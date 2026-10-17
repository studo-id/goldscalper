import MetaTrader5 as mt5

if mt5.initialize():
    info = mt5.terminal_info()
    print("=== TERMINAL INFO ===")
    print("connected:", getattr(info, "connected", None))
    print("trade_allowed:", getattr(info, "trade_allowed", None))
    print("tradeapi_disabled:", getattr(info, "tradeapi_disabled", None))
    
    acc = mt5.account_info()
    print("=== ACCOUNT INFO ===")
    print("trade_expert:", getattr(acc, "trade_expert", None))
    print("trade_allowed (acc):", getattr(acc, "trade_allowed", None))
    print("trade_mode:", getattr(acc, "trade_mode", None))
    print("balance:", getattr(acc, "balance", None))
    print("login:", getattr(acc, "login", None))
    print("server:", getattr(acc, "server", None))
    mt5.shutdown()
else:
    print("Failed to initialize MT5")
