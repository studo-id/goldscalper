"""Live runtime: wires data → agents → SPK → execution → learning.

This is the piece that turns the individual phases into a running bot:

* MT5 client (mock/native/bridge) + :class:`~core.mt5_connector.TickStreamer`
  feed candles into a shared :class:`~core.market_data.MarketDataCache`.
* A state builder snapshots the cache + quote + account into a
  :class:`~agents.state.SharedState`.
* The :class:`~agents.orchestrator.Orchestrator` runs the decision cycle and a
  pre-trade :func:`~execution.risk_gate.apply` gate.
* :class:`~execution.order_manager.OrderManager` opens trades and
  :class:`~execution.position_manager.PositionManager` manages them; closed
  trades feed :meth:`Orchestrator.on_trade_closed`.

Persistence is optional so the runtime is usable in tests without a database.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from agents.divisions import build_all_agents
from agents.learning import BanditOptimizer, PatternLibrary
from agents.message_bus import MemoryBus
from agents.orchestrator import Orchestrator
from agents.registry import AgentRegistry
from agents.state import SharedState, utcnow
from config.logging import get_logger
from config.settings import Settings
from config.settings import settings as default_settings
from core.calendar_service import EconomicCalendarService
from core.clock import MarketClock
from core.cross_asset import CrossAssetService
from core.wave_engine import DataDrivenWaveEngine
from core.news_sentiment_service import NewsSentimentService
from core.market_data import MarketDataCache
from core.mt5_connector import MT5Client, TickStreamer, create_client
from core.notifier import Notifier
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from execution.risk_gate import apply as risk_gate_apply
from spk.decision import ACTION_HOLD

log = get_logger("runtime")
WIB = timezone(timedelta(hours=7))


class Runtime:
    """Owns the live decision + execution loops."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: MT5Client | None = None,
        registry: AgentRegistry | None = None,
        cache: MarketDataCache | None = None,
        notifier: Notifier | None = None,
        clock: MarketClock | None = None,
        enable_persistence: bool = True,
        frame_depth: int = 250,
    ) -> None:
        self.settings = settings or default_settings
        self.symbol = self.settings.mt5_symbol
        self.clock = clock or MarketClock()
        self.calendar = EconomicCalendarService(
            pre_news_minutes=getattr(self.settings, "news_blackout_pre_minutes", 30),
            post_news_minutes=getattr(self.settings, "news_blackout_post_minutes", 20),
        )
        self.news_sentiment = NewsSentimentService()
        self.wave_engine = DataDrivenWaveEngine(broken_wave_cooldown_s=90, idle_reset_s=150)
        self._persistence = enable_persistence
        self._frame_depth = frame_depth

        self.client: MT5Client = client or create_client(self.settings)
        suffix = "m" if self.symbol.endswith("m") else ("c" if self.symbol.endswith("c") else "")
        self.cross_asset = CrossAssetService(
            client=self.client,
            symbol_suffix=suffix,
            poll_interval_s=3.0,
        )
        self.cache = cache or MarketDataCache()
        self.bus = MemoryBus()
        self.registry = registry or self._build_registry()
        self.notifier = notifier or Notifier(self.settings)

        self.streamer = TickStreamer(
            self.client,
            symbol=self.symbol,
            bus=self.bus,
            cache=self.cache,
            repo=None,
            poll_interval=0.08,
        )

        self.order_manager = OrderManager(
            self.client, self.settings, trade_repo=None, notifier=self.notifier
        )
        self.position_manager = PositionManager(
            self.client, self.settings, notifier=self.notifier
        )

        self.bandit = BanditOptimizer()
        self.patterns = PatternLibrary()

        self.orchestrator = Orchestrator(
            self.registry,
            settings=self.settings,
            bus=self.bus,
            state_builder=self._build_state,
            decision_repo=None,
            risk_gate=risk_gate_apply,
            broadcast=True,
            bandit=self.bandit,
            pattern_library=self.patterns,
        )

        self._task: asyncio.Task | None = None
        self._running = False
        self.paused = False
        self._predator_reload_side: str | None = None
        self._predator_reload_expiry: datetime | None = None
        self._trades: dict[int, dict[str, Any]] = {}
        self.orders_placed = 0
        self._last_equity: float = 10000.0
        self._last_balance: float = 10000.0

        # --- Scalper Radar Watchdog Trackers ---
        self._last_order_placed_at: datetime = utcnow()
        self._last_radar_report_at: datetime = utcnow()
        self._last_radar_snapshot: dict[str, Any] | None = None

        # --- The Juggler & BizDev Day Trackers ---
        self._sod_date = utcnow().astimezone(WIB).date()
        self._sod_balance: float | None = None
        self._daily_realized_pnl: float = 0.0
        self._daily_gross_profit: float = 0.0
        self._daily_gross_loss: float = 0.0
        self._daily_lots_traded: float = 0.0
        self._daily_friction_cost: float = 0.0
        self._daily_win_count: int = 0
        self._live_avg_win: float = 7.31

    # --- construction helpers --------------------------------------------------
    def _build_registry(self) -> AgentRegistry:
        registry = AgentRegistry()
        registry.register_all(build_all_agents())
        return registry

    def _wire_persistence(self) -> None:
        """Attach DB-backed repositories (best-effort, optional)."""
        if not self._persistence:
            return
        try:
            from data.repositories import (
                AgentDecisionRepository,
                AgentWeightRepository,
                LessonRepository,
                MarketDataRepository,
                TradeRepository,
            )

            self.streamer.repo = MarketDataRepository()
            self.orchestrator.decision_repo = AgentDecisionRepository()
            self.orchestrator.lesson_repo = LessonRepository()
            self.order_manager.trade_repo = TradeRepository()
            self._weights_repo = AgentWeightRepository()
        except Exception as exc:  # noqa: BLE001
            log.warning("persistence unavailable: %s", exc)

    # --- state -----------------------------------------------------------------
    async def _build_state(self) -> SharedState:
        quote = self.streamer.last_quote
        frames = {
            tf: self.cache.latest(self.symbol, tf, self._frame_depth)
            for tf in ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
        }
        frames = {tf: rows for tf, rows in frames.items() if rows}
        now_dt = utcnow()
        session = self.clock.primary_session(now_dt)
        extra_state: dict[str, Any] = {}
        if self._predator_reload_side and self._predator_reload_expiry and now_dt <= self._predator_reload_expiry:
            extra_state["predator_reload_side"] = self._predator_reload_side
        else:
            self._predator_reload_side = None

        # Institutional Session Timing Evaluation (London Open Freeze & Hard Cutoff)
        if getattr(self.settings, "london_open_freeze_enabled", True) and self.clock.is_london_open_freeze(now_dt):
            extra_state["london_open_freeze"] = True
        if getattr(self.settings, "hard_cutoff_utc_enabled", True) and self.clock.is_hard_cutoff(now_dt):
            extra_state["session_hard_cutoff"] = True

        # Real-time Economic Calendar & News Blackout
        try:
            await self.calendar.ensure_fresh()
            blackout, current_news = self.calendar.check_blackout(now_dt)
            upcoming = self.calendar.upcoming_events(now_dt, hours=12)
            extra_state["news_blackout"] = blackout
            extra_state["current_news"] = current_news
            extra_state["calendar_events"] = upcoming
        except Exception as exc:  # noqa: BLE001
            log.debug("economic calendar check error: %s", exc)

        # Cross-asset feeds (EURUSD, USDJPY, GBPUSD, Silver -> Synthetic DXY & Deltas)
        try:
            cross_data = await self.cross_asset.update(current_session=session)
            extra_state.update(cross_data)
        except Exception as exc:  # noqa: BLE001
            log.debug("cross-asset update error: %s", exc)

        # Real-time News Sentiment & Fed Macro Regime
        try:
            await self.news_sentiment.ensure_fresh()
            sent_data = self.news_sentiment.get_state()
            extra_state.update(sent_data)
        except Exception as exc:  # noqa: BLE001
            log.debug("news sentiment update error: %s", exc)

        # SPK Momentum & High-Conviction Confluence Feed for Evaluating Agents
        last_dec = getattr(self.orchestrator, "last_decision", None)
        if last_dec is not None:
            extra_state["spk_confidence"] = float(last_dec.confidence or 0.0)
            extra_state["spk_score"] = float(last_dec.score or 0.0)
            extra_state["high_confluence"] = (
                float(last_dec.confidence or 0.0) >= 0.70 or abs(float(last_dec.score or 0.0)) >= 5.0
            )

        extra_state["wave_engine"] = self.wave_engine

        state = SharedState(
            symbol=self.symbol,
            ts=now_dt,
            frames=frames,
            session=session,
            bid=quote.bid if quote else None,
            ask=quote.ask if quote else None,
            spread_points=(quote.spread * 10.0) if quote else None,
            extra=extra_state,
        )

        positions = await self._safe_positions()
        acc_info = await self._safe_account_info()
        unrealized = sum(float(getattr(p, "profit", 0.0) or 0.0) for p in positions)
        balance = float(acc_info.get("balance") or 10000.0)
        equity = float(acc_info.get("equity") or (balance + unrealized))

        self._last_equity = equity
        self._last_balance = balance

        # --- The Juggler & BizDev Day Rollover & PnL Engine ---
        today_date = now_dt.astimezone(WIB).date()
        if today_date != self._sod_date:
            self._sod_date = today_date
            self._sod_balance = balance
            self._daily_realized_pnl = 0.0
            self._daily_gross_profit = 0.0
            self._daily_gross_loss = 0.0
            self._daily_lots_traded = 0.0
            self._daily_friction_cost = 0.0
            self._daily_win_count = 0
            self._live_avg_win = 0.0
        elif self._sod_balance is None and balance > 0:
            # Reconstruct true start-of-day balance using preloaded realized PnL from DB
            # e.g. If balance now is $9,435 and realized_pnl is -$565, sod_b = 9435 - (-565) = $10,000!
            self._sod_balance = max(100.0, balance - self._daily_realized_pnl)

        sod_b = self._sod_balance or balance
        daily_pnl = (equity - sod_b) if sod_b > 0 else 0.0
        daily_pnl_pct = (daily_pnl / sod_b * 100.0) if sod_b > 0 else 0.0

        state.equity = equity
        state.balance = balance
        state.balance_start_of_day = sod_b
        state.daily_realized_pnl = self._daily_realized_pnl
        state.daily_pnl_pct = daily_pnl_pct
        state.daily_gross_profit = self._daily_gross_profit
        state.daily_friction_cost = self._daily_friction_cost
        state.daily_lots_traded = self._daily_lots_traded

        # Evaluate profit lock circuit breaker
        target_usd = sod_b * (self.settings.daily_profit_target_pct / 100.0)
        remaining_target_usd = max(0.0, target_usd - self._daily_realized_pnl)
        state.extra["target_usd"] = target_usd
        state.extra["remaining_target_usd"] = remaining_target_usd
        state.extra["live_avg_win"] = self._live_avg_win
        state.extra["daily_win_count"] = self._daily_win_count

        if (
            self.settings.juggler_enabled
            and self.settings.daily_profit_lock_enabled
            and daily_pnl_pct >= self.settings.daily_profit_target_pct
        ):
            state.daily_profit_locked = True

        now_dt = utcnow()
        pos_list = []
        for p in positions:
            trade_info = self._trades.get(p.ticket, {})
            opened_at = trade_info.get("opened_at") or p.time or now_dt
            age_s = int((now_dt - opened_at).total_seconds()) if opened_at else 0
            pos_list.append(
                {
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "direction": p.side,
                    "volume": p.volume,
                    "price_open": p.price_open,
                    "sl": p.sl,
                    "tp": p.tp,
                    "price_current": p.price_current,
                    "profit": p.profit,
                    "age_seconds": age_s,
                    "opened_at": opened_at.isoformat() if hasattr(opened_at, "isoformat") else str(opened_at),
                }
            )
        state.positions = pos_list
        return state

    async def _safe_positions(self) -> list[Any]:
        try:
            return await self.client.positions(self.symbol)
        except Exception as exc:  # noqa: BLE001
            log.debug("positions fetch failed: %s", exc)
            return []

    async def _safe_account_info(self) -> dict[str, Any]:
        if hasattr(self.client, "account_info"):
            try:
                info = await self.client.account_info()
                if info and isinstance(info, dict):
                    return info
            except Exception as exc:  # noqa: BLE001
                log.debug("account_info fetch failed: %s", exc)
        return {}

    # --- one execution cycle ---------------------------------------------------
    async def step(self) -> Any:
        """Run one decision + execution + position-management tick."""
        # 1. Manage and reconcile existing positions first (SL/TP, trailing, cutloss, cooldown arming)
        await self._manage_positions()

        if self.paused:
            return self.orchestrator.last_decision

        decision = await self.orchestrator.run_cycle()
        state = self.orchestrator.last_state

        if (
            state is not None
            and decision.action != ACTION_HOLD
            and not decision.hard_veto
            and decision.size
        ):
            result = await self.order_manager.execute(decision, state)
            if result is not None and result.ok and result.ticket is not None:
                self.orders_placed += 1
                self._last_order_placed_at = utcnow()
                self.wave_engine.record_trade_opened(
                    decision.action,
                    price=float(result.price or decision.entry or state.last_price() or 0.0),
                )
                risk = None
                if decision.entry is not None and decision.sl is not None:
                    risk = abs(decision.entry - decision.sl)
                self._trades[result.ticket] = {
                    "trade_id": result.trade_id,
                    "direction": decision.action,
                    "volume": float(result.size or decision.size or 0.0),
                    "entry": result.price or decision.entry,
                    "sl": decision.sl,
                    "tp": decision.tp,
                    "opened_at": utcnow(),
                    "risk": risk or 0.0,
                    "last_price": result.price or decision.entry,
                    "last_profit": 0.0,
                }

        # Scalper Radar Inactivity Watchdog Check (diagnose vetoes & market when idle)
        await self._check_scalper_radar(state, decision)

        return decision

    async def _manage_positions(self) -> None:
        positions = await self._safe_positions()
        live = {p.ticket: p for p in positions}

        # reconcile newly-seen positions (e.g. reopened after restart)
        for ticket, pos in live.items():
            if ticket not in self._trades and pos.magic == self.settings.mt5_magic:
                self.position_manager.track(pos)
                trade_id = None
                opened_at = pos.time or utcnow()
                if self.order_manager.trade_repo is not None:
                    try:
                        trade_info = await self.order_manager.trade_repo.find_open_trade_info(pos.ticket)
                        if trade_info:
                            trade_id, db_opened_at = trade_info
                            if db_opened_at:
                                opened_at = db_opened_at
                        else:
                            trade_id = await self.order_manager.trade_repo.find_open_by_ticket(pos.ticket)
                    except Exception as exc:  # noqa: BLE001
                        log.debug("find_open_trade_info failed for %s: %s", pos.ticket, exc)

                self._trades[ticket] = {
                    "trade_id": trade_id,
                    "direction": pos.side,
                    "volume": float(pos.volume),
                    "entry": pos.price_open,
                    "sl": pos.sl,
                    "tp": pos.tp,
                    "opened_at": opened_at,
                    "risk": abs(pos.price_open - (pos.sl or pos.price_open)),
                    "last_price": pos.price_current,
                    "last_profit": pos.profit,
                }

        # Multi-Entry Basket TP evaluation per side (BUY basket & SELL basket independently)
        our_positions = [p for p in positions if p.magic == self.settings.mt5_magic]
        our_buys = [p for p in our_positions if p.is_long]
        our_sells = [p for p in our_positions if not p.is_long]

        for side_name, group in [("BUY", our_buys), ("SELL", our_sells)]:
            if len(group) >= 2:
                quote = self.streamer.last_quote
                bid = quote.bid if quote else None
                ask = quote.ask if quote else None
                try:
                    basket_actions = await self.position_manager.manage_basket(group, bid, ask)
                    if "basket_tp_closed" in basket_actions or "basket_cut_closed" in basket_actions:
                        is_win = "basket_tp_closed" in basket_actions
                        log_tag = "TP" if is_win else "COLLECTIVE CUT"
                        log.info("BASKET %s EXECUTED for %d %s positions", log_tag, len(group), side_name)
                        if is_win:
                            self.order_manager.arm_cooldown(45, reason="post_basket_tp")
                            if self.settings.predator_reload_enabled:
                                self._predator_reload_side = side_name
                                self._predator_reload_expiry = utcnow() + timedelta(seconds=self.settings.predator_reload_window_s)
                                log.info("PREDATOR RELOAD ARMED for %s (window=%ds)", side_name, self.settings.predator_reload_window_s)
                        else:
                            self.order_manager.arm_m1_candle_cooldown(60, reason="post_basket_cut")

                        # Mark individual tickets so _finalize_closed inherits basket outcome
                        for p in group:
                            if p.ticket in self._trades:
                                self._trades[p.ticket]["basket_outcome_win"] = is_win

                        positions = await self._safe_positions()
                        live = {p.ticket: p for p in positions}
                except Exception as exc:  # noqa: BLE001
                    log.warning("manage_basket failed for %s: %s", side_name, exc)

        sod_b = self._sod_balance or self._last_balance or 10000.0
        target_usd = sod_b * (self.settings.daily_profit_target_pct / 100.0)
        remaining_target = max(0.0, target_usd - self._daily_realized_pnl)
        est_rebate = round(self._daily_lots_traded * self.settings.rebate_per_lot_usd, 2)
        mgmt_context = {
            "live_avg_win": self._live_avg_win,
            "remaining_target_usd": remaining_target,
            "target_usd": target_usd,
            "equity": self._last_equity,
            "balance_sod": sod_b,
            "rebate_usd": est_rebate,
            "decision": self.orchestrator.last_decision,
            "state": self.orchestrator.last_state,
        }

        # Identify tickets currently part of an active multi-position rescue basket
        rescue_basket_tickets: set[int] = set()
        for side_group in (our_buys, our_sells):
            if len(side_group) >= 2:
                has_pyramid = any("PYRAMID" in str(getattr(p, "comment", "") or "").upper() for p in side_group)
                sorted_side = sorted(side_group, key=lambda p: p.time or utcnow())
                is_long = side_group[0].is_long
                price_ascending = (
                    (is_long and sorted_side[-1].price_open > sorted_side[0].price_open + 0.30)
                    or (not is_long and sorted_side[-1].price_open < sorted_side[0].price_open - 0.30)
                )
                if not (has_pyramid or price_ascending):
                    for p in side_group:
                        rescue_basket_tickets.add(p.ticket)

        for ticket, info in list(self._trades.items()):
            pos = live.get(ticket)
            if pos is not None:
                info["last_price"] = pos.price_current or info["last_price"]
                info["last_profit"] = pos.profit
                info["volume"] = float(pos.volume)
                ticket_ctx = dict(mgmt_context)
                if ticket in rescue_basket_tickets:
                    ticket_ctx["in_rescue_basket"] = True
                try:
                    act = await self.position_manager.manage(
                        pos,
                        pos.price_current or pos.price_open,
                        context=ticket_ctx,
                    )
                    if any("clamp" in a or "cut" in a for a in act):
                        self.order_manager.arm_m1_candle_cooldown(60, reason="post_cutloss_clamp")
                    elif any("harvest" in a or "tp" in a for a in act):
                        regime = (self.orchestrator.last_state.extra.get("market_regime") if (self.orchestrator.last_state and self.orchestrator.last_state.extra) else "SIDEWAY")
                        win_cd = 45 if "TRENDING" in str(regime) else 60
                        self.order_manager.arm_cooldown(win_cd, reason="post_profit_harvest")
                except Exception as exc:  # noqa: BLE001
                    log.warning("position manage failed (%s): %s", ticket, exc)
            else:
                await self._finalize_closed(ticket, info)

    async def _finalize_closed(self, ticket: int, info: dict[str, Any]) -> None:
        self.position_manager.untrack(ticket)
        self._trades.pop(ticket, None)

        pnl = float(info.get("last_profit", 0.0) or 0.0)
        vol = float(info.get("volume", 0.01) or 0.01)
        side = str(info.get("direction") or info.get("side") or "BUY").upper()

        # Basket unity: If trade was closed as part of a winning basket, it counts as a WIN for wave engine!
        if info.get("basket_outcome_win") is True:
            is_trade_win = True
        elif info.get("basket_outcome_win") is False:
            is_trade_win = False
        else:
            is_trade_win = (pnl > 0)
        self.wave_engine.record_trade_closed(is_win=is_trade_win, direction=side)

        if not self._trades:
            if pnl > 0:
                regime = (self.orchestrator.last_state.extra.get("market_regime") if (self.orchestrator.last_state and self.orchestrator.last_state.extra) else "SIDEWAY")
                win_cd = 45 if "TRENDING" in str(regime) else 60
                self.order_manager.arm_cooldown(win_cd, reason="post_win_chaining")
            else:
                self.order_manager.arm_m1_candle_cooldown(60, reason="post_trade_cutloss")

        # Update daily telemetry and BizDev trackers
        self._daily_realized_pnl += pnl
        if pnl > 0:
            self._daily_gross_profit += pnl
            self._daily_win_count += 1
            if self._daily_win_count > 0:
                self._live_avg_win = round(self._daily_gross_profit / self._daily_win_count, 2)
        else:
            self._daily_gross_loss += abs(pnl)
        self._daily_lots_traded += vol
        spread_pts = float(self.streamer.last_quote.spread * 10.0) if (self.streamer.last_quote and self.streamer.last_quote.spread) else 15.0
        friction_per_lot = self.settings.commission_per_lot + (spread_pts * 0.10)
        self._daily_friction_cost += round(vol * friction_per_lot, 2)
        entry = info.get("entry")
        exit_price = info.get("last_price") or entry
        pips = 0.0
        if entry and exit_price:
            raw = (exit_price - entry) if info.get("direction") == "BUY" else (entry - exit_price)
            pips = raw * 10.0
        opened_at: datetime | None = info.get("opened_at")
        duration = int((utcnow() - opened_at).total_seconds()) if opened_at else 0
        trade_id = info.get("trade_id")

        if self.order_manager.trade_repo is not None:
            if not trade_id:
                try:
                    trade_id = await self.order_manager.trade_repo.find_open_by_ticket(ticket)
                except Exception:
                    trade_id = None

            if trade_id:
                try:
                    await self.order_manager.trade_repo.close_trade(
                        trade_id, exit_price or 0.0, pnl, pips, duration
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("close_trade persist failed: %s", exc)
            else:
                try:
                    trade_id = await self.order_manager.trade_repo.record_closed_trade(
                        ticket=ticket,
                        direction=info.get("direction", "BUY"),
                        size=info.get("volume", 0.01),
                        entry_price=entry or 0.0,
                        exit_price=exit_price or 0.0,
                        pnl=pnl,
                        pips=pips,
                        duration_s=duration,
                        symbol=self.symbol,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.debug("record_closed_trade fallback failed: %s", exc)

        try:
            await self.orchestrator.on_trade_closed(
                {
                    "id": trade_id,
                    "pnl": pnl,
                    "pips": pips,
                    "duration_s": duration,
                    "direction": info.get("direction"),
                    "symbol": self.symbol,
                    "regime": None,
                },
                {"spread_points": None},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("learning on close failed: %s", exc)

        if self.notifier.enabled:
            try:
                await self.notifier.trade_closed(
                    {
                        "symbol": self.symbol,
                        "ticket": ticket,
                        "pnl": pnl,
                        "pips": pips,
                        "duration_s": duration,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("notify close failed: %s", exc)

    # --- manual control --------------------------------------------------------
    async def panic_close(self) -> int:
        """Close every open position immediately; returns the count closed."""
        closed = 0
        for pos in await self._safe_positions():
            info = self._trades.get(pos.ticket)
            try:
                result = await self.client.close_position(pos.ticket)
                if not result.ok and result.comment != "no such position":
                    continue
                if info is None:
                    info = {
                        "trade_id": None,
                        "direction": pos.side,
                        "entry": pos.price_open,
                        "sl": pos.sl,
                        "tp": pos.tp,
                        "opened_at": utcnow(),
                        "risk": abs(pos.price_open - (pos.sl or pos.price_open)),
                        "last_price": pos.price_current or pos.price_open,
                        "last_profit": pos.profit,
                    }
                await self._finalize_closed(pos.ticket, info)
                closed += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("panic close failed (%s): %s", pos.ticket, exc)
        if closed:
            log.warning("PANIC: closed %d positions", closed)
        return closed

    async def close_single_position(self, ticket: int) -> dict[str, Any]:
        """Close a specific open position by ticket."""
        info = self._trades.get(ticket)
        result = await self.client.close_position(ticket)
        if result.ok or result.comment == "no such position":
            if info is not None:
                await self._finalize_closed(ticket, info)
            return {"ok": True, "ticket": ticket}
        return {"ok": False, "ticket": ticket, "error": result.comment}

    async def manual_order(
        self,
        side: str,
        size: float,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict[str, Any]:
        """Submit a manual market order (bypasses SPK). Returns a result dict."""
        from core.mt5_connector import OrderRequest

        request = OrderRequest(
            symbol=self.symbol,
            side=side.upper(),
            volume=float(size),
            sl=sl,
            tp=tp,
            magic=self.settings.mt5_magic,
            deviation=self.settings.mt5_deviation,
            comment="manual",
            order_type="market",
        )
        result = await self.client.order_send(request)
        if result.ok and result.ticket is not None:
            self.orders_placed += 1
        return {
            "ok": result.ok,
            "ticket": result.ticket,
            "price": result.price,
            "volume": result.volume,
            "reason": result.comment,
        }

    # --- loop ------------------------------------------------------------------
    async def run_forever(self) -> None:
        interval = max(0.05, self.settings.cycle_interval_ms / 1000.0)
        self._running = True
        log.info("runtime loop started (interval=%.3fs, agents=%d)", interval, self.registry.size)
        while self._running:
            started = utcnow()
            try:
                await self.step()
            except Exception as exc:  # noqa: BLE001
                log.error("runtime step error: %s", exc)
            elapsed = (utcnow() - started).total_seconds()
            await asyncio.sleep(max(0.0, interval - elapsed))

    # --- lifecycle -------------------------------------------------------------
    async def start(self) -> None:
        self._wire_persistence()
        if not self.client.connected:
            try:
                await self.client.connect()
            except Exception as exc:
                if self.settings.mt5_mock:
                    log.warning(
                        "MT5 connect failed (%s); falling back to MockMT5Client so cockpit stays live",
                        exc,
                    )
                    from core.mt5_connector import MockMT5Client

                    self.client = MockMT5Client()
                    await self.client.connect()
                    self.streamer.client = self.client
                    self.order_manager.client = self.client
                    self.position_manager.client = self.client
                else:
                    log.warning(
                        "MT5 initial connect failed (%s); retaining bridge client and will auto-reconnect",
                        exc,
                    )
        if self._persistence and getattr(self, "_weights_repo", None) is not None:
            try:
                weights = await self._weights_repo.load()
                self.registry.load_weights(weights)
            except Exception as exc:  # noqa: BLE001
                log.warning("load weights failed: %s", exc)

        repo = getattr(self.order_manager, "trade_repo", None)
        if self._persistence and repo is not None:
            try:
                live_positions = await self._safe_positions()
                live_tickets = [p.ticket for p in live_positions if p.magic == self.settings.mt5_magic]
                cleaned = await repo.reconcile_orphaned_trades(live_tickets)
                if cleaned > 0:
                    log.info("reconciled %d orphaned OPEN trade(s) in DB", cleaned)

                # Preload today's portfolio statistics for dynamic Juggler SL/TP (WIB 00:00:00)
                now_dt = utcnow()
                now_wib = now_dt.astimezone(WIB)
                today_s = datetime(now_wib.year, now_wib.month, now_wib.day, tzinfo=WIB)
                today_stats = await repo.aggregate(since=today_s, until=now_dt)
                self._daily_win_count = int(today_stats.get("wins", 0) or 0)
                self._daily_gross_profit = float(today_stats.get("gross_profit", 0.0) or 0.0)
                self._daily_gross_loss = float(today_stats.get("gross_loss", 0.0) or 0.0)
                self._daily_realized_pnl = float(today_stats.get("total_pnl", 0.0) or 0.0)
                self._daily_lots_traded = float(today_stats.get("total_lots", 0.0) or 0.0)
                if self._daily_win_count > 0:
                    self._live_avg_win = round(self._daily_gross_profit / self._daily_win_count, 2)
                log.info(
                    "PRELOADED TODAY PORTFOLIO STATS: wins=%d, avg_win=$%.2f, gross_profit=$%.2f, gross_loss=$%.2f",
                    self._daily_win_count,
                    self._live_avg_win,
                    self._daily_gross_profit,
                    self._daily_gross_loss,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("startup trade reconcile/preload failed: %s", exc)

        # Warm up candle history from broker bridge so technical and structure agents wake up immediately
        if hasattr(self.client, "copy_rates"):
            tf_lookbacks = {
                "M1": timedelta(hours=6),
                "M5": timedelta(hours=12),
                "M15": timedelta(hours=24),
                "M30": timedelta(hours=48),
                "H1": timedelta(days=5),
                "H4": timedelta(days=15),
                "D1": timedelta(days=30),
            }
            for tf, lookback in tf_lookbacks.items():
                try:
                    now = utcnow()
                    start_time = now - lookback
                    bars = await self.client.copy_rates(self.symbol, tf, start_time, now)
                    for b in bars:
                        self.cache.append(b)
                    if bars:
                        log.info("warmed up %d %s candles for %s", len(bars), tf, self.symbol)
                except Exception as exc:  # noqa: BLE001
                    log.warning("candle warm-up failed for %s (%s): %s", self.symbol, tf, exc)

        self.streamer.start()
        self._running = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever(), name="gs-runtime")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception) as exc:  # noqa: BLE001
                log.debug("runtime task ended: %s", exc)
            self._task = None
        await self.streamer.stop()
        try:
            await self.notifier.close()
        except Exception as exc:  # noqa: BLE001
            log.debug("notifier close failed: %s", exc)
        log.info("runtime stopped (orders=%d)", self.orders_placed)

    # --- Scalper Radar Inactivity Watchdog -------------------------------------
    async def _check_scalper_radar(self, state: SharedState | None, decision: Any) -> None:
        """Examine market structure, M1 channel, and veto deadlocks periodically when idle."""
        if not getattr(self.settings, "radar_watchdog_enabled", True) or state is None or decision is None:
            return

        now_dt = utcnow()
        idle_s = (now_dt - self._last_order_placed_at).total_seconds()
        interval = getattr(self.settings, "radar_report_interval_s", 300)

        if idle_s >= interval and (now_dt - self._last_radar_report_at).total_seconds() >= interval:
            self._last_radar_report_at = now_dt
            await self._emit_scalper_radar_report(state, decision, idle_s)

    async def _emit_scalper_radar_report(self, state: SharedState, decision: Any, idle_s: float) -> None:
        from agents.state import VETO_ALL, VETO_BUY, VETO_SELL

        idle_min = round(idle_s / 60.0, 1)
        votes = getattr(decision, "votes", []) or []

        # 1. Veto & Deadlock Diagnostics:
        buyer_blockers = [v for v in votes if getattr(v, "veto", None) in (VETO_BUY, VETO_ALL)]
        seller_blockers = [v for v in votes if getattr(v, "veto", None) in (VETO_SELL, VETO_ALL)]
        deadlock = bool(buyer_blockers and seller_blockers and not any(getattr(v, "veto", None) == VETO_ALL for v in votes))
        veto_all_active = any(getattr(v, "veto", None) == VETO_ALL for v in votes)

        if veto_all_active:
            blocker_desc = "M1 Mid Dead Zone (30%-70% chop, VETO_ALL)"
            conflict_status = "MID_CHOP_DEAD_ZONE"
        elif deadlock:
            b_name = buyer_blockers[0].agent_id
            s_name = seller_blockers[0].agent_id
            blocker_desc = f"Deadlock: {b_name} (VETO_BUY) vs {s_name} (VETO_SELL)"
            conflict_status = "DEADLOCK_CONFLICT"
        elif buyer_blockers:
            blocker_desc = f"Blocked BUY: {buyer_blockers[0].agent_id} ({buyer_blockers[0].reasoning or buyer_blockers[0].veto})"
            conflict_status = "BUY_VETOED"
        elif seller_blockers:
            blocker_desc = f"Blocked SELL: {seller_blockers[0].agent_id} ({seller_blockers[0].reasoning or seller_blockers[0].veto})"
            conflict_status = "SELL_VETOED"
        elif getattr(decision, "hard_veto", False):
            blocker_desc = f"Hard Veto: {getattr(decision, 'veto_reason', 'circuit_breaker')}"
            conflict_status = "HARD_VETO"
        elif getattr(decision, "action", None) == "HOLD":
            blocker_desc = f"Neutral SPK Consensus (Score: {getattr(decision, 'score', 0.0):+.2f})"
            conflict_status = "SPK_NEUTRAL"
        else:
            blocker_desc = "Awaiting execution trigger"
            conflict_status = "READY"

        # 2. M1 Tactical Scalper Snapshot:
        extra = getattr(state, "extra", {}) or {}
        close = state.last_price() or 0.0
        m1_sup = float(extra.get("m1_support") or 0.0)
        m1_res = float(extra.get("m1_resistance") or 0.0)
        m1_span = float(extra.get("m1_span") or (m1_res - m1_sup if m1_res > m1_sup else 0.0))
        m1_pos = float(extra.get("m1_pos_pct") or 0.5)

        # 3. M5 Wave Dynamics:
        trend_sig = next((v for v in votes if getattr(v, "agent_id", None) == "Tech-Trend"), None)
        vol_sig = next((v for v in votes if getattr(v, "agent_id", None) == "Tech-Volatility"), None)
        trend_desc = trend_sig.reasoning if trend_sig else "Trend neutral"
        vol_desc = (vol_sig.metadata.get("regime") if vol_sig and hasattr(vol_sig, "metadata") and isinstance(vol_sig.metadata, dict) else "normal")

        # 4. Actionable Scalper Triggers:
        triggers: dict[str, str] = {}
        if m1_sup > 0 and m1_res > m1_sup:
            sell_lvl = m1_res - (0.30 * m1_span)
            buy_lvl = m1_sup + (0.30 * m1_span)
            triggers["ping_sell"] = f"SELL >= ${sell_lvl:.2f} (Upper 30%)"
            triggers["pong_buy"] = f"BUY <= ${buy_lvl:.2f} (Lower 30%)"
            triggers["breakout_buy"] = f"BUY Breakout > ${m1_res + 1.20:.2f}"
            triggers["breakdown_sell"] = f"SELL Breakdown < ${m1_sup - 1.20:.2f}"

        report = {
            "idle_minutes": idle_min,
            "status": conflict_status,
            "blocker": blocker_desc,
            "close": close,
            "m1_range": {
                "support": m1_sup,
                "resistance": m1_res,
                "span": round(m1_span, 2),
                "position_pct": round(m1_pos * 100.0, 1),
            },
            "m5_wave": {
                "trend": trend_desc,
                "volatility": vol_desc,
            },
            "triggers": triggers,
            "spk_score": getattr(decision, "score", 0.0),
            "ts": utcnow().isoformat(),
        }
        self._last_radar_snapshot = report

        log.info(
            "SCALPER RADAR [idle=%0.1fm]: %s | Price: $%.2f (pos %0.1f%% of $%.2f M1 span: $%.2f-$%.2f) | M5: %s (%s) | Triggers: %s",
            idle_min,
            blocker_desc,
            close,
            m1_pos * 100.0,
            m1_span,
            m1_sup,
            m1_res,
            trend_desc,
            vol_desc,
            ", ".join(f"{k}: {v}" for k, v in triggers.items()) if triggers else "None",
        )

        try:
            from api.ws_manager import manager
            if manager.count > 0:
                await manager.broadcast({"type": "scalper_radar", "data": report})
        except Exception as exc:  # noqa: BLE001
            log.debug("scalper radar ws broadcast error: %s", exc)

    # --- introspection ---------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        mt5_trade_allowed = getattr(self.client, "trade_allowed", True)
        return {
            "running": self._running,
            "paused": self.paused,
            "algo_trading": mt5_trade_allowed and not self.paused,
            "mt5_trade_allowed": mt5_trade_allowed,
            "symbol": self.symbol,
            "agents": self.registry.size,
            "divisions": {d: len(a) for d, a in self.registry.divisions().items()},
            "orders_placed": self.orders_placed,
            "open_trades": len(self._trades),
            "streamer": self.streamer.snapshot(),
            "orchestrator": self.orchestrator.snapshot(),
            "patterns": self.patterns.top(5),
            "scalper_radar": self._last_radar_snapshot,
        }

    def agent_health(self) -> list[dict[str, Any]]:
        rows = self.registry.health()
        # annotate with bandit winrate where we have samples
        for row in rows:
            stats = self.bandit.snapshot().get(row["id"])
            row["winrate"] = stats["winrate"] if stats else None
        return rows

    def telemetry(self) -> dict[str, Any]:
        """Lightweight payload for WebSocket/telemetry pushes."""
        d = self.orchestrator.last_decision
        quote = self.streamer.last_quote
        q_time = None
        if quote and getattr(quote, "time", None):
            q_time = quote.time.isoformat() if hasattr(quote.time, "isoformat") else str(quote.time)
        mt5_trade_allowed = getattr(self.client, "trade_allowed", True)
        positions_list = []
        for ticket, info in list(self._trades.items()):
            opened_at = info.get("opened_at")
            opened_str = (
                opened_at.isoformat()
                if hasattr(opened_at, "isoformat")
                else str(opened_at)
                if opened_at
                else None
            )
            cur = info.get("last_price")
            profit = float(info.get("last_profit", 0.0) or 0.0)
            if quote and quote.bid and quote.ask and info.get("entry"):
                direction = (info.get("direction") or "BUY").upper()
                cur = quote.bid if direction == "BUY" else quote.ask
                diff = (cur - info["entry"]) if direction == "BUY" else (info["entry"] - cur)
                vol = float(info.get("volume") or 0.01)
                profit = round(diff * vol * 100.0, 2)
            positions_list.append({
                "ticket": ticket,
                "direction": info.get("direction"),
                "side": info.get("direction"),
                "volume": float(info.get("volume") or 0.0),
                "size": float(info.get("volume") or 0.0),
                "entry": info.get("entry"),
                "open_price": info.get("entry"),
                "price_open": info.get("entry"),
                "sl": info.get("sl"),
                "tp": info.get("tp"),
                "opened_at": opened_str,
                "price_current": cur,
                "last_price": cur,
                "pnl": profit,
                "profit": profit,
                "last_profit": profit,
            })

        cd_rem = 0
        cd_reason = None
        if hasattr(self, "order_manager") and self.order_manager and self.order_manager.in_cooldown:
            if self.order_manager._cooldown_until:
                cd_rem = max(0, int((self.order_manager._cooldown_until - utcnow()).total_seconds()))
            cd_reason = self.order_manager._cooldown_reason

        cur_news = None
        is_news_blackout = False
        if hasattr(self, "orchestrator") and self.orchestrator and self.orchestrator.last_state:
            is_news_blackout = self.orchestrator.last_state.is_news_blackout()
            cur_news = self.orchestrator.last_state.extra.get("current_news")

        return {
            "running": self._running,
            "paused": self.paused,
            "algo_trading": mt5_trade_allowed and not self.paused,
            "mt5_trade_allowed": mt5_trade_allowed,
            "symbol": self.symbol,
            "bid": quote.bid if quote else None,
            "ask": quote.ask if quote else None,
            "ts": q_time or utcnow().isoformat(),
            "cycles": self.orchestrator.cycle_count,
            "orders_placed": self.orders_placed,
            "open_trades": len(self._trades),
            "positions": positions_list,
            "equity": self._last_equity,
            "balance": self._last_balance,
            "cooldown_remaining_s": cd_rem,
            "cooldown_reason": cd_reason,
            "news_blackout": is_news_blackout,
            "current_news": cur_news,
            "juggler": {
                "enabled": self.settings.juggler_enabled,
                "daily_target_pct": self.settings.daily_profit_target_pct,
                "daily_pnl_pct": round(((self._last_equity - (self._sod_balance or self._last_balance or 10000.0)) / (self._sod_balance or self._last_balance or 10000.0) * 100.0), 2),
                "progress_pct": min(100.0, max(0.0, round((((self._last_equity - (self._sod_balance or self._last_balance or 10000.0)) / (self._sod_balance or self._last_balance or 10000.0) * 100.0) / max(0.01, self.settings.daily_profit_target_pct) * 100.0), 1))),
                "status": "LOCKED" if (self.settings.juggler_enabled and self.settings.daily_profit_lock_enabled and ((self._last_equity - (self._sod_balance or self._last_balance or 10000.0)) / (self._sod_balance or self._last_balance or 10000.0) * 100.0) >= self.settings.daily_profit_target_pct) else "ACTIVE",
                "daily_realized_pnl": round(self._daily_realized_pnl, 2),
                "remaining_usd": max(0.0, round(((self._sod_balance or self._last_balance or 10000.0) * (self.settings.daily_profit_target_pct / 100.0)) - self._daily_realized_pnl, 2)),
                "profit_locked": (
                    self.settings.juggler_enabled
                    and self.settings.daily_profit_lock_enabled
                    and ((self._last_equity - (self._sod_balance or self._last_balance or 10000.0)) / (self._sod_balance or self._last_balance or 10000.0) * 100.0) >= self.settings.daily_profit_target_pct
                ),
                "hard_clamp_usd": self.settings.hard_loss_clamp_usd,
                "live_avg_win": self._live_avg_win,
                "daily_win_count": self._daily_win_count,
                "sod_balance": round(self._sod_balance or self._last_balance or 10000.0, 2),
            },
            "bizdev": {
                "enabled": self.settings.bizdev_enabled,
                "total_lots_today": round(self._daily_lots_traded, 2),
                "estimated_rebate_usd": round(self._daily_lots_traded * self.settings.rebate_per_lot_usd, 2),
                "friction_cost_usd": round(self._daily_friction_cost, 2),
                "friction_ratio_pct": round((self._daily_friction_cost / self._daily_gross_profit) * 100.0, 1) if self._daily_gross_profit > 0 else 0.0,
                "net_yield_usd": round(self._daily_realized_pnl + (self._daily_lots_traded * self.settings.rebate_per_lot_usd) - self._daily_friction_cost, 2),
            },
            "decision": {
                "action": d.action,
                "strength": d.strength,
                "score": d.score,
                "confidence": d.confidence,
                "size": d.size,
                "sl": d.sl,
                "tp": d.tp,
                "hard_veto": d.hard_veto,
                "veto_reason": d.veto_reason,
                "division_scores": d.division_scores,
            }
            if d is not None
            else None,
            "scalper_radar": self._last_radar_snapshot,
        }


__all__ = ["Runtime"]
