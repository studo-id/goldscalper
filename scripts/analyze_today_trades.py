"""Analyze today's trades before and after the update."""
import asyncio
import os
import asyncpg
from datetime import datetime, timezone, timedelta

WIB = timezone(timedelta(hours=7))

async def main():
    db_url = os.environ.get("DATABASE_URL", "postgresql://goldscalper:change_me_in_env@timescaledb:5432/goldscalper")
    conn = await asyncpg.connect(db_url)
    
    # Deployment time of our updates: 2026-10-16 01:12:00 WIB (18:12:00 UTC 2026-10-15)
    t_deploy = datetime(2026, 10, 16, 1, 12, 0, tzinfo=WIB)
    today_start = datetime(2026, 10, 16, 0, 0, 0, tzinfo=WIB)
    
    rows = await conn.fetch("""
        SELECT mt5_ticket, direction, size, entry_price, exit_price, pnl, duration_s, 
               opened_at, closed_at, 
               COALESCE(metadata->>'root_cause', metadata->>'close_reason', 'NORMAL_EXIT') as root_cause
        FROM trades
        WHERE status = 'CLOSED' AND closed_at >= $1
        ORDER BY closed_at ASC
    """, today_start)
    
    before = [r for r in rows if r['closed_at'] < t_deploy]
    after = [r for r in rows if r['closed_at'] >= t_deploy]
    
    def summarize(cohort, name):
        if not cohort:
            print(f"=== {name}: 0 trades ===")
            return
        total = len(cohort)
        wins = [r for r in cohort if (r['pnl'] or 0) > 0]
        losses = [r for r in cohort if (r['pnl'] or 0) <= 0]
        pnl = sum(r['pnl'] or 0 for r in cohort)
        durations = [r['duration_s'] or 0 for r in cohort]
        avg_dur = sum(durations) / max(1, len(durations))
        min_dur = min(durations)
        max_dur = max(durations)
        
        # duration brackets
        d_under_5s = sum(1 for d in durations if d < 5)
        d_5_to_15s = sum(1 for d in durations if 5 <= d < 15)
        d_15_to_60s = sum(1 for d in durations if 15 <= d < 60)
        d_1_to_5m = sum(1 for d in durations if 60 <= d < 300)
        d_over_5m = sum(1 for d in durations if d >= 300)
        
        avg_win = sum(r['pnl'] for r in wins) / max(1, len(wins)) if wins else 0
        avg_loss = sum(r['pnl'] for r in losses) / max(1, len(losses)) if losses else 0
        
        print(f"\n==================================================")
        print(f"=== {name} ({total} trades) ===")
        print(f"==================================================")
        print(f"Winrate: {len(wins)}/{total} ({len(wins)/total*100:.1f}%)")
        print(f"Total PnL: ${pnl:.2f}")
        print(f"Avg Win: ${avg_win:.2f} | Avg Loss: ${avg_loss:.2f}")
        print(f"Durations: Min={min_dur:.1f}s, Avg={avg_dur:.1f}s, Max={max_dur:.1f}s")
        print(f"Duration breakdown:")
        print(f"  < 5s     : {d_under_5s} ({d_under_5s/total*100:.1f}%)")
        print(f"  5 - 15s  : {d_5_to_15s} ({d_5_to_15s/total*100:.1f}%)")
        print(f"  15 - 60s : {d_15_to_60s} ({d_15_to_60s/total*100:.1f}%)")
        print(f"  1 - 5m   : {d_1_to_5m} ({d_1_to_5m/total*100:.1f}%)")
        print(f"  > 5m     : {d_over_5m} ({d_over_5m/total*100:.1f}%)")
        
        # Root causes breakdown
        rc_counts = {}
        for r in cohort:
            rc = r['root_cause'] or 'UNKNOWN'
            rc_counts[rc] = rc_counts.get(rc, 0) + 1
        print(f"Root causes:")
        for rc, cnt in sorted(rc_counts.items(), key=lambda x: x[1], reverse=True)[:6]:
            print(f"  - {rc}: {cnt}")

    summarize(before, "SEBELUM UPDATE (00:00 - 01:12 WIB)")
    summarize(after, "SETELAH UPDATE (01:12 - 10:02 WIB)")
    
    # Detail on the last 15 trades
    print("\n=== DETAIL 15 TRADE TERAKHIR (SETELAH UPDATE) ===")
    for r in after[-15:]:
        t_wib = r['closed_at'].astimezone(WIB).strftime("%H:%M:%S")
        print(f"Ticket {r['mt5_ticket']}: {r['direction']:4s} {r['size']:.2f} lots | Dur: {r['duration_s']:5.1f}s | PnL: ${r['pnl']:+6.2f} | Closed: {t_wib} WIB | {r['root_cause']}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
