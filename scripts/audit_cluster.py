import asyncio
import asyncpg

async def check_cluster():
    conn = await asyncpg.connect('postgresql://goldscalper:change_me_in_env@gs-timescaledb:5432/goldscalper')
    rows = await conn.fetch('''
        SELECT mt5_ticket, direction, size, entry_price, exit_price, pnl, duration_s, opened_at, closed_at
        FROM trades 
        WHERE opened_at >= '2026-10-14 22:00:00+00' AND opened_at <= '2026-10-14 23:15:00+00'
        ORDER BY opened_at ASC
    ''')
    print(f"Cluster trades (22:00-23:15 UTC): {len(rows)}")
    net = sum(r['pnl'] for r in rows if r['pnl'] is not None)
    print(f"Net PnL in this window: ${net:.2f}")
    for r in rows:
        print(f"{r['opened_at'].strftime('%H:%M:%S')} -> {r['direction']} {r['size']} @ {r['entry_price']} | Exit: {r['exit_price']} | PnL: ${r['pnl']:.2f} | Dur: {r['duration_s']}s")
    await conn.close()

asyncio.run(check_cluster())
