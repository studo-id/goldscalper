import asyncio
import json
from datetime import datetime, timezone
import asyncpg

async def audit():
    conn = await asyncpg.connect("postgresql://goldscalper:change_me_in_env@gs-timescaledb:5432/goldscalper")
    
    rows = await conn.fetch("""
        SELECT id, mt5_ticket, direction, size, entry_price, exit_price, pnl, pips, 
               duration_s, status, opened_at, closed_at
        FROM trades 
        WHERE opened_at < '2026-10-15 04:00:00+00'
        ORDER BY opened_at ASC
    """)
    
    print(f"=== TOTAL TRADES AUDITED (before idle/fix): {len(rows)} ===")
    
    # Split into 3 phases:
    # Phase 1: Initial (Before formula fix: before 2026-10-14 18:05:00 UTC)
    # Phase 2: Sweet Spot (After formula fix, before Ganas: 18:05:00 to 18:46:00 UTC)
    # Phase 3: Post-Ganas (After 18:46:00 UTC to 00:00:00 UTC)
    
    t_formula_fix = datetime(2026, 10, 14, 18, 5, 0, tzinfo=timezone.utc)
    t_ganas = datetime(2026, 10, 14, 18, 46, 0, tzinfo=timezone.utc)
    
    phase1 = [r for r in rows if r['opened_at'] < t_formula_fix]
    phase2 = [r for r in rows if t_formula_fix <= r['opened_at'] < t_ganas]
    phase3 = [r for r in rows if r['opened_at'] >= t_ganas]
    
    def analyze_phase(name, trades):
        wins = [r for r in trades if r['pnl'] is not None and r['pnl'] > 0]
        losses = [r for r in trades if r['pnl'] is not None and r['pnl'] < 0]
        be = [r for r in trades if r['pnl'] is not None and r['pnl'] == 0]
        total_pnl = sum(r['pnl'] for r in trades if r['pnl'] is not None)
        gross_profit = sum(r['pnl'] for r in wins)
        gross_loss = abs(sum(r['pnl'] for r in losses))
        pf = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
        win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
        avg_win = (gross_profit / len(wins)) if wins else 0.0
        avg_loss = (gross_loss / len(losses)) if losses else 0.0
        max_loss = min((r['pnl'] for r in losses), default=0.0)
        max_win = max((r['pnl'] for r in wins), default=0.0)
        
        print(f"\n--- {name} ({len(trades)} trades) ---")
        print(f"Time Range: {trades[0]['opened_at'] if trades else 'N/A'} -> {trades[-1]['opened_at'] if trades else 'N/A'}")
        print(f"Net PnL: ${total_pnl:.2f} USD")
        print(f"Win Rate: {win_rate:.1f}% ({len(wins)} W / {len(losses)} L / {len(be)} BE)")
        print(f"Profit Factor: {pf:.2f}")
        print(f"Gross Profit: +${gross_profit:.2f} | Gross Loss: -${gross_loss:.2f}")
        print(f"Avg Win: +${avg_win:.2f} | Avg Loss: -${avg_loss:.2f}")
        print(f"Max Win: +${max_win:.2f} | Max Loss: ${max_loss:.2f}")
        
        # Directions
        buy_losses = len([r for r in losses if r['direction'] == 'BUY'])
        sell_losses = len([r for r in losses if r['direction'] == 'SELL'])
        print(f"Loss Directions: BUY: {buy_losses}, SELL: {sell_losses}")
        
        # Lots
        loss_lots = [r['size'] for r in losses if r['size']]
        avg_loss_lot = sum(loss_lots)/len(loss_lots) if loss_lots else 0.0
        max_loss_lot = max(loss_lots, default=0.0)
        print(f"Loss Lots: Avg {avg_loss_lot:.2f}, Max {max_loss_lot:.2f}")
        
        return trades
        
    analyze_phase("PHASE 1: Sebelum Perbaikan Formula", phase1)
    analyze_phase("PHASE 2: Pasca Perbaikan Formula (Golden Period)", phase2)
    p3 = analyze_phase("PHASE 3: Pasca Strategi GANAS (Multi-Entry/Rescue/Pyramid)", phase3)
    
    # Deep dive into Phase 3 biggest losses
    print("\n=== TOP 15 BIGGEST LOSSES IN PHASE 3 ===")
    p3_sorted_loss = sorted([r for r in p3 if r['pnl'] and r['pnl'] < 0], key=lambda x: x['pnl'])
    for r in p3_sorted_loss[:15]:
        print(f"Ticket {r['mt5_ticket']}: {r['direction']} {r['size']} lot @ {r['entry_price']} -> {r['exit_price']} | PnL: ${r['pnl']:.2f} | Dur: {r['duration_s']}s | Time: {r['opened_at']}")
        
    await conn.close()

asyncio.run(audit())
