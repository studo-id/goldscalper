import urllib.request
import json
import pandas as pd
import numpy as np

def fetch_data(interval, rng):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval={interval}&range={rng}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())["chart"]["result"][0]
        ts = pd.to_datetime(data["timestamp"], unit="s", utc=True).tz_convert("Asia/Jakarta")
        q = data["indicators"]["quote"][0]
        df = pd.DataFrame({
            "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"], "volume": q["volume"]
        }, index=ts).dropna()
        return df

def analyze_tf(name, df):
    df["ema9"] = df["close"].ewm(span=9).mean()
    df["ema21"] = df["close"].ewm(span=21).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]
    
    high_20 = df["high"].iloc[-20:].max()
    low_20 = df["low"].iloc[-20:].min()
    
    # recent structure
    trend = "BULLISH" if last["close"] > last["ema21"] and last["ema9"] > last["ema21"] else ("BEARISH" if last["close"] < last["ema21"] and last["ema9"] < last["ema21"] else "SIDEWAYS / COMPRESSION")
    
    print(f"=== TIMEFRAME: {name} ===")
    print(f"Time: {df.index[-1].strftime('%Y-%m-%d %H:%M WIB')} | Close: {last['close']:.2f}")
    print(f"Current Bar: Open={last['open']:.2f}, High={last['high']:.2f}, Low={last['low']:.2f}, Close={last['close']:.2f}, Vol={int(last['volume'])}")
    print(f"Prev Bar:    Open={prev['open']:.2f}, High={prev['high']:.2f}, Low={prev['low']:.2f}, Close={prev['close']:.2f}, Vol={int(prev['volume'])}")
    print(f"Prev2 Bar:   Open={prev2['open']:.2f}, High={prev2['high']:.2f}, Low={prev2['low']:.2f}, Close={prev2['close']:.2f}")
    print(f"EMAs: 9={last['ema9']:.2f} | 21={last['ema21']:.2f} | 50={last['ema50']:.2f}")
    print(f"RSI(14): {last['rsi']:.1f}")
    print(f"20-Bar Support: {low_20:.2f} | Resistance: {high_20:.2f} | Range: {high_20 - low_20:.2f} pts")
    print(f"Market Structure / Bias: {trend}")
    
    # Candlestick characteristics
    body = last['close'] - last['open']
    rng = last['high'] - last['low']
    upper_wick = last['high'] - max(last['close'], last['open'])
    lower_wick = min(last['close'], last['open']) - last['low']
    print(f"Candle shape: Body={body:+.2f}, UpperWick={upper_wick:.2f}, LowerWick={lower_wick:.2f}, TotalRange={rng:.2f}")
    print("-" * 50)

if __name__ == "__main__":
    df_1m = fetch_data("1m", "1d")
    analyze_tf("M1", df_1m)

    df_5m = fetch_data("5m", "1d")
    analyze_tf("M5", df_5m)

    df_15m = fetch_data("15m", "5d")
    analyze_tf("M15", df_15m)

    df_30m = fetch_data("30m", "5d")
    analyze_tf("M30", df_30m)

    df_1h = fetch_data("60m", "1mo")
    analyze_tf("H1", df_1h)

    df_4h = df_1h.resample("4h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()
    analyze_tf("H4", df_4h)

    df_1d = fetch_data("1d", "6mo")
    analyze_tf("D1", df_1d)
