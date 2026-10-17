"""Comprehensive 24-Hour Trading Performance Audit (Juggler & BizDev Strategy)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import asyncpg

WIB = timezone(timedelta(hours=7))

async def run_audit():
    db_url = os.environ.get(
        "DATABASE_URL", 
        "postgresql://goldscalper:change_me_in_env@timescaledb:5432/goldscalper"
    )
    # Also fallback to localhost/gs-timescaledb if running from host
    conn = None
    for target in [db_url, "postgresql://goldscalper:change_me_in_env@gs-timescaledb:5432/goldscalper", "postgresql://goldscalper:change_me_in_env@localhost:5432/goldscalper"]:
        try:
            conn = await asyncpg.connect(target)
            break
        except Exception:
            continue
            
    if not conn:
        print("ERROR: Could not connect to TimescaleDB!")
        return

    now_utc = datetime.now(timezone.utc)
    t_24h_ago = now_utc - timedelta(hours=24)
    # Start of today WIB (00:00 WIB today = 17:00 UTC yesterday)
    today_wib_start = datetime(now_utc.year, now_utc.month, now_utc.day, 0, 0, 0, tzinfo=WIB).astimezone(timezone.utc)

    # Fetch all closed trades in last 24h
    rows = await conn.fetch("""
        SELECT id, mt5_ticket, direction, size, entry_price, exit_price, pnl, pips,
               duration_s, status, opened_at, closed_at,
               COALESCE(metadata->>'root_cause', metadata->>'close_reason', 'NORMAL_EXIT') as root_cause,
               metadata
        FROM trades
        WHERE status = 'CLOSED' AND closed_at >= $1
        ORDER BY closed_at ASC
    """, t_24h_ago)

    # Also check currently open trades
    open_rows = await conn.fetch("""
        SELECT id, mt5_ticket, direction, size, entry_price, opened_at
        FROM trades
        WHERE status = 'OPEN'
        ORDER BY opened_at ASC
    """)

    await conn.close()

    total_closed = len(rows)
    print("=" * 60)
    print(f"  GOLDSCAALPER 24-HOUR PERFORMANCE AUDIT (JUGGLER & BIZDEV)")
    print(f"  Period: {t_24h_ago.astimezone(WIB).strftime('%Y-%m-%d %H:%M:%S')} WIB -> {now_utc.astimezone(WIB).strftime('%Y-%m-%d %H:%M:%S')} WIB")
    print("=" * 60)

    if not rows:
        print("No closed trades found in the last 24 hours.")
        print(f"Active open trades: {len(open_rows)}")
        return

    wins = [r for r in rows if (r['pnl'] or 0.0) > 0]
    losses = [r for r in rows if (r['pnl'] or 0.0) < 0]
    bes = [r for r in rows if (r['pnl'] or 0.0) == 0]

    net_pnl = sum(r['pnl'] or 0.0 for r in rows)
    gross_profit = sum(r['pnl'] for r in wins) if wins else 0.0
    gross_loss = abs(sum(r['pnl'] for r in losses)) if losses else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    winrate = (len(wins) / total_closed * 100) if total_closed else 0.0

    avg_win = (gross_profit / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    max_win = max((r['pnl'] for r in wins), default=0.0)
    max_loss = min((r['pnl'] for r in losses), default=0.0)

    durations = [r['duration_s'] or 0 for r in rows]
    avg_dur = sum(durations) / len(durations) if durations else 0
    durations_sorted = sorted(durations)
    median_dur = durations_sorted[len(durations_sorted) // 2] if durations_sorted else 0

    total_lots = sum(r['size'] or 0.0 for r in rows)
    est_rebate = total_lots * 6.0  # $6 per lot Exness BizDev rebate tier

    print("\n--- 1. METRIK EKSEKUSI UTAMA (OVERALL STATS) ---")
    print(f"Total Closed Trades : {total_closed}")
    print(f"Win / Loss / BE     : {len(wins)} Wins ({winrate:.1f}%) | {len(losses)} Losses | {len(bes)} BE")
    print(f"Net Realized PnL    : ${net_pnl:+,.2f} USD")
    print(f"Gross Profit        : +${gross_profit:,.2f} USD")
    print(f"Gross Loss          : -${gross_loss:,.2f} USD")
    print(f"Profit Factor (PF)  : {profit_factor:.2f}")
    print(f"Avg Win vs Avg Loss : +${avg_win:.2f} vs -${avg_loss:.2f} (Payoff Ratio: {payoff_ratio:.2f}x)")
    print(f"Max Win vs Max Loss : +${max_win:.2f} vs ${max_loss:.2f}")
    print(f"Duration            : Avg: {avg_dur:.1f}s (~{avg_dur/60:.1f}m) | Median: {median_dur:.1f}s")
    print(f"Total Volume Traded : {total_lots:.2f} Lots")
    print(f"Est. BizDev Rebate  : +${est_rebate:.2f} USD (Net Effective PnL: ${net_pnl + est_rebate:+,.2f} USD)")

    print("\n--- 2. AUDIT RISIKO & DYNAMIC BLEEDING CLAMP ---")
    # Check clamp adherence (target clamp: <= $7.50 / $8.00)
    clamp_adhered = [r for r in losses if abs(r['pnl']) <= 8.00]
    clamp_breached = [r for r in losses if abs(r['pnl']) > 8.00]
    print(f"Losses <= $8.00 (Clamped)  : {len(clamp_adhered)} ({len(clamp_adhered)/max(1, len(losses))*100:.1f}%)")
    print(f"Losses > $8.00 (Breached) : {len(clamp_breached)} ({len(clamp_breached)/max(1, len(losses))*100:.1f}%)")
    if clamp_breached:
        print("  Top Breached Losses:")
        for b in sorted(clamp_breached, key=lambda x: x['pnl'])[:5]:
            print(f"    Ticket {b['mt5_ticket']}: ${b['pnl']:.2f} | Size: {b['size']} | Dur: {b['duration_s']}s | Reason: {b['root_cause']}")

    # Loss brackets
    l_under_3 = sum(1 for r in losses if abs(r['pnl']) <= 3.0)
    l_3_to_7 = sum(1 for r in losses if 3.0 < abs(r['pnl']) <= 7.0)
    l_7_to_10 = sum(1 for r in losses if 7.0 < abs(r['pnl']) <= 10.0)
    l_over_10 = sum(1 for r in losses if abs(r['pnl']) > 10.0)
    print("  Distribusi Loss:")
    print(f"    Kecil (<= $3.00)    : {l_under_3} trades")
    print(f"    Sedang ($3.01 - $7) : {l_3_to_7} trades")
    print(f"    Clamp ($7.01 - $10) : {l_7_to_10} trades")
    print(f"    Besar (> $10.00)    : {l_over_10} trades")

    # Win brackets
    w_under_2 = sum(1 for r in wins if r['pnl'] <= 2.0)
    w_2_to_5 = sum(1 for r in wins if 2.0 < r['pnl'] <= 5.0)
    w_5_to_10 = sum(1 for r in wins if 5.0 < r['pnl'] <= 10.0)
    w_runner = sum(1 for r in wins if r['pnl'] > 10.0)
    print("  Distribusi Win:")
    print(f"    Micro-scalp (<= $2.00) : {w_under_2} trades")
    print(f"    Standard ($2.01 - $5) : {w_2_to_5} trades")
    print(f"    Solid ($5.01 - $10)   : {w_5_to_10} trades")
    print(f"    Runner (> $10.00)     : {w_runner} trades")

    print("\n--- 3. DIRECTIONAL BREAKDOWN (BUY VS SELL) ---")
    buys = [r for r in rows if r['direction'] == 'BUY']
    sells = [r for r in rows if r['direction'] == 'SELL']
    
    def summarize_dir(cohort, dir_name):
        if not cohort:
            print(f"  {dir_name}: 0 trades")
            return
        w = [r for r in cohort if (r['pnl'] or 0.0) > 0]
        l = [r for r in cohort if (r['pnl'] or 0.0) < 0]
        pnl_d = sum(r['pnl'] or 0.0 for r in cohort)
        pf_d = sum(r['pnl'] for r in w) / abs(sum(r['pnl'] for r in l)) if l else 99.0
        print(f"  {dir_name:4s} : {len(cohort)} trades | Winrate: {len(w)/len(cohort)*100:.1f}% ({len(w)}W / {len(l)}L) | Net PnL: ${pnl_d:+,.2f} | PF: {pf_d:.2f}")

    summarize_dir(buys, "BUY")
    summarize_dir(sells, "SELL")

    print("\n--- 4. TOP ROOT CAUSES / EXIT REASONS ---")
    rc_counts = {}
    rc_pnl = {}
    for r in rows:
        rc = r['root_cause'] or 'UNKNOWN'
        rc_counts[rc] = rc_counts.get(rc, 0) + 1
        rc_pnl[rc] = rc_pnl.get(rc, 0.0) + (r['pnl'] or 0.0)
    for rc, cnt in sorted(rc_counts.items(), key=lambda x: x[1], reverse=True)[:8]:
        print(f"  - {rc:35s} : {cnt:3d} trades | Net PnL: ${rc_pnl[rc]:+,.2f}")

    print("\n--- 5. DURATION BRACKETS ---")
    d_under_5s = sum(1 for d in durations if d < 5)
    d_5_to_30s = sum(1 for d in durations if 5 <= d < 30)
    d_30s_to_2m = sum(1 for d in durations if 30 <= d < 120)
    d_2m_to_10m = sum(1 for d in durations if 120 <= d < 600)
    d_over_10m = sum(1 for d in durations if d >= 600)
    print(f"  Flash (< 5s)      : {d_under_5s} ({d_under_5s/total_closed*100:.1f}%)")
    print(f"  Ultra-fast (5-30s): {d_5_to_30s} ({d_5_to_30s/total_closed*100:.1f}%)")
    print(f"  Scalp (30s - 2m)  : {d_30s_to_2m} ({d_30s_to_2m/total_closed*100:.1f}%)")
    print(f"  Swinglet (2 - 10m): {d_2m_to_10m} ({d_2m_to_10m/total_closed*100:.1f}%)")
    print(f"  Runner (> 10m)    : {d_over_10m} ({d_over_10m/total_closed*100:.1f}%)")

    print("\n--- 6. HOURLY PROGRESSION (TERAKHIR 12 JAM) ---")
    now_hour = now_utc.replace(minute=0, second=0, microsecond=0)
    for h in range(12, -1, -1):
        h_start = now_hour - timedelta(hours=h)
        h_end = h_start + timedelta(hours=1)
        h_trades = [r for r in rows if h_start <= r['closed_at'] < h_end]
        if not h_trades:
            continue
        h_pnl = sum(r['pnl'] or 0.0 for r in h_trades)
        h_wins = sum(1 for r in h_trades if (r['pnl'] or 0.0) > 0)
        h_time_wib = h_start.astimezone(WIB).strftime("%H:00 WIB")
        print(f"  {h_time_wib} : {len(h_trades):2d} trades ({h_wins:2d}W/{len(h_trades)-h_wins:2d}L) | PnL: ${h_pnl:+6.2f} USD")
    print("\n--- 7. SEBELUM VS SESUDAH FIX (CUT-OFF: 16:40 WIB HARI INI) ---")
    t_fix = datetime(2026, 10, 16, 16, 40, 0, tzinfo=WIB).astimezone(timezone.utc)
    before_fix = [r for r in rows if r['closed_at'] < t_fix]
    after_fix = [r for r in rows if r['closed_at'] >= t_fix]

    def print_cohort(cohort, title):
        if not cohort:
            print(f"  === {title}: 0 trades ===")
            return
        w = [r for r in cohort if (r['pnl'] or 0.0) > 0]
        l = [r for r in cohort if (r['pnl'] or 0.0) < 0]
        pnl = sum(r['pnl'] or 0.0 for r in cohort)
        gp = sum(r['pnl'] for r in w)
        gl = abs(sum(r['pnl'] for r in l))
        pf = (gp / gl) if gl > 0 else 99.0
        avg_w = gp / len(w) if w else 0.0
        avg_l = gl / len(l) if l else 0.0
        vol = sum(r['size'] or 0.0 for r in cohort)
        rebate = vol * 6.0
        print(f"  {title}:")
        print(f"    Trades          : {len(cohort)} ({len(w)}W / {len(l)}L | Winrate: {len(w)/len(cohort)*100:.1f}%)")
        print(f"    Realized PnL    : ${pnl:+,.2f} USD")
        print(f"    Profit Factor   : {pf:.2f}")
        print(f"    Avg Win / Loss  : +${avg_w:.2f} / -${avg_l:.2f} (Payoff: {avg_w/avg_l if avg_l else 0:.2f}x)")
        print(f"    Volume / Rebate : {vol:.2f} Lots (Rebate: +${rebate:.2f} USD)")
        print(f"    Net with Rebate : ${pnl + rebate:+,.2f} USD")
        print(f"    Max Loss        : ${min((r['pnl'] for r in l), default=0.0):.2f}")

    print_cohort(before_fix, "FASE 1: Sebelum Perbaikan Bridge & SPK Audit (22:45 kemarin - 16:40 WIB)")
    print_cohort(after_fix, "FASE 2: Sesudah Perbaikan Bridge & SPK Audit (16:40 - 22:45 WIB)")

    print("\n--- 8. DETAIL SAMPLE 15 TRADE TERAKHIR DI FASE 2 ---")
    for r in after_fix[-15:]:
        t_wib = r['closed_at'].astimezone(WIB).strftime("%H:%M:%S")
        print(f"    Ticket {r['mt5_ticket']}: {r['direction']:4s} {r['size']:.2f} lot | Entry: {r['entry_price']:.2f} -> Exit: {r['exit_price']:.2f} | Dur: {r['duration_s']:4d}s | PnL: ${r['pnl']:+6.2f} | Closed: {t_wib} WIB")

    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_audit())
