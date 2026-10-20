// GoldScalper — view renderers: cockpit (with realtime candlestick chart),
// agents, divisions, performance, lessons, control.

import {
  drawEquity,
  drawRadar,
  emptyState,
  esc,
  fmtMoney,
  fmtNum,
  fmtPct,
  fmtPnl,
  fmtPrice,
  hydrateIcons,
  icon,
  openModal,
  pnlClass,
  relTime,
  formatStreamingDuration,
  formatWIB,
  toast,
  voteClass,
  voteLabel,
} from "./components.js?v=20261020_01";
import { api, manualOrder, panic, setState, state } from "./ws.js?v=20261014_17";
import { PriceChart } from "./chart.js?v=20261015_01";

const sigArrow = (action) =>
  action === "BUY" ? "up" : action === "SELL" ? "down" : "dot";

const TF_LIST = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

function renderTfIcon(vote = 0) {
  if (vote > 0) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round" class="tf-scout-svg up" aria-hidden="true"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>`;
  }
  if (vote < 0) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round" class="tf-scout-svg down" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"></line><polyline points="19 12 12 19 5 12"></polyline></svg>`;
  }
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round" class="tf-scout-svg flat" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"></line></svg>`;
}

function getTfVote(tf, votes = []) {
  if (!votes || !votes.length) return 0;
  const match = votes.find((v) => v.timeframe === tf || (v.agent_id && v.agent_id.toLowerCase().includes(tf.toLowerCase())));
  return match ? (match.vote || 0) : 0;
}

export const COCKPIT_SUBTABS = {
  positions: "positions",
  pos: "positions",
  open: "positions",
  trace: "trace",
  votes: "trace",
  spk: "trace",
  trades: "trades",
  recent: "trades",
  closed: "trades",
  history: "trades",
};

/* ============================================================== cockpit */
export const cockpit = {
  title: "Cockpit",
  sub: "live consensus",
  icon: "gauge",
  chart: null,
  activeTf: "M1",
  activeTab: "positions",
  ticketSide: "BUY",
  ticketLot: 0.10,
  _lastCycles: -1,
  _lastOpenKey: "",
  _lastRecentKey: "",
  _posTimer: null,

  _startPositionTimer() {
    if (this._posTimer) clearInterval(this._posTimer);
    this._posTimer = setInterval(() => {
      if (this.activeTab !== "positions") return;
      const root = document.getElementById("view-cockpit");
      if (!root) return;
      const timeEls = root.querySelectorAll("#positions-tbody .pos-time[data-opened]");
      if (!timeEls || timeEls.length === 0) return;
      for (const el of timeEls) {
        if (el.dataset.opened) {
          el.textContent = formatStreamingDuration(el.dataset.opened);
        }
      }
    }, 1000);
  },

  _stopPositionTimer() {
    if (this._posTimer) {
      clearInterval(this._posTimer);
      this._posTimer = null;
    }
  },

  async enter() {
    const urlTf = window.getUrlParam?.("tf");
    if (urlTf && TF_LIST.includes(urlTf.toUpperCase())) {
      this.activeTf = urlTf.toUpperCase();
    }
    const urlSubtab = window.getUrlParam?.("tab") || window.getUrlParam?.("subtab");
    if (urlSubtab) {
      const mapped = COCKPIT_SUBTABS[urlSubtab.toLowerCase()];
      if (mapped) this.activeTab = mapped;
    }
    this._startPositionTimer();
    try {
      const [pos, spk, tradesRes] = await Promise.all([
        api("/api/positions"),
        api("/api/spk/latest"),
        api("/api/trades", { query: { limit: 20, offset: 0 } }),
      ]);
      setState({
        trades: {
          open: pos.open_trades || [],
          recent: tradesRes.recent || [],
          totalRecent: tradesRes.total ?? (tradesRes.recent || []).length,
          hasMoreRecent: tradesRes.has_more ?? false,
          loadingMore: false,
        },
        decision: spk.decision ?? state.decision,
      });
      this.patch();
    } catch (e) {
      handleErr(e, "Failed to load cockpit data");
    }
  },

  exit() {
    this._stopPositionTimer();
    if (this.chart) {
      this.chart.destroy();
      this.chart = null;
    }
  },

  render(root) {
    const urlTf = window.getUrlParam?.("tf");
    if (urlTf && TF_LIST.includes(urlTf.toUpperCase())) {
      this.activeTf = urlTf.toUpperCase();
    }
    const urlSubtab = window.getUrlParam?.("tab") || window.getUrlParam?.("subtab");
    if (urlSubtab) {
      const mapped = COCKPIT_SUBTABS[urlSubtab.toLowerCase()];
      if (mapped) this.activeTab = mapped;
    }

    const t = state.telemetry;
    const d = state.decision;
    const action = d?.action || "HOLD";
    const strength = d?.strength || "NONE";
    const score = d?.score ?? 0;
    const conf = d?.confidence ?? 0;
    const cycles = t?.cycles ?? 0;
    const openTrades = state.trades?.open || [];
    const juggler = t?.juggler || {};
    const bizdev = t?.bizdev || {};
    const isLocked = Boolean(juggler?.profit_locked);
    const dailyPnlPct = Number(juggler?.daily_pnl_pct || 0);
    const jBorderColor = isLocked ? "#10b981" : dailyPnlPct >= 0 ? "#10b981" : "#ef4444";

    root.innerHTML = `
      <div class="cockpit-layout">
        <!-- Left: Realtime Chart + Bottom Tabs -->
        <div class="cockpit-main">
          <!-- Realtime Chart Panel -->
          <div class="panel flush chart-panel">
            <div class="chart-header">
              <div class="tf-controls" id="chart-tf-btns" role="group" aria-label="Filter Periode Chart">
                ${TF_LIST.map((tf) => {
                  const vote = getTfVote(tf, d?.votes);
                  const activeClass = this.activeTf === tf ? "active" : "";
                  return `
                    <button class="tf-btn ${activeClass}" data-tf="${tf}" type="button" title="Timeframe ${tf}">
                      <span class="tf-scout-icon" data-tf-icon="${tf}">${renderTfIcon(vote)}</span>
                      <span class="tf-label">${tf}</span>
                    </button>
                  `;
                }).join("")}
              </div>
            </div>

            <div class="chart-canvas-wrap" id="chart-container"></div>
          </div>

          <!-- Tabs: Positions, Vote Trace, Recent Trades -->
          <div class="panel flush cockpit-tabs-panel">
            <div class="tab-headers">
              <button class="tab-btn ${this.activeTab === "positions" ? "active" : ""}" data-tab="positions" type="button">
                Positions (<span id="tab-cnt-positions">${openTrades.length}</span>)
              </button>
              <button class="tab-btn ${this.activeTab === "trace" ? "active" : ""}" data-tab="trace" type="button">
                Vote Trace (<span id="tab-cnt-trace">${d?.votes?.length ?? 0}</span>)
              </button>
              <button class="tab-btn ${this.activeTab === "trades" ? "active" : ""}" data-tab="trades" type="button">
                Recent Trades
              </button>
            </div>

            <div class="tab-pane ${this.activeTab === "positions" ? "active" : ""}" id="pane-positions">
              <div id="positions-table-wrap">${positionsBody()}</div>
            </div>

            <div class="tab-pane ${this.activeTab === "trace" ? "active" : ""}" id="pane-trace">
              <div id="trace-table-wrap">${traceBody(d)}</div>
            </div>

            <div class="tab-pane ${this.activeTab === "trades" ? "active" : ""}" id="pane-trades">
              <div id="trades-table-wrap">${tradesBody()}</div>
            </div>
          </div>
        </div>

        <!-- Right Column: SPK Consensus, Order Ticket, Risk -->
        <div class="cockpit-side">
          <!-- Consensus Card -->
          <div class="panel consensus-card">
            <div class="card-title">SPK Consensus</div>
            
            <div class="verdict-box">
              <span class="verdict-strength" id="c-strength">${esc(strength)} SIGNAL</span>
              <span class="verdict-action ${esc(action)}" id="c-action">${esc(action)}</span>
              <span class="verdict-sub mono" id="c-sub">${
                d?.tradable
                  ? `Lot ${fmtNum(d?.size, 2)} · SL ${fmtPrice(d?.sl)} · TP ${fmtPrice(d?.tp)}`
                  : d?.hard_veto
                    ? `Vetoed: ${esc(d?.veto_reason || "Risk guard")}`
                    : "No tradable edge"
              }</span>
            </div>

            <!-- Diverging Score Meter -->
            <div class="diverge-meter">
              <div class="diverge-fill" id="diverge-fill" style="width: 0; left: 50%;"></div>
            </div>

            <div class="consensus-stats">
              <div class="cs-item">
                <span class="k">Score</span>
                <span class="v mono" id="c-score">${fmtNum(score, 2)}</span>
              </div>
              <div class="cs-item">
                <span class="k">Confidence</span>
                <span class="v mono" id="c-conf">${fmtPct(conf)}</span>
              </div>
              <div class="cs-item">
                <span class="k">Cycles</span>
                <span class="v mono" id="c-cycles">${cycles}</span>
              </div>
            </div>
          </div>

          <!-- Order Ticket Card -->
          <div class="panel order-card">
            <div class="card-title">Trading Terminal</div>

            <div class="ticket-mode-tabs" id="ticket-mode-tabs">
              <button class="ticket-mode-btn ${this.ticketSide === "BUY" ? "active buy" : ""}" data-side="BUY" type="button">Buy</button>
              <button class="ticket-mode-btn ${this.ticketSide === "SELL" ? "active sell" : ""}" data-side="SELL" type="button">Sell</button>
              <button class="ticket-mode-btn ${this.ticketSide === "AUTO" ? "active auto" : ""}" data-side="AUTO" type="button">Auto</button>
            </div>

            <div class="lot-section">
              <div class="lot-input-wrap">
                <span class="dim" style="font-size: 11px; margin-right: 8px;">Lots:</span>
                <input class="lot-input mono" id="ticket-lot-input" type="number" step="0.01" min="0.01" max="10" value="${this.ticketLot}" />
              </div>

              <div class="lot-chips" id="ticket-lot-chips">
                <button class="lot-chip" data-lot="0.01" type="button">0.01</button>
                <button class="lot-chip" data-lot="0.05" type="button">0.05</button>
                <button class="lot-chip" data-lot="0.10" type="button">0.10</button>
                <button class="lot-chip" data-lot="0.50" type="button">0.50</button>
              </div>
            </div>

            <div class="ticket-actions">
              <button class="btn-execute ${this.ticketSide === "SELL" ? "sell" : "buy"}" id="ticket-execute-btn" type="button">
                Execute ${this.ticketSide}
              </button>
              <button class="btn-panic" id="ticket-panic-btn" type="button">
                Panic close all positions
              </button>
            </div>
          </div>

          <!-- The Juggler & BizDev Engine HUD -->
          <div class="panel juggler-hud-card" id="juggler-hud" style="border-left: 3px solid ${jBorderColor} !important;">
            <div class="card-title" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <span style="display: inline-flex; align-items: center; gap: 6px;">
                <span data-icon="target" data-size="13" style="color: var(--accent);"><svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg></span>
                Juggler & BizDev
              </span>
              <span class="mono" id="j-status-badge" style="font-size: 10px; padding: 2px 7px; border-radius: 4px; background: ${isLocked ? "var(--up)" : "var(--s2)"}; color: ${isLocked ? "#0b0e14" : "var(--accent)"}; font-weight: 700;">
                ${isLocked ? "TARGET LOCKED" : (juggler?.status || "ACTIVE")}
              </span>
            </div>

            <div style="margin: 6px 0 10px;">
              <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 4px;">
                <span class="dim">Daily Sprint Goal (+${juggler?.daily_target_pct || 35}%)</span>
                <span class="mono ${dailyPnlPct >= 0 ? "pos" : "neg"}" id="j-pnl-pct" style="font-weight: 700;">
                  ${dailyPnlPct >= 0 ? "+" : ""}${dailyPnlPct.toFixed(1)}%
                </span>
              </div>
              <div style="background: var(--s2); height: 5px; border-radius: 3px; overflow: hidden; position: relative;">
                <div id="j-progress-bar" style="background: var(--accent); width: ${Math.min(100, Math.max(0, juggler?.progress_pct || 0))}%; height: 100%; transition: width 0.3s ease;"></div>
              </div>
            </div>

            <div class="consensus-stats" style="grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 0;">
              <div class="cs-item" style="padding: 6px 8px;">
                <span class="k" style="font-size: 10px;">Bleed Clamp</span>
                <span class="v mono neg" id="j-clamp-val" style="font-size: 12.5px;" title="Max force cutloss per trade">-$${juggler?.hard_clamp_usd || "7.00"}</span>
              </div>
              <div class="cs-item" style="padding: 6px 8px;">
                <span class="k" style="font-size: 10px;">Est. Rebate</span>
                <span class="v mono pos" id="b-rebate-val" style="font-size: 12.5px;" title="Cashback from volume">+$${bizdev?.estimated_rebate_usd != null ? Number(bizdev.estimated_rebate_usd).toFixed(2) : "0.00"}</span>
              </div>
              <div class="cs-item" style="padding: 6px 8px;">
                <span class="k" style="font-size: 10px;">Volume</span>
                <span class="v mono" id="b-lots-val" style="font-size: 12.5px;">${bizdev?.total_lots_today != null ? Number(bizdev.total_lots_today).toFixed(2) : "0.00"} L</span>
              </div>
              <div class="cs-item" style="padding: 6px 8px;">
                <span class="k" style="font-size: 10px;">Friction</span>
                <span class="v mono ${(bizdev?.friction_ratio_pct || 0) > 15 ? "neg" : ""}" id="b-friction-val" style="font-size: 12.5px;">${bizdev?.friction_ratio_pct != null ? Number(bizdev.friction_ratio_pct).toFixed(1) + "%" : "0.0%"}</span>
              </div>
            </div>
          </div>

          <!-- Risk & Session Telemetry -->
          <div class="panel risk-card">
            <div class="card-title">Risk & Telemetry</div>

            <div class="risk-row">
              <span class="lbl">Hard Veto</span>
              <span class="val mono ${d?.hard_veto ? "neg" : "pos"}" id="r-veto">
                ${d?.hard_veto ? "ACTIVE" : "Off"}
              </span>
            </div>
            <div class="risk-row">
              <span class="lbl">Open Trades</span>
              <span class="val mono" id="r-trades">${openTrades.length} / 3</span>
            </div>
            <div class="risk-row">
              <span class="lbl">Bot Status</span>
              <span class="val ${t?.paused ? "neg" : "pos"}" id="r-status">
                ${t?.paused ? "PAUSED" : "RUNNING"}
              </span>
            </div>
            <div class="risk-row">
              <span class="lbl">Symbol</span>
              <span class="val mono" id="r-sym">${esc(t?.symbol || "XAUUSD")}</span>
            </div>
          </div>
        </div>
      </div>
    `;

    hydrateIcons(root);

    // Initialize Chart
    const container = root.querySelector("#chart-container");
    if (container) {
      if (this.chart) this.chart.destroy();
      this.chart = new PriceChart(container, {
        onCrosshairMove: (data) => {
          const livePriceEl = root.querySelector("#chart-live-price");
          if (livePriceEl && data) {
            livePriceEl.textContent = fmtPrice(data.close);
          } else if (livePriceEl && t?.bid != null) {
            livePriceEl.textContent = fmtPrice(t.bid);
          }
        },
      });
      this.chart.load(this.activeTf);
      this.chart.setPositions(openTrades);
    }

    // Timeframe selector
    root.querySelectorAll("#chart-tf-btns button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tf = btn.dataset.tf;
        if (!tf || tf === this.activeTf) return;
        this.activeTf = tf;
        window.updateUrlParams?.({ tf });
        root.querySelectorAll("#chart-tf-btns button").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        this.chart?.load(this.activeTf);
      });
    });

    // Tab buttons
    root.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.tab;
        if (!tab || tab === this.activeTab) return;
        this.activeTab = tab;
        window.updateUrlParams?.({ tab: tab, subtab: null });
        root.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
        root.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        const pane = root.querySelector(`#pane-${tab}`);
        pane?.classList.add("active");
        if (tab === "positions") {
          const wrap = root.querySelector("#positions-table-wrap");
          if (wrap) wrap.innerHTML = positionsBody();
        } else if (tab === "trace") {
          const wrap = root.querySelector("#trace-table-wrap");
          if (wrap) wrap.innerHTML = traceBody(state.decision);
        } else if (tab === "trades") {
          const wrap = root.querySelector("#trades-table-wrap");
          if (wrap) {
            wrap.innerHTML = tradesBody();
            const recent = state.trades?.recent || [];
            this._lastRecentKey = `${recent.length}:${recent[0]?.ticket || recent[0]?.id || ""}:${state.trades?.loadingMore || false}`;
          }
        }
        if (pane) hydrateIcons(pane);
      });
    });

    // Lot chips
    root.querySelectorAll("#ticket-lot-chips button").forEach((chip) => {
      chip.addEventListener("click", () => {
        const lot = parseFloat(chip.dataset.lot);
        if (lot) {
          this.ticketLot = lot;
          const input = root.querySelector("#ticket-lot-input");
          if (input) input.value = lot.toFixed(2);
        }
      });
    });

    // Lot input
    root.querySelector("#ticket-lot-input")?.addEventListener("change", (e) => {
      const val = parseFloat(e.target.value);
      if (val > 0) this.ticketLot = val;
    });

    // Ticket side mode buttons
    root.querySelectorAll("#ticket-mode-tabs button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const side = btn.dataset.side;
        this.ticketSide = side;
        root.querySelectorAll("#ticket-mode-tabs button").forEach((b) => {
          b.className = "ticket-mode-btn";
        });
        btn.classList.add("active");
        if (side === "BUY") btn.classList.add("buy");
        else if (side === "SELL") btn.classList.add("sell");
        else btn.classList.add("auto");

        const execBtn = root.querySelector("#ticket-execute-btn");
        if (execBtn) {
          execBtn.className = `btn-execute ${side === "SELL" ? "sell" : "buy"}`;
          execBtn.textContent = side === "AUTO" ? "Execute SPK Verdict" : `Execute ${side}`;
        }
      });
    });

    // Execute order
    root.querySelector("#ticket-execute-btn")?.addEventListener("click", async () => {
      let side = this.ticketSide;
      if (side === "AUTO") {
        side = state.decision?.action || "BUY";
        if (side === "HOLD") {
          toast({ title: "No signal", text: "SPK consensus is currently HOLD.", type: "warn" });
          return;
        }
      }
      try {
        const res = await manualOrder({
          side,
          size: this.ticketLot,
        });
        toast({
          title: res.ok ? `Order filled · #${res.ticket ?? "—"}` : "Order rejected",
          text: res.price ? `@ ${fmtPrice(res.price)}` : res.reason || "",
          type: res.ok ? "ok" : "err",
        });
        this.enter();
      } catch (err) {
        handleErr(err, "Manual order failed");
      }
    });

    // Panic close
    root.querySelector("#ticket-panic-btn")?.addEventListener("click", () => {
      openModal({
        title: "Emergency Panic Close?",
        body: `<p class="dim" style="font-size:12.5px;">This will immediately close <strong class="mono">${openTrades.length}</strong> open position(s) at current market prices.</p>`,
        actions: [
          { label: "Cancel" },
          {
            label: "Close all positions",
            kind: "danger",
            onClick: async () => {
              try {
                const res = await panic();
                toast({ title: `Closed ${res.closed} position(s)`, type: "ok" });
                this.enter();
              } catch (err) {
                handleErr(err, "Panic close failed");
              }
            },
          },
        ],
      });
    });

    this.updateDivergingMeter(score);
  },

  patch() {
    const root = document.getElementById("view");
    if (!root || !root.querySelector(".cockpit-layout")) return;

    const t = state.telemetry;
    const d = state.decision;
    const openTrades = state.trades?.open || [];
    const action = d?.action || "HOLD";
    const strength = d?.strength || "NONE";
    const score = d?.score ?? 0;
    const conf = d?.confidence ?? 0;

    // Update Chart with live tick
    if (this.chart && t?.bid != null) {
      this.chart.pushTick(t.bid, t.ask, t.ts);
      this.chart.setPositions(openTrades);
    }

    // Live price tag in chart header
    const livePriceEl = root.querySelector("#chart-live-price");
    if (livePriceEl && t?.bid != null) {
      livePriceEl.textContent = fmtPrice(t.bid);
    }

    // Update TF scout icons based on latest votes
    root.querySelectorAll("#chart-tf-btns .tf-btn").forEach((btn) => {
      const tf = btn.dataset.tf;
      if (!tf) return;
      const iconSpan = btn.querySelector(".tf-scout-icon");
      if (iconSpan) {
        const vote = getTfVote(tf, d?.votes);
        iconSpan.innerHTML = renderTfIcon(vote);
      }
    });

    // Verdict box
    const cAction = root.querySelector("#c-action");
    if (cAction) {
      cAction.className = `verdict-action ${action}`;
      cAction.textContent = action;
    }
    const cStrength = root.querySelector("#c-strength");
    if (cStrength) cStrength.textContent = `${strength} SIGNAL`;

    const cSub = root.querySelector("#c-sub");
    if (cSub) {
      cSub.textContent = d?.tradable
        ? `Lot ${fmtNum(d?.size, 2)} · SL ${fmtPrice(d?.sl)} · TP ${fmtPrice(d?.tp)}`
        : d?.hard_veto
          ? `Vetoed: ${esc(d?.veto_reason || "Risk guard")}`
          : "No tradable edge";
    }

    const cScore = root.querySelector("#c-score");
    if (cScore) cScore.textContent = fmtNum(score, 2);

    const cConf = root.querySelector("#c-conf");
    if (cConf) cConf.textContent = fmtPct(conf);

    const cCycles = root.querySelector("#c-cycles");
    if (cCycles) cCycles.textContent = t?.cycles ?? 0;

    this.updateDivergingMeter(score);

    // Tab counts & tables update (only when data changes to prevent DOM churn & hover flicker)
    const curCycles = d?.cycles ?? t?.cycles ?? 0;
    if (curCycles !== this._lastCycles) {
      this._lastCycles = curCycles;
      const cntTrace = root.querySelector("#tab-cnt-trace");
      if (cntTrace) cntTrace.textContent = d?.votes?.length ?? 0;
      const traceWrap = root.querySelector("#trace-table-wrap");
      if (traceWrap && this.activeTab === "trace") {
        traceWrap.innerHTML = traceBody(d);
        hydrateIcons(traceWrap);
      }
    }

    // Live streaming open positions table
    const cntPos = root.querySelector("#tab-cnt-positions");
    if (cntPos) cntPos.textContent = openTrades.length;

    const posWrap = root.querySelector("#positions-table-wrap");
    if (posWrap && this.activeTab === "positions") {
      const tbody = posWrap.querySelector("#positions-tbody");
      const existingRows = tbody ? Array.from(tbody.querySelectorAll("tr[data-ticket]")) : [];
      const existingTickets = existingRows.map((tr) => tr.dataset.ticket).join(",");
      const currentTickets = openTrades.map((p) => String(p.ticket)).join(",");

      if (tbody && existingTickets === currentTickets && openTrades.length > 0) {
        // Ultra-smooth zero-flicker in-place DOM streaming
        for (const p of openTrades) {
          const row = tbody.querySelector(`tr[data-ticket="${p.ticket}"]`);
          if (!row) continue;
          const current = p.price_current ?? p.last_price;
          const pnl = p.pnl ?? p.last_profit;
          const curEl = row.querySelector(".pos-current");
          if (curEl) curEl.textContent = fmtPrice(current);
          const pnlEl = row.querySelector(".pos-pnl");
          if (pnlEl) {
            pnlEl.textContent = fmtPnl(pnl);
            pnlEl.className = `pos-pnl pnl-cell mono ${pnlClass(pnl)}`;
          }
          const timeEl = row.querySelector(".pos-time");
          if (timeEl) {
            timeEl.dataset.opened = p.opened_at;
            timeEl.textContent = formatStreamingDuration(p.opened_at);
            timeEl.title = `Opened at ${formatWIB(p.opened_at)}`;
          }
        }

        // Live update basket summary bar if multi-entry active
        const bLayers = posWrap.querySelector("#basket-layers");
        const bVol = posWrap.querySelector("#basket-vol");
        const bEntry = posWrap.querySelector("#basket-entry");
        const bPnl = posWrap.querySelector("#basket-pnl");
        if (bLayers && bVol && bEntry && bPnl) {
          const totalVol = openTrades.reduce((acc, p) => acc + (Number(p.volume ?? p.size) || 0), 0);
          const totalPnl = openTrades.reduce((acc, p) => acc + (Number(p.pnl ?? p.last_profit) || 0), 0);
          const sumVal = openTrades.reduce((acc, p) => {
            const vol = Number(p.volume ?? p.size) || 0;
            const entry = Number(p.entry ?? p.open_price) || 0;
            return acc + vol * entry;
          }, 0);
          const avgEntry = totalVol > 0 ? sumVal / totalVol : 0;
          bLayers.textContent = `${openTrades.length} Layers`;
          bVol.textContent = `${totalVol.toFixed(2)} Lots`;
          bEntry.textContent = fmtPrice(avgEntry);
          bPnl.textContent = fmtPnl(totalPnl);
          bPnl.className = `mono ${totalPnl >= 0 ? "pos" : "neg"}`;
        }
      } else {
        const openKey = openTrades.map((p) => `${p.ticket}:${p.pnl}:${p.price_current}`).join("|");
        if (openKey !== this._lastOpenKey) {
          this._lastOpenKey = openKey;
          posWrap.innerHTML = positionsBody();
          hydrateIcons(posWrap);
        }
      }
    }

    // Live recent closed trades table (auto-refresh on initial load and trade completion)
    const tradesWrap = root.querySelector("#trades-table-wrap");
    if (tradesWrap && this.activeTab === "trades") {
      const recent = state.trades?.recent;
      if (recent) {
        const recentKey = `${recent.length}:${recent[0]?.ticket || recent[0]?.id || ""}:${state.trades?.loadingMore || false}`;
        const hasEmptyOrSkeleton = Boolean(tradesWrap.querySelector(".state") || tradesWrap.querySelector(".skeleton"));
        if (recentKey !== this._lastRecentKey || (hasEmptyOrSkeleton && recent.length > 0)) {
          this._lastRecentKey = recentKey;
          tradesWrap.innerHTML = tradesBody();
          hydrateIcons(tradesWrap);
        }
      }
    }

    // Risk card
    const rVeto = root.querySelector("#r-veto");
    if (rVeto) {
      rVeto.className = `val mono ${d?.hard_veto ? "neg" : "pos"}`;
      rVeto.textContent = d?.hard_veto ? "ACTIVE" : "Off";
    }
    const maxPositions = state.config?.max_open_positions || 3;
    const rTrades = root.querySelector("#r-trades");
    if (rTrades) rTrades.textContent = `${openTrades.length} / ${maxPositions}`;

    const rStatus = root.querySelector("#r-status");
    if (rStatus) {
      rStatus.className = `val ${t?.paused ? "neg" : "pos"}`;
      rStatus.textContent = t?.paused ? "PAUSED" : "RUNNING";
    }

    // Live update Juggler & BizDev HUD
    const jHud = root.querySelector("#juggler-hud");
    const jug = t?.juggler;
    const bdev = t?.bizdev;
    if (jHud && jug) {
      const isLck = Boolean(jug.profit_locked);
      const pnlPct = Number(jug.daily_pnl_pct || 0);
      jHud.style.borderLeft = (isLck ? "3px solid #10b981" : pnlPct >= 0 ? "3px solid #10b981" : "3px solid #ef4444") + " !important";

      const badge = root.querySelector("#j-status-badge");
      if (badge) {
        badge.textContent = isLck ? "TARGET LOCKED" : (jug.status || "ACTIVE");
        badge.style.background = isLck ? "var(--up)" : "var(--s2)";
        badge.style.color = isLck ? "#0b0e14" : "var(--accent)";
      }

      const pnlEl = root.querySelector("#j-pnl-pct");
      if (pnlEl) {
        pnlEl.textContent = (pnlPct >= 0 ? "+" : "") + pnlPct.toFixed(1) + "%";
        pnlEl.className = `mono ${pnlPct >= 0 ? "pos" : "neg"}`;
      }

      const bar = root.querySelector("#j-progress-bar");
      if (bar) bar.style.width = Math.min(100, Math.max(0, jug.progress_pct || 0)) + "%";

      const rebVal = root.querySelector("#b-rebate-val");
      if (rebVal && bdev?.estimated_rebate_usd != null) {
        rebVal.textContent = "+$" + Number(bdev.estimated_rebate_usd).toFixed(2);
      }

      const lotsVal = root.querySelector("#b-lots-val");
      if (lotsVal && bdev?.total_lots_today != null) {
        lotsVal.textContent = Number(bdev.total_lots_today).toFixed(2) + " L";
      }

      const fricVal = root.querySelector("#b-friction-val");
      if (fricVal && bdev?.friction_ratio_pct != null) {
        fricVal.textContent = Number(bdev.friction_ratio_pct).toFixed(1) + "%";
        fricVal.className = `v mono ${Number(bdev.friction_ratio_pct) > 15 ? "neg" : ""}`;
      }
    }

    hydrateIcons(root);
  },

  updateDivergingMeter(score) {
    const fill = document.getElementById("diverge-fill");
    if (!fill) return;
    const clamped = Math.max(-1, Math.min(1, score / 4.0));
    const widthPct = Math.abs(clamped) * 50;
    fill.style.width = `${widthPct}%`;
    fill.style.left = clamped >= 0 ? "50%" : `${50 - widthPct}%`;
    fill.style.background = score >= 0 ? "var(--up)" : "var(--down)";
  },
};

function positionsBody() {
  const open = state.trades?.open || [];
  if (!open.length) {
    return emptyState(
      "No open positions",
      "The desk is flat. New entries appear here when SPK fires.",
      "inbox",
    );
  }

  let basketHeader = "";
  if (open.length > 1) {
    const totalVol = open.reduce((acc, p) => acc + (Number(p.volume ?? p.size) || 0), 0);
    const totalPnl = open.reduce((acc, p) => acc + (Number(p.pnl ?? p.last_profit) || 0), 0);
    const buys = open.filter((p) => (p.direction || p.side) === "BUY");
    const sells = open.filter((p) => (p.direction || p.side) === "SELL");
    const isPingPong = buys.length > 0 && sells.length > 0;

    let modeTitle = `${open.length} Layers (${buys.length > 0 ? "BUY" : "SELL"})`;
    let avgEntryStr = "";
    if (isPingPong) {
      modeTitle = `Ping-Pong (${buys.length} BUY / ${sells.length} SELL)`;
      avgEntryStr = `<div><span class="dim">Strategy:</span> <strong class="mono" style="color:var(--accent);">Bi-Directional</strong></div>`;
    } else {
      const sumVal = open.reduce((acc, p) => {
        const vol = Number(p.volume ?? p.size) || 0;
        const entry = Number(p.entry ?? p.open_price) || 0;
        return acc + vol * entry;
      }, 0);
      const avgEntry = totalVol > 0 ? sumVal / totalVol : 0;
      avgEntryStr = `<div><span class="dim">Avg BE Entry:</span> <strong id="basket-entry" class="mono" style="color:var(--text);">${fmtPrice(avgEntry)}</strong></div>`;
    }
    const pnlColorClass = totalPnl >= 0 ? "pos" : "neg";

    basketHeader = `
      <div class="basket-summary-bar" style="display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.03); border:1px solid var(--line); border-radius:var(--radius-sm); padding:10px 14px; margin-bottom:12px; font-size:12px;">
        <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
          <div><span class="dim">Active Mode:</span> <strong id="basket-layers" class="mono" style="color:var(--text);">${modeTitle}</strong></div>
          <div><span class="dim">Total Vol:</span> <strong id="basket-vol" class="mono" style="color:var(--text);">${totalVol.toFixed(2)} Lots</strong></div>
          ${avgEntryStr}
          <div><span class="dim">Net PnL:</span> <strong id="basket-pnl" class="mono ${pnlColorClass}" style="font-weight:700;">${fmtPnl(totalPnl)}</strong></div>
        </div>
        <div>
          <button class="btn danger" style="padding:4px 10px; font-size:11px;" onclick="window.closeAllPositions()" type="button">
            Close All
          </button>
        </div>
      </div>
    `;
  }

  return `${basketHeader}<div class="table-scroll"><table class="data"><thead><tr>
    <th>Ticket</th><th>Side</th><th>Size</th><th>Entry</th><th>Current</th><th>PnL</th><th>Opened</th><th>Action</th>
  </tr></thead><tbody id="positions-tbody">${open
    .map((p) => {
      const dir = p.direction || p.side;
      const entry = p.entry ?? p.open_price;
      const current = p.price_current ?? p.last_price;
      const pnl = p.pnl ?? p.last_profit;
      const size = p.volume ?? p.size;
      const ticket = p.ticket;
      return `<tr data-ticket="${ticket}">
      <td class="mono font-semibold">${esc(ticket)}</td>
      <td><span class="tag ${voteClass(dir)}">${esc(voteLabel(dir))}</span></td>
      <td class="mono font-semibold">${size != null ? fmtNum(size, 2) : "—"}</td>
      <td class="mono">${fmtPrice(entry)}</td>
      <td class="pos-current mono">${fmtPrice(current)}</td>
      <td class="pos-pnl pnl-cell mono ${pnlClass(pnl)}">${fmtPnl(pnl)}</td>
      <td class="pos-time mono dim" data-opened="${p.opened_at}" title="Opened at ${formatWIB(p.opened_at)}">${formatStreamingDuration(p.opened_at)}</td>
      <td>
        <button class="btn danger" style="padding: 3px 8px; font-size: 11px;" onclick="window.closeSinglePosition(${ticket})" type="button">
          Close
        </button>
      </td>
    </tr>`;
    })
    .join("")}</tbody></table></div>`;
}

// Global position close action handler
window.closeSinglePosition = async function (ticket) {
  try {
    await api(`/api/control/close?ticket=${ticket}`, { method: "POST" });
    toast({ title: `Closed position #${ticket}`, type: "ok" });
    cockpit.enter();
  } catch (err) {
    handleErr(err, `Failed to close position #${ticket}`);
  }
};

window.closeAllPositions = function () {
  const open = state.trades?.open || [];
  openModal({
    title: "Close entire basket?",
    body: `<p class="dim" style="font-size:12.5px;">Closing <strong class="mono">${open.length}</strong> active open positions at current market prices.</p>`,
    actions: [
      { label: "Cancel" },
      {
        label: "Close Basket",
        kind: "danger",
        onClick: async () => {
          try {
            const r = await panic();
            toast({ title: `Closed ${r.closed} position(s) in basket`, type: "ok" });
            cockpit.enter();
          } catch (e) {
            handleErr(e, "Close basket failed");
          }
        },
      },
    ],
  });
};

function traceBody(d) {
  if (d?.hard_veto) {
    return `<div style="padding:10px 14px"><div class="veto-banner">${icon(
      "shield",
      15,
    )}<span>Hard veto active — ${esc(d.veto_reason || "Risk guard gate")}. Entry blocked regardless of consensus.</span></div></div>`;
  }
  const votes = (d?.votes || []).slice().sort((a, b) => {
    const sa = a.vote * a.confidence * (a.weight ?? 1);
    const sb = b.vote * b.confidence * (b.weight ?? 1);
    return Math.abs(sb) - Math.abs(sa);
  });
  if (!votes.length) {
    return emptyState(
      "No votes recorded yet",
      "Consensus trace updates once the decision cycle completes.",
      "cpu",
    );
  }
  return `<div class="trace">${votes
    .map((v) => {
      const contrib = v.vote * v.confidence * (v.weight ?? 1);
      return `<div class="trace-row" data-vote="${esc(voteLabel(v.vote))}">
        <div class="trace-bar"></div>
        <div class="trace-main">
          <span class="t-id">${esc(v.agent_id)}</span>
          <span class="t-div">${esc(v.division)}${v.timeframe ? " · " + esc(v.timeframe) : ""}</span>
        </div>
        <span class="trace-conf mono dim">${fmtPct(v.confidence)}</span>
        <span class="trace-contrib mono ${contrib > 0 ? "pos" : contrib < 0 ? "neg" : "muted"}">
          ${contrib > 0 ? "+" : ""}${fmtNum(contrib, 2)}
        </span>
      </div>`;
    })
    .join("")}</div>`;
}

function tradesBody() {
  const recent = state.trades?.recent;
  if (recent === undefined) {
    // Initial loading skeleton state while API is in-flight (Strict Borderless UI)
    return `<div class="table-scroll"><table class="data">
      <thead><tr>
        <th class="col-ticket">Ticket</th><th class="col-side">Side</th><th class="col-size">Size</th>
        <th class="col-entry">Entry</th><th class="col-exit">Exit</th><th class="col-pnl">PnL</th>
        <th class="col-dur">Duration</th><th class="col-time">Closed</th>
      </tr></thead>
      <tbody>
        ${[1, 2, 3, 4, 5].map(() => `<tr>
          <td colspan="8" style="padding: 10px 14px; border: none !important;"><div class="skeleton sk-line" style="margin:0; width: 100%; height: 18px; border: none !important;"></div></td>
        </tr>`).join("")}
      </tbody>
    </table></div>`;
  }
  if (!recent.length) {
    return emptyState("No recent trades", "Closed trade executions will be displayed here.", "inbox");
  }
  const total = state.trades?.totalRecent ?? recent.length;
  const hasMore = state.trades?.hasMoreRecent ?? (recent.length < total);
  const loading = state.trades?.loadingMore ?? false;

  return `<div class="table-scroll"><table class="data"><thead><tr>
    <th class="col-ticket">Ticket</th><th class="col-side">Side</th><th class="col-size">Size</th><th class="col-entry">Entry</th><th class="col-exit">Exit</th><th class="col-pnl">PnL</th><th class="col-dur">Duration</th><th class="col-time">Closed</th>
  </tr></thead><tbody>${recent
    .map((r) => {
      const side = r.side || r.direction;
      const entry = r.entry ?? r.entry_price ?? r.open_price;
      const exit = r.exit ?? r.exit_price ?? r.close_price;
      const pnl = r.pnl ?? r.profit;
      const dur = r.duration_s != null && r.duration_s !== "" ? `${Math.round(r.duration_s)}s` : "—";
      const ticket = r.ticket ?? r.mt5_ticket ?? (r.id ? `#${String(r.id).slice(0, 8)}` : "—");
      const closedTime = r.closed_at || r.opened_at;
      return `<tr>
        <td class="col-ticket mono font-semibold">${esc(ticket)}</td>
        <td class="col-side"><span class="tag ${voteClass(side)}">${esc(voteLabel(side))}</span></td>
        <td class="col-size mono font-semibold">${fmtNum(r.size ?? r.volume, 2)}</td>
        <td class="col-entry mono">${entry != null ? fmtPrice(entry) : "—"}</td>
        <td class="col-exit mono">${exit != null ? fmtPrice(exit) : "—"}</td>
        <td class="col-pnl pnl-cell mono ${pnlClass(pnl)}">${pnl != null ? fmtPnl(pnl) : "—"}</td>
        <td class="col-dur mono dim">${dur}</td>
        <td class="col-time mono dim">${relTime(closedTime)}</td>
      </tr>`;
    })
    .join("")}</tbody></table></div>
    <div class="table-footer-bar">
      <span class="counter-text">Showing <strong class="mono" style="color:var(--fg);">${recent.length}</strong> of <strong class="mono" style="color:var(--fg);">${total}</strong> trades</span>
      ${
        hasMore
          ? `<button class="btn-load-more" onclick="window.loadMoreTrades(this)" ${loading ? "disabled" : ""}>
              ${loading ? icon("loader", 13) : icon("arrowDown", 13)}
              <span>${loading ? "Loading..." : "Load More (+20)"}</span>
            </button>`
          : `<span class="dim mono" style="font-size:11px;">All closed trades loaded</span>`
      }
    </div>`;
}

window.loadMoreTrades = async function (btn) {
  if (state.trades?.loadingMore) return;
  const currentRecent = state.trades?.recent || [];
  const offset = currentRecent.length;

  setState({ trades: { ...(state.trades || {}), loadingMore: true } });
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `${icon("loader", 13)} <span class="spin">Loading...</span>`;
    hydrateIcons(btn);
  }

  try {
    const res = await api("/api/trades", { query: { limit: 20, offset } });
    const merged = currentRecent.concat(res.recent || []);
    const total = res.total ?? merged.length;
    const hasMore = res.has_more ?? (merged.length < total);

    setState({
      trades: {
        ...(state.trades || {}),
        recent: merged,
        totalRecent: total,
        hasMoreRecent: hasMore,
        loadingMore: false,
      },
    });

    const cockpitWrap = document.getElementById("trades-table-wrap");
    if (cockpitWrap) {
      cockpitWrap.innerHTML = tradesBody();
      hydrateIcons(cockpitWrap);
    }
    const controlWrap = document.getElementById("control-trades-wrap");
    if (controlWrap) {
      controlWrap.innerHTML = tradesBody();
      hydrateIcons(controlWrap);
    }
  } catch (e) {
    setState({ trades: { ...(state.trades || {}), loadingMore: false } });
    handleErr(e, "Failed to load more trades");
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `${icon("arrowDown", 13)} <span>Retry (+20)</span>`;
      hydrateIcons(btn);
    }
  }
};

/* =============================================================== agents */
export const agents = {
  title: "Agents",
  sub: "fleet status",
  icon: "cpu",
  _filter: "",
  _division: "all",
  _selectInstance: null,

  async enter() {
    const q = window.getUrlParam?.("q") || window.getUrlParam?.("search");
    if (q != null) this._filter = q.trim().toLowerCase();
    const div = window.getUrlParam?.("div") || window.getUrlParam?.("division");
    if (div != null) this._division = div.trim().toLowerCase();

    try {
      const r = await api("/api/agents");
      setState({ agentHealth: r.agents || [] });
      const root = document.getElementById("view");
      if (root) {
        if (root.querySelector(".agent-toolbar")) {
          this.updateGrid(root);
        } else {
          this.render(root);
        }
      }
    } catch (e) {
      handleErr(e, "Failed to load agents");
    }
  },

  exit() {
    if (this._selectInstance?.destroy) {
      this._selectInstance.destroy();
      this._selectInstance = null;
    }
  },

  updateGrid(root) {
    const rows = state.agentHealth || [];
    const filtered = rows.filter(
      (a) =>
        (this._division === "all" || a.division === this._division) &&
        (!this._filter || a.id.toLowerCase().includes(this._filter)),
    );
    const countEl = root.querySelector("#agent-count-val");
    if (countEl) countEl.textContent = `${filtered.length} / ${rows.length} agents`;

    const gridWrap = root.querySelector("#agent-grid-wrap");
    if (gridWrap) {
      const decision = state.decision;
      gridWrap.innerHTML = filtered.length
        ? `<div class="agent-grid">${filtered.map((a) => agentCard(a, decision)).join("")}</div>`
        : emptyState("No agents match", "Try clearing your search keyword or selecting All Divisions.", "cpu");
      hydrateIcons(gridWrap);
    }
  },

  render(root) {
    const rows = state.agentHealth;
    if (rows == null) {
      root.innerHTML = skeleton(6);
      return;
    }
    const divisions = [...new Set(rows.map((a) => a.division))].sort();

    root.innerHTML = `
      <div class="panel">
        <div class="agent-toolbar">
          <div class="grow field" style="margin: 0;">
            <input class="input" id="agent-search" placeholder="Filter agents by name or division…" value="${esc(this._filter)}" />
          </div>
          <div id="agent-div-select"></div>
          <span class="agent-count mono" id="agent-count-val">${rows.length} / ${rows.length} agents</span>
        </div>

        <div id="agent-grid-wrap"></div>
      </div>
    `;
    hydrateIcons(root);

    const search = root.querySelector("#agent-search");
    search?.addEventListener("input", (e) => {
      this._filter = e.target.value.trim().toLowerCase();
      window.updateUrlParams?.({ q: this._filter || null });
      this.updateGrid(root);
    });

    if (this._selectInstance?.destroy) {
      this._selectInstance.destroy();
      this._selectInstance = null;
    }

    import("./components.js").then(({ createSelect }) => {
      const mount = root.querySelector("#agent-div-select");
      if (mount) {
        mount.innerHTML = "";
        this._selectInstance = createSelect({
          ariaLabel: "Division",
          value: this._division,
          options: [{ value: "all", label: "All Divisions" }].concat(
            divisions.map((d) => ({ value: d, label: d })),
          ),
          onChange: (v) => {
            this._division = v;
            window.updateUrlParams?.({ div: v !== "all" ? v : null });
            this.updateGrid(root);
          },
        });
        mount.appendChild(this._selectInstance);
        hydrateIcons(mount);
      }
    });

    this.updateGrid(root);
  },

  patch() {
    const root = document.getElementById("view");
    if (!root) return;
    const grid = root.querySelector(".agent-grid");
    if (!grid) return;

    const decision = state.decision;
    if (!decision?.votes) return;

    for (const v of decision.votes) {
      const card = grid.querySelector(`.agent-card[data-agent-id="${esc(v.agent_id)}"]`);
      if (!card) continue;
      const vl = voteLabel(v.vote);
      if (card.dataset.vote !== vl) {
        card.dataset.vote = vl;
        const tag = card.querySelector(".ac-head .tag");
        if (tag) {
          tag.className = `tag ${voteClass(vl)}`;
          tag.textContent = vl;
        }
        const confWrap = card.querySelector(".conf");
        if (confWrap) confWrap.className = `conf ${voteClass(vl)}`;
      }
      const confVal = card.querySelector(".conf-val");
      if (confVal) confVal.textContent = fmtPct(v.confidence);
      const confFill = card.querySelector(".conf-fill");
      if (confFill) confFill.style.width = `${Math.round(v.confidence * 100)}%`;
    }
  },
};

function agentCard(a, decision) {
  const vote = decision?.votes?.find((v) => v.agent_id === a.id);
  const v = vote ? voteLabel(vote.vote) : a.last_vote != null ? voteLabel(a.last_vote) : "HOLD";
  const conf = vote?.confidence ?? a.last_confidence ?? 0;
  const weight = a.weight ?? a.default_weight ?? 1;
  const wr = a.winrate;

  return `<div class="agent-card" data-agent-id="${esc(a.id)}" data-vote="${esc(v)}">
    <div class="ac-head">
      <div>
        <div class="ac-id">${esc(a.id)}</div>
        <div class="ac-div">${esc(a.division)}${a.timeframe ? " · " + esc(a.timeframe) : ""}</div>
      </div>
      <span class="tag ${voteClass(v)}">${v}</span>
    </div>
    <div class="ac-rows">
      <div class="ac-row">
        <span class="k">Confidence</span>
        <span class="v mono conf-val">${fmtPct(conf)}</span>
      </div>
      <div class="conf ${voteClass(v)}">
        <span class="conf-track"><span class="conf-fill" style="width:${Math.round(conf * 100)}%"></span></span>
      </div>
      <div class="ac-row">
        <span class="k">Latency</span>
        <span class="v mono latency-val">${a.last_latency_ms != null ? fmtNum(a.last_latency_ms, 1) + " ms" : "—"}</span>
      </div>
      <div class="ac-row">
        <span class="k">Winrate</span>
        <span class="v mono winrate-val">${wr != null ? fmtPct(wr) : "—"}</span>
      </div>
    </div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-top:2px;">
      <span class="weight-chip">${icon("sliders", 11)} w ${fmtNum(weight, 2)}</span>
      ${
        a.error_count
          ? `<span class="tag loss">${a.error_count} err</span>`
          : `<span class="tag hold" style="background:var(--s2);color:var(--fg-dim);">healthy</span>`
      }
    </div>
  </div>`;
}

/* ============================================================ divisions */
export const divisions = {
  title: "Divisions",
  sub: "consensus distribution",
  icon: "radar",
  _lastCycles: -1,

  async enter() {
    try {
      const [div, spk] = await Promise.all([
        api("/api/agents/divisions"),
        api("/api/spk/latest"),
      ]);
      setState({ divisions: div.divisions || {}, decision: spk.decision ?? state.decision });
      const root = document.getElementById("view");
      if (root) this.render(root);
    } catch (e) {
      handleErr(e, "Failed to load divisions");
    }
  },

  render(root) {
    const divs = state.divisions;
    if (divs == null) {
      root.innerHTML = skeleton(4);
      return;
    }
    const d = state.decision;
    const votes = d?.votes || [];

    // 1. Separate Directional (Market Alpha) vs Governance (System)
    const alphaOrder = ["timeframe", "structure", "technical", "fundamental"];
    const alphaDivs = alphaOrder.filter((n) => divs[n]);
    // Include any other non-governance divisions if added dynamically
    Object.keys(divs).forEach((n) => {
      if (!alphaDivs.includes(n) && !["risk", "spk_core", "infra"].includes(n)) {
        alphaDivs.push(n);
      }
    });

    // 4-Axis Diamond Radar (Timeframe, Technical, Fundamental, Structure)
    const radarOrder = ["timeframe", "technical", "fundamental", "structure"].filter((n) => divs[n]);
    const radarLabels = radarOrder.map((n) => n.toUpperCase());
    const radarValues = radarOrder.map((n) => Math.abs(divs[n]?.score || 0));
    const radarMax = Math.max(1, ...radarValues);

    // Live Telemetry Extraction for Governance Cards
    // Risk
    const ddGuard = votes.find((v) => v.agent_id === "Risk-DrawdownGuard");
    const costMon = votes.find((v) => v.agent_id === "Risk-CostMonitor");
    const ddPct = ddGuard?.metadata?.daily_pnl_pct != null ? `${Number(ddGuard.metadata.daily_pnl_pct).toFixed(1)}%` : "0.0%";
    const spreadVal = costMon?.metadata?.spread_points != null ? `${Number(costMon.metadata.spread_points).toFixed(1)} pt` : "2.4 pt";
    const costOk = costMon?.metadata?.cost_ok ?? true;

    // SPK Core
    const chief = votes.find((v) => v.agent_id === "SPK-Chief");
    const resolver = votes.find((v) => v.agent_id === "SPK-Resolver");
    const conf = votes.find((v) => v.agent_id === "SPK-Confidence");
    const probVal = conf?.metadata?.probability != null ? `${(Number(conf.metadata.probability) * 100).toFixed(0)}%` : d?.confidence ? `${(Number(d.confidence) * 100).toFixed(0)}%` : "68%";
    const actionVal = d?.action ? d.action : "SCANNING";
    const conflictVal = resolver?.metadata?.resolution === "higher_timeframe_priority" ? "HTF Priority" : "Aligned";

    // Infra
    const conn = votes.find((v) => v.agent_id === "Infra-Connectivity");
    const res = votes.find((v) => v.agent_id === "Infra-Resource");
    const mt5Ok = conn?.metadata?.mt5 ?? true;
    const redisOk = conn?.metadata?.redis ?? true;
    const dbOk = conn?.metadata?.db ?? true;
    const errCount = res?.metadata?.error_count ?? 0;

    root.innerHTML = `
      <div class="divisions-grid">
        <div class="panel">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <div>
              <div class="card-title" style="margin-bottom: 2px;">Market Alpha Consensus</div>
              <div style="font-size: 11px; color: var(--fg-muted);">Directional bias & momentum voting · 23 agents</div>
            </div>
            <span class="badge" style="background: var(--s2); font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 999px; color: var(--fg-muted); letter-spacing: 0.5px;">ALPHA SIGNALS</span>
          </div>
          <div class="div-list">
            ${alphaDivs
              .map((n) => {
                const x = divs[n];
                const total = x.agents || 1;
                const bw = (x.buy / total) * 100;
                const sw = (x.sell / total) * 100;
                const nw = 100 - bw - sw;
                return `<div class="div-row">
                  <div class="div-name">
                    <strong>${esc(n)}</strong>
                    <span>${x.agents} agents</span>
                  </div>
                  <div class="div-meter">
                    <div class="div-track">
                      <div class="seg buy" style="width:${bw}%"></div>
                      <div class="seg sell" style="width:${sw}%"></div>
                      <div class="seg neutral" style="width:${nw}%"></div>
                    </div>
                    <div class="div-counts mono">
                      <span class="buy">${x.buy}</span>
                      <span class="sell">${x.sell}</span>
                      <span class="neutral">${x.neutral}</span>
                    </div>
                  </div>
                  <div class="div-score mono ${x.score > 0 ? "pos" : x.score < 0 ? "neg" : "muted"}">
                    ${x.score > 0 ? "+" : ""}${fmtNum(x.score, 2)}
                  </div>
                </div>`;
              })
              .join("")}
          </div>
        </div>

        <div class="panel divisions-radar-card">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <div class="card-title" style="margin-bottom: 2px;">Alpha Signal Radar</div>
              <div style="font-size: 11px; color: var(--fg-muted);">4-Axis diamond polar map</div>
            </div>
            <span class="badge" style="background: rgba(217, 164, 65, 0.15); font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 999px; color: var(--accent); letter-spacing: 0.5px;">DIAMOND RADAR</span>
          </div>
          <div class="radar-wrap"><canvas id="radar-chart"></canvas></div>
        </div>
      </div>

      <!-- System Governance & Vitals -->
      <div class="panel" style="margin-top: 14px; padding: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <div>
            <div class="card-title" style="margin-bottom: 2px;">System Governance & Platform Vitals</div>
            <div style="font-size: 11px; color: var(--fg-muted);">Real-time capital protection, arbitration engine, and platform health (14 agents)</div>
          </div>
          <span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; font-size: 10px; font-weight: 700; padding: 3px 10px; border-radius: 999px; letter-spacing: 0.5px;">100% OPERATIONAL</span>
        </div>

        <div class="governance-grid">
          <!-- Risk Card -->
          <div class="gov-card">
            <div class="gov-card-header">
              <div class="gov-title-group">
                <div class="gov-icon" data-icon="shield"></div>
                <div>
                  <div class="gov-title">Risk Guard</div>
                  <div class="gov-subtitle">6 Agents · Vote-Neutral</div>
                </div>
              </div>
              <div class="gov-pill guarded"><span class="gov-pill-dot"></span>PROTECTED</div>
            </div>
            <div class="gov-metrics-list">
              <div class="gov-metric-item">
                <span class="gov-metric-label">Daily Drawdown</span>
                <span class="gov-metric-value">${ddPct} / 3.0% max</span>
              </div>
              <div class="gov-metric-item">
                <span class="gov-metric-label">Spread & Cost</span>
                <span class="gov-metric-value">${spreadVal} (${costOk ? 'Cost OK' : 'High'})</span>
              </div>
              <div class="gov-metric-item">
                <span class="gov-metric-label">Position Sizing</span>
                <span class="gov-metric-value">ATR Vol-Adjusted</span>
              </div>
              <div class="gov-metric-item">
                <span class="gov-metric-label">Stagnant Salvage</span>
                <span class="gov-metric-value">120s Auto-Unlock</span>
              </div>
            </div>
            <div class="gov-reasoning">${esc(ddGuard?.reasoning || 'All risk guards active and monitoring')}</div>
          </div>

          <!-- SPK Core Card -->
          <div class="gov-card">
            <div class="gov-card-header">
              <div class="gov-title-group">
                <div class="gov-icon" data-icon="cpu"></div>
                <div>
                  <div class="gov-title">SPK Arbiter</div>
                  <div class="gov-subtitle">5 Agents · Meta-Observer</div>
                </div>
              </div>
              <div class="gov-pill calibrated"><span class="gov-pill-dot"></span>CALIBRATED</div>
            </div>
            <div class="gov-metrics-list">
              <div class="gov-metric-item">
                <span class="gov-metric-label">Decision State</span>
                <span class="gov-metric-value" style="color: ${d?.action === 'BUY' ? 'var(--up)' : d?.action === 'SELL' ? 'var(--down)' : 'var(--fg)'}">${actionVal}</span>
              </div>
              <div class="gov-metric-item">
                <span class="gov-metric-label">Win Probability</span>
                <span class="gov-metric-value">${probVal}</span>
              </div>
              <div class="gov-metric-item">
                <span class="gov-metric-label">HTF/LTF Conflict</span>
                <span class="gov-metric-value">${conflictVal}</span>
              </div>
              <div class="gov-metric-item">
                <span class="gov-metric-label">Hard Veto</span>
                <span class="gov-metric-value">${d?.hard_veto ? '<span style="color:var(--down)">BLOCKED</span>' : 'None (Clear)'}</span>
              </div>
            </div>
            <div class="gov-reasoning">${esc(chief?.reasoning || 'Aggregating cross-division signals')}</div>
          </div>

          <!-- Infra Card -->
          <div class="gov-card">
            <div class="gov-card-header">
              <div class="gov-title-group">
                <div class="gov-icon" data-icon="wifi"></div>
                <div>
                  <div class="gov-title">Infrastructure</div>
                  <div class="gov-subtitle">3 Agents · Health Telemetry</div>
                </div>
              </div>
              <div class="gov-pill optimal"><span class="gov-pill-dot"></span>OPTIMAL</div>
            </div>
            <div class="gov-metrics-list">
              <div class="gov-metric-item">
                <span class="gov-metric-label">MT5 Connector</span>
                <span class="gov-metric-value" style="color: ${mt5Ok ? 'var(--up)' : 'var(--down)'}">${mt5Ok ? 'Connected (:8001)' : 'Disconnected'}</span>
              </div>
              <div class="gov-metric-item">
                <span class="gov-metric-label">Redis Streams</span>
                <span class="gov-metric-value" style="color: ${redisOk ? 'var(--up)' : 'var(--down)'}">${redisOk ? 'Active (:6380)' : 'Error'}</span>
              </div>
              <div class="gov-metric-item">
                <span class="gov-metric-label">TimescaleDB</span>
                <span class="gov-metric-value" style="color: ${dbOk ? 'var(--up)' : 'var(--down)'}">${dbOk ? 'Healthy (:5433)' : 'Error'}</span>
              </div>
              <div class="gov-metric-item">
                <span class="gov-metric-label">Cycle Errors</span>
                <span class="gov-metric-value">${errCount} errors</span>
              </div>
            </div>
            <div class="gov-reasoning">${esc(conn?.reasoning || 'All services and message buses online')}</div>
          </div>
        </div>
      </div>

      <div class="panel flush" style="margin-top: 14px;">
        <div class="card-title" style="padding: 12px 14px 6px;">SPK Vote Trace</div>
        <div id="div-trace-wrap">${traceBody(d)}</div>
      </div>
    `;
    hydrateIcons(root);

    const radar = root.querySelector("#radar-chart");
    if (radar && radarLabels.length) {
      requestAnimationFrame(() => {
        drawRadar(radar, { labels: radarLabels, values: radarValues, max: radarMax });
      });
    }
  },

  patch() {
    const root = document.getElementById("view");
    if (!root || !root.querySelector(".div-list")) return;
    const d = state.decision;
    const curCycles = d?.cycles ?? -1;
    if (curCycles !== this._lastCycles) {
      this._lastCycles = curCycles;
      this.render(root);
    }
  },
};

/* ============================================================ portfolio */
export const portfolio = {
  title: "Portfolio",
  sub: "realized metrics & post-trade ledger",
  icon: "trending",

  _activePeriod: "all",
  _customSince: "",
  _customUntil: "",
  _expandedTicket: null,
  _page: 1,
  _pageSize: 15,
  _tradesTotal: 0,
  _tradesPageData: [],
  _showEquity: true,
  _showPnl: true,

  async enter() {
    await this.fetchData(this._activePeriod, this._customSince, this._customUntil);
  },

  async fetchData(period = "all", since = "", until = "") {
    this._activePeriod = period;
    this._customSince = since;
    this._customUntil = until;
    this._page = 1;
    this._expandedTicket = null;

    const root = document.getElementById("view");
    if (root) {
      const perfContent = root.querySelector("#perf-dynamic-content");
      if (perfContent) {
        perfContent.style.opacity = "0.45";
        perfContent.style.pointerEvents = "none";
      }
    }

    try {
      const query = { period };
      if (period === "custom") {
        if (since) query.since = `${since}T00:00:00+07:00`;
        if (until) query.until = `${until}T23:59:59+07:00`;
      }
      const r = await api("/api/performance", { query });
      this._tradesTotal = r.total_trades ?? (r.trades || []).length;
      this._tradesPageData = (r.trades || []).slice(0, this._pageSize);
      setState({ performance: r });
      if (root) this.render(root);
    } catch (e) {
      handleErr(e, "Failed to load portfolio data");
      if (root) {
        const perfContent = root.querySelector("#perf-dynamic-content");
        if (perfContent) {
          perfContent.style.opacity = "1";
          perfContent.style.pointerEvents = "auto";
        }
      }
    }
  },

  async fetchTradesPage(page) {
    if (page < 1) return;
    const totalPages = Math.max(1, Math.ceil(this._tradesTotal / this._pageSize));
    if (page > totalPages && totalPages > 0) return;

    const root = document.getElementById("view");
    const wrap = root?.querySelector("#portfolio-ledger-wrap");
    if (wrap) {
      wrap.style.opacity = "0.5";
      wrap.style.pointerEvents = "none";
    }

    try {
      const offset = (page - 1) * this._pageSize;
      const query = {
        limit: this._pageSize,
        offset,
      };
      const p = state.performance;
      if (p?.since) query.since = p.since;
      if (p?.until) query.until = p.until;

      const res = await api("/api/trades", { query });
      this._page = page;
      this._tradesPageData = res.recent || [];
      if (res.total != null) this._tradesTotal = res.total;
      this._expandedTicket = null;

      if (wrap) {
        wrap.innerHTML = renderLedgerTable(
          this._tradesPageData,
          this._expandedTicket,
          this._page,
          this._pageSize,
          this._tradesTotal
        );
        wrap.style.opacity = "1";
        wrap.style.pointerEvents = "auto";
        hydrateIcons(wrap);
        this.attachLedgerListeners(root);
      }
    } catch (err) {
      handleErr(err, `Failed to load page ${page} of trade ledger`);
      if (wrap) {
        wrap.style.opacity = "1";
        wrap.style.pointerEvents = "auto";
      }
    }
  },

  attachLedgerListeners(root) {
    if (!root) return;
    const wrap = root.querySelector("#portfolio-ledger-wrap");
    if (!wrap) return;

    wrap.querySelectorAll(".ledger-row").forEach((tr) => {
      tr.addEventListener("click", () => {
        const tId = tr.dataset.ticket;
        this._expandedTicket = this._expandedTicket === tId ? null : tId;
        wrap.innerHTML = renderLedgerTable(
          this._tradesPageData,
          this._expandedTicket,
          this._page,
          this._pageSize,
          this._tradesTotal
        );
        hydrateIcons(wrap);
        this.attachLedgerListeners(root);
      });
    });

    wrap.querySelectorAll(".page-btn[data-page]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const pNum = Number(btn.dataset.page);
        if (!isNaN(pNum) && pNum !== this._page) {
          this.fetchTradesPage(pNum);
        }
      });
    });
  },

  render(root) {
    const p = state.performance;
    if (p == null) {
      root.innerHTML = skeleton(4);
      return;
    }
    const s = p.stats || {};
    const wins = s.wins ?? 0;
    const losses = s.losses ?? 0;
    const total = s.total ?? wins + losses;
    const winrate = s.winrate ?? (total ? wins / total : 0);
    const totalPnl = s.total_pnl ?? 0;
    const pf = s.profit_factor ?? 0;
    const avgWin = total ? (s.gross_profit ?? 0) / Math.max(1, wins) : 0;
    const avgLoss = total ? (s.gross_loss ?? 0) / Math.max(1, losses) : 0;

    const activeP = this._activePeriod || "all";
    const isCustom = activeP === "custom";

    const presets = [
      { id: "today", label: "Hari Ini (WIB)" },
      { id: "yesterday", label: "Kemarin (WIB)" },
      { id: "week", label: "7 Hari (Week)" },
      { id: "month", label: "30 Hari (Month)" },
      { id: "all", label: "Semua (All)" },
      { id: "custom", label: "Kustom (WIB)" },
    ];

    const pillsHtml = presets
      .map(
        (pr) => `
        <button type="button" class="perf-pill ${activeP === pr.id ? "active" : ""}" data-period="${pr.id}">
          ${esc(pr.label)}
        </button>
      `,
      )
      .join("");

    const customHtml = `
      <div class="perf-custom-bar ${isCustom ? "visible" : ""}">
        <div class="perf-date-field">
          <span>Dari:</span>
          <input type="date" id="perf-since" value="${esc(this._customSince)}" class="input-date" />
        </div>
        <div class="perf-date-field">
          <span>Sampai:</span>
          <input type="date" id="perf-until" value="${esc(this._customUntil)}" class="input-date" />
        </div>
        <button type="button" class="btn primary btn-sm" id="perf-apply-btn">Terapkan</button>
      </div>
    `;

    root.innerHTML = `
      <div class="perf-header">
        <div class="perf-title-group">
          <span class="perf-main-title">Filter Periode</span>
          <span class="perf-sub-badge">${esc(activeP.toUpperCase())}</span>
        </div>
        <div class="perf-pills">
          ${pillsHtml}
        </div>
        ${customHtml}
      </div>

      <div id="perf-dynamic-content" style="transition: opacity 0.2s ease;">
        <div class="kv-grid">
          ${kv("Total PnL", fmtMoney(totalPnl), pnlClass(totalPnl))}
          ${kv("Win Rate", fmtPct(winrate), "")}
          ${kv("Profit Factor", fmtNum(pf, 2), pf >= 1 ? "pos" : "neg")}
          ${kv("Trades", String(total), "")}
          ${kv("Final Equity", fmtMoney(s.final_equity), "")}
          ${kv("Max Drawdown", fmtPct(s.max_drawdown ?? 0), "neg")}
        </div>

        <div class="panel" style="margin-top: 10px;">
          <div class="card-title" style="margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
            <span>Equity Growth & Trade PnL (${(p.equity_curve || []).length} Points)</span>
            <div class="chart-toggles">
              <button type="button" class="chart-toggle-btn ${this._showEquity ? "active" : ""}" data-toggle="equity" title="Toggle Equity Curve">
                <span class="chart-toggle-dot" style="background: var(--accent);"></span>
                <span>Equity Curve</span>
              </button>
              <button type="button" class="chart-toggle-btn ${this._showPnl ? "active" : ""}" data-toggle="pnl" title="Toggle Trade PnL Histogram">
                <span class="chart-toggle-dot" style="background: var(--up);"></span>
                <span>Trade PnL</span>
              </button>
            </div>
          </div>
          <div class="equity-wrap"><canvas id="equity-chart"></canvas></div>
        </div>

        <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-top: 10px;">
          <div class="panel" style="border-left: 3px solid #64748b !important;">
            <div class="card-title" style="margin-bottom: 10px;">Outcome Breakdown</div>
            <div class="dist">
              ${distRow("Wins", wins, total, "win")}
              ${distRow("Losses", losses, total, "loss")}
            </div>
          </div>

          <div class="panel" style="border-left: 3px solid ${Math.abs(avgLoss) > 7.5 ? "#ef4444" : "#10b981"} !important;">
            <div class="card-title" style="margin-bottom: 10px;">Trade Averages</div>
            <div style="display: flex; gap: 20px;">
              <div><span class="dim" style="font-size: 11px;">Average Win</span><div class="mono pos" style="font-size: 16px; font-weight: 700;">${fmtMoney(Math.abs(avgWin))}</div></div>
              <div><span class="dim" style="font-size: 11px;">Average Loss</span><div class="mono neg" style="font-size: 16px; font-weight: 700;">${fmtMoney(-Math.abs(avgLoss))}</div></div>
            </div>
            <div style="margin-top: 8px; font-size: 11px; display: flex; align-items: center; justify-content: space-between; background: var(--s2); padding: 4px 8px; border-radius: 4px;">
              <span class="dim">Juggler Clamp Limit</span>
              <span class="mono neg" style="font-weight: 600;">-$7.00 Max</span>
            </div>
          </div>

          <div class="panel" style="border-left: 3px solid ${(s.gross_profit ?? 0) >= (s.gross_loss ?? 0) ? "#10b981" : "#ef4444"} !important;">
            <div class="card-title" style="margin-bottom: 10px;">Gross Returns</div>
            <div style="display: flex; gap: 20px;">
              <div><span class="dim" style="font-size: 11px;">Gross Profit</span><div class="mono pos" style="font-size: 16px; font-weight: 700;">${fmtMoney(s.gross_profit ?? 0)}</div></div>
              <div><span class="dim" style="font-size: 11px;">Gross Loss</span><div class="mono neg" style="font-size: 16px; font-weight: 700;">${fmtMoney(s.gross_loss ?? 0)}</div></div>
            </div>
            <div style="margin-top: 8px; font-size: 11px; display: flex; align-items: center; justify-content: space-between; background: var(--s2); padding: 4px 8px; border-radius: 4px;">
              <span class="dim">Profit Factor</span>
              <span class="mono ${pf >= 1.5 ? "pos" : "neg"}" style="font-weight: 600;">${fmtNum(pf, 2)} (Target &ge; 1.50)</span>
            </div>
          </div>

          <div class="panel" style="border-left: 3px solid #d9a441 !important;">
            <div class="card-title" style="margin-bottom: 10px;">BizDev Economics</div>
            <div style="display: flex; gap: 20px;">
              <div><span class="dim" style="font-size: 11px;">Total Volume</span><div class="mono" style="font-size: 16px; font-weight: 700;">${fmtNum(s.total_lots ?? (total * 0.05), 2)} L</div></div>
              <div><span class="dim" style="font-size: 11px;">Est. Rebate</span><div class="mono pos" style="font-size: 16px; font-weight: 700;">+${fmtMoney((s.total_lots ?? (total * 0.05)) * 6.0)}</div></div>
            </div>
            <div style="margin-top: 8px; font-size: 11px; display: flex; align-items: center; justify-content: space-between; background: var(--s2); padding: 4px 8px; border-radius: 4px;">
              <span class="dim">IB Cashback Rate</span>
              <span class="mono pos" style="font-weight: 600;">$6.00 / lot</span>
            </div>
          </div>
        </div>

        <div class="panel flush" style="margin-top: 10px;">
          <div class="card-title" style="padding: 12px 14px 6px; display: flex; justify-content: space-between; align-items: center;">
            <span>Closed Trades & Retrospectives (${this._tradesTotal})</span>
            <span class="dim mono" style="font-size: 11px; font-weight: normal;">Click row to inspect adaptive policy</span>
          </div>
          <div id="portfolio-ledger-wrap" class="trade-ledger-wrap">
            ${renderLedgerTable(this._tradesPageData, this._expandedTicket, this._page, this._pageSize, this._tradesTotal)}
          </div>
        </div>
      </div>
    `;
    hydrateIcons(root);

    // Event listeners for period pills
    root.querySelectorAll(".perf-pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        const period = btn.dataset.period;
        if (period === "custom") {
          this._activePeriod = "custom";
          this.render(root);
        } else {
          this.fetchData(period);
        }
      });
    });

    const applyBtn = root.querySelector("#perf-apply-btn");
    if (applyBtn) {
      applyBtn.addEventListener("click", () => {
        const sinceVal = root.querySelector("#perf-since")?.value || "";
        const untilVal = root.querySelector("#perf-until")?.value || "";
        this.fetchData("custom", sinceVal, untilVal);
      });
    }

    // Chart metric toggles
    root.querySelectorAll(".chart-toggle-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const toggleType = btn.dataset.toggle;
        if (toggleType === "equity") {
          if (this._showEquity && !this._showPnl) return; // Prevent disabling both
          this._showEquity = !this._showEquity;
        } else if (toggleType === "pnl") {
          if (this._showPnl && !this._showEquity) return; // Prevent disabling both
          this._showPnl = !this._showPnl;
        }
        btn.classList.toggle("active");
        const canvas = root.querySelector("#equity-chart");
        if (canvas) {
          drawEquity(canvas, p.equity_curve || [], {
            showEquity: this._showEquity,
            showPnl: this._showPnl,
          });
        }
      });
    });

    this.attachLedgerListeners(root);

    const canvas = root.querySelector("#equity-chart");
    if (canvas) {
      drawEquity(canvas, p.equity_curve || [], {
        showEquity: this._showEquity,
        showPnl: this._showPnl,
      });
    }
  },
};

function renderPagination(page, pageSize, total) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (totalPages <= 1 && total <= pageSize) {
    if (total === 0) return "";
    return `
      <div class="ledger-pagination">
        <span class="pagination-info">Showing all <strong class="mono" style="color: var(--fg);">${total}</strong> trades</span>
        <div></div>
      </div>
    `;
  }

  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  // Generate page numbers with ellipsis
  const pages = [];
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i);
  } else {
    pages.push(1);
    if (page > 3) pages.push("...");
    const start = Math.max(2, page - 1);
    const end = Math.min(totalPages - 1, page + 1);
    for (let i = start; i <= end; i++) {
      if (!pages.includes(i)) pages.push(i);
    }
    if (page < totalPages - 2) pages.push("...");
    if (!pages.includes(totalPages)) pages.push(totalPages);
  }

  const prevDisabled = page <= 1 ? "disabled" : "";
  const nextDisabled = page >= totalPages ? "disabled" : "";

  return `
    <div class="ledger-pagination">
      <span class="pagination-info">Showing <strong class="mono" style="color: var(--fg);">${from}–${to}</strong> of <strong class="mono" style="color: var(--fg);">${total}</strong> trades</span>
      <div class="pagination-controls">
        <button type="button" class="page-btn" data-page="${page - 1}" ${prevDisabled} title="Previous page">
          ${icon("chevronLeft", 14)}
        </button>
        <div class="pagination-pages">
          ${pages
            .map((p) => {
              if (p === "...") {
                return `<span class="page-ellipsis">…</span>`;
              }
              const isActive = p === page;
              return `<button type="button" class="page-btn ${isActive ? "active" : ""}" data-page="${p}">${p}</button>`;
            })
            .join("")}
        </div>
        <button type="button" class="page-btn" data-page="${page + 1}" ${nextDisabled} title="Next page">
          ${icon("chevronRight", 14)}
        </button>
      </div>
    </div>
  `;
}

function renderLedgerTable(trades, expandedTicket, page = 1, pageSize = 15, total = 0) {
  if (!trades || !trades.length) {
    return emptyState("No closed trades in this period", "Try selecting another time range or 'Semua (All)'.", "inbox");
  }
  return `
    <table class="data">
      <thead>
        <tr>
          <th class="col-ticket">Ticket</th>
          <th class="col-side">Side</th>
          <th class="col-size">Size</th>
          <th class="col-entry">Entry</th>
          <th class="col-exit">Exit</th>
          <th class="col-pnl">PnL</th>
          <th class="col-dur">Duration</th>
          <th class="col-cause">Root Cause</th>
          <th class="col-time">Closed</th>
          <th class="col-expand" style="text-align: right; width: 32px;"></th>
        </tr>
      </thead>
      <tbody>
        ${trades
          .map((r) => {
            const ticket = r.ticket ?? r.mt5_ticket ?? (r.id ? `#${String(r.id).slice(0, 8)}` : "—");
            const isExpanded = String(expandedTicket) === String(ticket);
            const side = r.side || r.direction;
            const entry = r.entry ?? r.entry_price ?? r.open_price;
            const exit = r.exit ?? r.exit_price ?? r.close_price;
            const pnl = r.pnl ?? r.profit;
            const dur = r.duration_s != null && r.duration_s !== "" ? `${Math.round(r.duration_s)}s` : "—";
            const closedTime = r.closed_at || r.opened_at;
            const rootCause = r.root_cause ? r.root_cause.replace(/_/g, " ") : "signal confirmed";
            const policy = r.adaptive_policy || r.action || (pnl >= 0 ? "keep weight; reinforce setup" : "review entry timing; avoid immediate reversal stops");
            const score = r.lesson_score ?? r.spk_score ?? (pnl >= 0 ? 1.0 : -1.0);
            const regime = r.regime || "TRENDING";
            const session = r.session || "ACTIVE";

            return `
              <tr class="ledger-row ${isExpanded ? "expanded" : ""}" data-ticket="${esc(ticket)}">
                <td class="col-ticket mono font-semibold">${esc(ticket)}</td>
                <td class="col-side"><span class="tag ${voteClass(side)}">${esc(voteLabel(side))}</span></td>
                <td class="col-size mono font-semibold">${fmtNum(r.size ?? r.volume, 2)}</td>
                <td class="col-entry mono">${entry != null ? fmtPrice(entry) : "—"}</td>
                <td class="col-exit mono">${exit != null ? fmtPrice(exit) : "—"}</td>
                <td class="col-pnl pnl-cell mono ${pnlClass(pnl)}">${pnl != null ? fmtPnl(pnl) : "—"}</td>
                <td class="col-dur mono dim">${dur}</td>
                <td class="col-cause"><span class="tag ${pnlClass(pnl)}" style="font-size: 10px; padding: 2px 7px;">${esc(rootCause)}</span></td>
                <td class="col-time mono dim" title="${formatWIB(closedTime)}">
                  ${relTime(closedTime)}
                  <div style="font-size: 10px; color: var(--fg-muted); line-height: 1.2;">${formatWIB(closedTime, false)}</div>
                </td>
                <td class="col-expand" style="text-align: right; color: var(--fg-muted);">
                  <span style="display: inline-block; transition: transform 0.15s ease; transform: rotate(${isExpanded ? "180deg" : "0deg"});">
                    ${icon("chevron", 14)}
                  </span>
                </td>
              </tr>
              ${
                isExpanded
                  ? `
                <tr class="ledger-detail-row">
                  <td colspan="10">
                    <div class="ledger-detail-panel">
                      <div class="ledger-policy-box">
                        <span style="color: var(--accent); font-weight: 700; white-space: nowrap;">Adaptive Policy:</span>
                        <span>${esc(policy)}</span>
                      </div>
                      <div class="ledger-detail-grid">
                        <div><span class="dim" style="font-size: 11px;">Decision Score</span><div class="mono" style="font-size: 13px; font-weight: 600;">${fmtNum(score, 2)}</div></div>
                        <div><span class="dim" style="font-size: 11px;">Market Regime</span><div class="mono" style="font-size: 13px; font-weight: 600;">${esc(regime)}</div></div>
                        <div><span class="dim" style="font-size: 11px;">Trading Session</span><div class="mono" style="font-size: 13px; font-weight: 600;">${esc(session)}</div></div>
                        <div><span class="dim" style="font-size: 11px;">Closed (WIB)</span><div class="mono" style="font-size: 13px; font-weight: 600; color: var(--accent);">${formatWIB(closedTime)}</div></div>
                        <div><span class="dim" style="font-size: 11px;">Stop Loss</span><div class="mono" style="font-size: 13px;">${r.sl ? fmtPrice(r.sl) : "—"}</div></div>
                        <div><span class="dim" style="font-size: 11px;">Take Profit</span><div class="mono" style="font-size: 13px;">${r.tp ? fmtPrice(r.tp) : "—"}</div></div>
                        <div><span class="dim" style="font-size: 11px;">Captured Pips</span><div class="mono ${pnlClass(pnl)}" style="font-size: 13px; font-weight: 700;">${r.pips != null ? fmtNum(r.pips, 1) : "—"}</div></div>
                      </div>
                    </div>
                  </td>
                </tr>
              `
                  : ""
              }
            `;
          })
          .join("")}
      </tbody>
    </table>
    ${renderPagination(page, pageSize, total)}
  `;
}

function kv(label, value, cls) {
  return `<div class="kv"><span class="k">${esc(label)}</span><span class="v mono ${cls || ""}">${value}</span></div>`;
}
function distRow(label, n, total, kind) {
  const pct = total ? ((n / total) * 100).toFixed(1) : "0.0";
  const numCls = kind === "win" ? "pos" : kind === "loss" ? "neg" : "";
  return `<div class="dist-row"><span class="dim" style="font-weight: 500;">${esc(label)}</span><span class="dist-track"><span class="dist-fill ${kind}" style="width:${pct}%"></span></span><span class="dist-val mono"><span class="${numCls}" style="font-weight: 700;">${n}</span> <span style="font-size: 10px; color: var(--fg-muted);">(${pct}%)</span></span></div>`;
}



/* ============================================================== settings */
export const settings = {
  title: "Settings",
  sub: "operations, risk & system configuration",
  icon: "sliders",

  _activeTab: "ops", // "ops" | "risk" | "system"

  async enter() {
    try {
      const [st, cfg, tr] = await Promise.all([
        api("/api/status").catch(() => ({})),
        api("/api/control/config").catch(() => ({})),
        api("/api/trades", { query: { limit: 10, offset: 0 } }).catch(() => ({})),
      ]);
      setState({
        settingsConfig: cfg,
        statusSnapshot: st,
        trades: {
          ...(state.trades || {}),
          open: tr.open || state.trades?.open || [],
        },
      });
      const root = document.getElementById("view");
      if (root) this.render(root);
    } catch (e) {
      handleErr(e, "Failed to load settings data");
    }
  },

  render(root) {
    const t = state.telemetry;
    const paused = t?.paused ?? false;
    const cfg = state.settingsConfig || {};
    const risk = cfg.risk || {};
    const sys = cfg.system || {};
    const openTrades = state.trades?.open || [];
    const activeTab = this._activeTab || "ops";

    const tabsHtml = `
      <div class="settings-tabs">
        <button type="button" class="settings-tab-btn ${activeTab === "ops" ? "active" : ""}" data-tab="ops">
          ${icon("zap", 14)} <span>Operations & Emergency</span>
        </button>
        <button type="button" class="settings-tab-btn ${activeTab === "risk" ? "active" : ""}" data-tab="risk">
          ${icon("shield", 14)} <span>Risk & Parameters</span>
        </button>
        <button type="button" class="settings-tab-btn ${activeTab === "system" ? "active" : ""}" data-tab="system">
          ${icon("cpu", 14)} <span>System & Connectivity</span>
        </button>
      </div>
    `;

    let contentHtml = "";

    if (activeTab === "ops") {
      contentHtml = `
        <div class="control-grid">
          <div class="control-card">
            <div class="cc-head">${icon("pause", 16)}<h3>Runtime Loop</h3></div>
            <p class="cc-desc">Pause halts new entries while currently open positions remain actively managed with SL/TP trailing.</p>
            <div class="seg-ctrl" id="run-seg">
              <button data-run="run" aria-pressed="${!paused}">Running</button>
              <button data-run="pause" aria-pressed="${paused}">Paused</button>
            </div>
          </div>

          <div class="control-card">
            <div class="cc-head">${icon("zap", 16)}<h3>Emergency Killswitch</h3></div>
            <p class="cc-desc">Instantly close all open positions at market price and cancel pending orders.</p>
            <div class="warn-note">
              ${icon("alert", 15)}
              <span>Bypasses standard exit consensus and flattens the book immediately.</span>
            </div>
            <button class="btn danger" id="control-panic-btn" type="button" style="margin-top: 10px;">
              Panic Close All (${t?.open_trades ?? openTrades.length} open)
            </button>
          </div>

          <div class="control-card">
            <div class="cc-head">${icon("target", 16)}<h3>Manual Order Modal</h3></div>
            <p class="cc-desc">Launch the detailed market order dialog with custom lot size, stop loss, and take profit.</p>
            <button class="btn primary" id="control-manual-modal-btn" type="button" style="margin-top: 10px;">
              Open Order Dialog
            </button>
          </div>
        </div>

        <div class="panel flush" style="margin-top: 12px;">
          <div class="card-title" style="padding: 12px 14px 8px; display: flex; justify-content: space-between; align-items: center;">
            <span>Active Floating Positions (${openTrades.length})</span>
            <span class="dim mono" style="font-size: 11px;">Realtime MT5 book</span>
          </div>
          ${
            openTrades.length
              ? `<div class="table-scroll"><table class="data">
                  <thead>
                    <tr>
                      <th>Ticket</th>
                      <th>Side</th>
                      <th>Size</th>
                      <th>Entry</th>
                      <th>Current</th>
                      <th>Floating PnL</th>
                      <th>SL</th>
                      <th>TP</th>
                      <th style="text-align: right;">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${openTrades
                      .map((pos) => {
                        const side = pos.side || pos.direction || "BUY";
                        const entry = pos.entry ?? pos.open_price;
                        const cur = pos.price_current ?? pos.last_price ?? entry;
                        const pnl = pos.pnl ?? pos.last_profit ?? 0;
                        const ticket = pos.ticket ?? pos.mt5_ticket;
                        return `
                          <tr>
                            <td class="mono font-semibold">${esc(ticket)}</td>
                            <td><span class="tag ${voteClass(side)}">${esc(voteLabel(side))}</span></td>
                            <td class="mono font-semibold">${fmtNum(pos.volume ?? pos.size, 2)}</td>
                            <td class="mono">${entry != null ? fmtPrice(entry) : "—"}</td>
                            <td class="mono">${cur != null ? fmtPrice(cur) : "—"}</td>
                            <td class="pnl-cell mono ${pnlClass(pnl)}" style="font-weight: 700;">${fmtPnl(pnl)}</td>
                            <td class="mono dim">${pos.sl ? fmtPrice(pos.sl) : "—"}</td>
                            <td class="mono dim">${pos.tp ? fmtPrice(pos.tp) : "—"}</td>
                            <td style="text-align: right;">
                              <button type="button" class="btn danger btn-close-pos" data-ticket="${esc(ticket)}">Close</button>
                            </td>
                          </tr>
                        `;
                      })
                      .join("")}
                  </tbody>
                </table></div>`
              : emptyState("No active floating positions", "Engine is scanning market setups. Positions will appear here when filled.", "shield")
          }
        </div>
      `;
    } else if (activeTab === "risk") {
      contentHtml = `
        <div class="params-grid">
          <div class="param-card">
            <span class="label">Risk Per Trade</span>
            <span class="value mono" style="color: var(--accent);">${risk.risk_per_trade_pct != null ? `${risk.risk_per_trade_pct}%` : "0.5%"}</span>
            <span class="hint">Maximum equity risk percentage allocated per individual position.</span>
          </div>
          <div class="param-card">
            <span class="label">Max Daily Loss Limit</span>
            <span class="value mono" style="color: var(--down);">${risk.max_daily_loss_pct != null ? `${risk.max_daily_loss_pct}%` : "3.0%"}</span>
            <span class="hint">Daily circuit breaker. Trading halts for the day if drawdown hits this threshold.</span>
          </div>
          <div class="param-card">
            <span class="label">Max Weekly Loss Limit</span>
            <span class="value mono" style="color: var(--down);">${risk.max_weekly_loss_pct != null ? `${risk.max_weekly_loss_pct}%` : "6.0%"}</span>
            <span class="hint">Weekly capital protection ceiling. Halts bot until next Monday 00:00 UTC.</span>
          </div>
          <div class="param-card">
            <span class="label">Max Consecutive Losses</span>
            <span class="value mono">${risk.max_consecutive_losses != null ? `${risk.max_consecutive_losses} Trades` : "4 Trades"}</span>
            <span class="hint">Consecutive loss limit triggering mandatory 30-minute cooling period.</span>
          </div>
          <div class="param-card">
            <span class="label">Max Spread Filter Barrier</span>
            <span class="value mono">${risk.max_spread_points != null ? `${risk.max_spread_points} pts (4.5 pips)` : "45 pts"}</span>
            <span class="hint">SPK hard veto prevents new market entries when broker spread widens.</span>
          </div>
          <div class="param-card">
            <span class="label">Max Open Positions</span>
            <span class="value mono">${risk.max_open_positions != null ? `${risk.max_open_positions} Positions` : "10 Positions"}</span>
            <span class="hint">Maximum concurrent exposure ceiling across all division agents.</span>
          </div>
          <div class="param-card">
            <span class="label">Default Risk/Reward (R:R)</span>
            <span class="value mono" style="color: var(--up);">${risk.default_rr != null ? `1 : ${risk.default_rr}` : "1 : 1.5"}</span>
            <span class="hint">Minimum theoretical reward-to-risk ratio required to validate setup entry.</span>
          </div>
          <div class="param-card">
            <span class="label">ATR Stop Loss Multiplier</span>
            <span class="value mono">${risk.atr_sl_multiplier != null ? `${risk.atr_sl_multiplier}x ATR` : "1.2x ATR"}</span>
            <span class="hint">Dynamic volatility stop loss calibrated to M5/M15 Average True Range.</span>
          </div>
          <div class="param-card">
            <span class="label">Max Holding Duration</span>
            <span class="value mono">${risk.max_hold_seconds != null ? `${risk.max_hold_seconds}s (15 min)` : "900s"}</span>
            <span class="hint">Fast scalper time-stop. Stagnant positions are pruned automatically.</span>
          </div>
          <div class="param-card">
            <span class="label">Engine Cycle Interval</span>
            <span class="value mono">${risk.cycle_interval_ms != null ? `${risk.cycle_interval_ms}ms` : "1,000ms"}</span>
            <span class="hint">Frequency of full market evaluation and 37-agent consensus voting.</span>
          </div>
        </div>
      `;
    } else if (activeTab === "system") {
      contentHtml = `
        <div class="system-grid">
          <div class="system-card">
            <div class="head">${icon("trending", 16)} <span>MetaTrader 5 Bridge</span></div>
            <div class="body">
              <div class="kv"><span class="k">Server</span><span class="v mono">${esc(sys.server || "Exness-Real10")}</span></div>
              <div class="kv"><span class="k">Symbol</span><span class="v mono">${esc(sys.symbol || "XAUUSD")}</span></div>
              <div class="kv"><span class="k">Magic Number</span><span class="v mono">${esc(sys.magic || 990001)}</span></div>
              <div class="kv"><span class="k">Algo Trading</span><span class="v mono ${sys.algo_trading ? "pos" : "neg"}">${sys.algo_trading ? "ALLOWED / ACTIVE" : "STOPPED"}</span></div>
            </div>
          </div>

          <div class="system-card">
            <div class="head">${icon("cpu", 16)} <span>Multi-Agent Collective</span></div>
            <div class="body">
              <div class="kv"><span class="k">Registered Agents</span><span class="v mono">${esc(sys.agents_count || 37)} Sub-Agents</span></div>
              <div class="kv"><span class="k">Divisions</span><span class="v mono">7 Specialized Clusters</span></div>
              <div class="kv"><span class="k">Veto System</span><span class="v mono pos">Active (Hard & Soft)</span></div>
              <div class="kv"><span class="k">Consensus Loop</span><span class="v mono">Continuous (1.0s)</span></div>
            </div>
          </div>

          <div class="system-card">
            <div class="head">${icon("target", 16)} <span>Database & Storage</span></div>
            <div class="body">
              <div class="kv"><span class="k">Engine</span><span class="v mono">TimescaleDB / PostgreSQL 16</span></div>
              <div class="kv"><span class="k">Database Port</span><span class="v mono">${esc(sys.db_port || 5433)}</span></div>
              <div class="kv"><span class="k">Database Name</span><span class="v mono">${esc(sys.db_name || "goldscalper")}</span></div>
              <div class="kv"><span class="k">Hypertable Status</span><span class="v mono pos">Active & Compressing</span></div>
            </div>
          </div>

          <div class="system-card">
            <div class="head">${icon("zap", 16)} <span>Message Bus & Cache</span></div>
            <div class="body">
              <div class="kv"><span class="k">Engine</span><span class="v mono">Redis 7 (Alpine)</span></div>
              <div class="kv"><span class="k">Redis Port</span><span class="v mono">${esc(sys.redis_port || 6380)}</span></div>
              <div class="kv"><span class="k">Streams</span><span class="v mono">gs:ticks · gs:events</span></div>
              <div class="kv"><span class="k">Bus State</span><span class="v mono pos">Connected & Healthy</span></div>
            </div>
          </div>

          <div class="system-card">
            <div class="head">${icon("shield", 16)} <span>Notifications & Tunnel</span></div>
            <div class="body">
              <div class="kv"><span class="k">Telegram Alerts</span><span class="v mono ${sys.telegram_enabled ? "pos" : "dim"}">${sys.telegram_enabled ? "ENABLED" : "DISABLED"}</span></div>
              <div class="kv"><span class="k">Ingress Tunnel</span><span class="v mono pos">Cloudflare ZeroTrust</span></div>
              <div class="kv"><span class="k">Environment</span><span class="v mono">${esc(sys.environment || "production")}</span></div>
              <div class="kv"><span class="k">Host Architecture</span><span class="v mono">Linux x86_64</span></div>
            </div>
          </div>
        </div>
      `;
    }

    root.innerHTML = `
      ${tabsHtml}
      <div id="settings-tab-content">
        ${contentHtml}
      </div>
    `;
    hydrateIcons(root);

    // Event listeners
    root.querySelectorAll(".settings-tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._activeTab = btn.dataset.tab;
        this.render(root);
      });
    });

    if (activeTab === "ops") {
      root.querySelectorAll("#run-seg button").forEach((b) =>
        b.addEventListener("click", async () => {
          try {
            if (b.dataset.run === "pause") await import("./ws.js").then((m) => m.pause());
            else await import("./ws.js").then((m) => m.resume());
            toast({ title: b.dataset.run === "pause" ? "Bot paused" : "Bot resumed", type: "ok" });
          } catch (e) {
            handleErr(e, "Control action failed");
          }
        }),
      );

      root.querySelector("#control-panic-btn")?.addEventListener("click", () => {
        openModal({
          title: "Close all positions now?",
          body: `<p class="dim" style="font-size:12.5px;">Closing <strong class="mono">${t?.open_trades ?? openTrades.length}</strong> positions at market price.</p>`,
          actions: [
            { label: "Cancel" },
            {
              label: "Close all",
              kind: "danger",
              onClick: async () => {
                try {
                  const r = await panic();
                  toast({ title: `Closed ${r.closed} position(s)`, type: "ok" });
                  settings.enter();
                } catch (e) {
                  handleErr(e, "Panic close failed");
                }
              },
            },
          ],
        });
      });

      root.querySelector("#control-manual-modal-btn")?.addEventListener("click", () => openManualModal(t));

      root.querySelectorAll(".btn-close-pos").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const ticket = btn.dataset.ticket;
          try {
            const ws = await import("./ws.js");
            await ws.closePosition(ticket);
            toast({ title: `Closed position #${ticket}`, type: "ok" });
            settings.enter();
          } catch (e) {
            handleErr(e, `Failed to close position #${ticket}`);
          }
        });
      });
    }
  },
};

function openManualModal(t) {
  const price = t?.bid ?? t?.ask ?? 0;
  const body = document.createElement("div");
  body.style.display = "flex";
  body.style.flexDirection = "column";
  body.style.gap = "12px";
  body.innerHTML = `
    <div class="field">
      <label>Order Side</label>
      <div class="seg-ctrl" id="mo-side">
        <button data-side="BUY" aria-pressed="true">Buy</button>
        <button data-side="SELL" aria-pressed="false">Sell</button>
      </div>
    </div>
    <div class="field">
      <label>Volume (Lots)</label>
      <input class="input mono" id="mo-size" type="number" min="0.01" step="0.01" value="0.10" />
    </div>
    <div class="field">
      <label>Stop Loss (Price, optional)</label>
      <input class="input mono" id="mo-sl" type="number" step="0.01" placeholder="${price ? fmtPrice(price) : ""}" />
    </div>
    <div class="field">
      <label>Take Profit (Price, optional)</label>
      <input class="input mono" id="mo-tp" type="number" step="0.01" placeholder="${price ? fmtPrice(price) : ""}" />
    </div>
  `;

  let side = "BUY";
  body.querySelectorAll("#mo-side button").forEach((b) =>
    b.addEventListener("click", () => {
      side = b.dataset.side;
      body.querySelectorAll("#mo-side button").forEach((x) =>
        x.setAttribute("aria-pressed", String(x.dataset.side === side)),
      );
    }),
  );

  openModal({
    title: "Place Market Order",
    body,
    actions: [
      { label: "Cancel" },
      {
        label: "Send Order",
        kind: "primary",
        onClick: async () => {
          const size = parseFloat(body.querySelector("#mo-size").value);
          const sl = body.querySelector("#mo-sl").value;
          const tp = body.querySelector("#mo-tp").value;
          if (!size || size <= 0) {
            toast({ title: "Invalid volume", text: "Please enter a valid lot size.", type: "err" });
            return false;
          }
          try {
            const r = await manualOrder({
              side,
              size,
              sl: sl ? parseFloat(sl) : null,
              tp: tp ? parseFloat(tp) : null,
            });
            toast({
              title: r.ok ? `Order filled · #${r.ticket ?? "—"}` : "Order rejected",
              text: r.price ? `@ ${fmtPrice(r.price)}` : r.reason || "",
              type: r.ok ? "ok" : "err",
            });
            cockpit.enter();
          } catch (e) {
            handleErr(e, "Order submission failed");
          }
        },
      },
    ],
  });
}

function skeleton(n) {
  let s = '<div class="grid" style="grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px;">';
  for (let i = 0; i < n; i++) s += '<div class="panel"><div class="skeleton sk-block"></div></div>';
  return s + "</div>";
}

function handleErr(e, title) {
  if (e && e.code === 401) {
    import("./app.js").then((m) => m.requireToken?.());
    return;
  }
  toast({ title, text: e?.message || "Unknown error occurred", type: "err" });
}

export const performance = portfolio;
export const lessons = portfolio;
export const control = settings;

export const VIEWS = {
  cockpit,
  agents,
  divisions,
  portfolio,
  settings,
  performance: portfolio,
  lessons: portfolio,
  control: settings,
};
