import MetaTrader5 as mt5

ok = mt5.initialize()
print("Initialize:", ok)
if ok:
    sel = mt5.symbol_select("XAUUSDm", True)
    print("Symbol select:", sel)
    tick = mt5.symbol_info_tick("XAUUSDm")
    print("Real Tick XAUUSDm:")
    print("  Bid:", getattr(tick, "bid", None))
    print("  Ask:", getattr(tick, "ask", None))
    print("  Time:", getattr(tick, "time", None))
    rates = mt5.copy_rates_from_pos("XAUUSDm", mt5.TIMEFRAME_M1, 0, 3)
    print("Real Candles M1:")
    for r in rates or []:
        print(" ", r)
    mt5.shutdown()
