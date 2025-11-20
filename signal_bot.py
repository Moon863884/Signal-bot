#!/usr/bin/env python3
"""
signal_bot.py
- Giám sát BTCUSDT (Binance) và XAU/USD (Alpha Vantage)
- EMA100/EMA200 + Engulfing trên nến vừa đóng
- Gửi cảnh báo qua Telegram
"""

import time
import requests
import traceback
import pandas as pd

# === CẤU HÌNH ===
TELEGRAM_TOKEN = "8230123317:AAEmQgEU2BVZy9xV1LvURMlN3bvmcZOzM4k"
TELEGRAM_CHAT_ID = "6146169999"

SYMBOLS = ["BTCUSDT", "XAUUSD"]
TIMEFRAMES = ["5m", "15m", "1h"]
EMA_PERIODS = [100, 200]
POLL_INTERVAL = 60
PRICE_TOUCH_THRESHOLD_PCT = 0.0015
BINANCE_REST = "https://api.binance.com/api/v3/klines"
ALPHA_KEY = "4Z2TFS34K5D26HBR"

# Mapping timeframe -> Alpha Vantage interval
AV_INTERVAL_MAP = {"5m":"5min","15m":"15min","1h":"60min"}

# === HỖ TRỢ HÀM ===
def fetch_klines(symbol, interval, limit=500):
    if symbol == "BTCUSDT":
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = requests.get(BINANCE_REST, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    elif symbol == "XAUUSD":
        av_interval = AV_INTERVAL_MAP.get(interval,"15min")
        url = f"https://www.alphavantage.co/query?function=FX_INTRADAY&from_symbol=XAU&to_symbol=USD&interval={av_interval}&apikey={ALPHA_KEY}&outputsize=full"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        ts_key = f"Time Series FX ({av_interval})"
        if ts_key not in data:
            raise ValueError("Alpha Vantage no data, check API key or limit")
        candles = []
        count = 0
        for time_str, val in sorted(data[ts_key].items()):
            candles.append([pd.to_datetime(time_str), float(val['1. open']),
                            float(val['2. high']), float(val['3. low']),
                            float(val['4. close']), 0])
            count += 1
            if count >= limit:
                break
        return candles
    else:
        raise ValueError(f"No source for symbol {symbol}")

def klines_to_df(klines):
    if not klines: return pd.DataFrame()
    if isinstance(klines[0][0], pd.Timestamp):
        df = pd.DataFrame(klines, columns=["open_time","open","high","low","close","volume"])
    else:
        cols = ["open_time","open","high","low","close","volume","close_time",
                "qav","num_trades","taker_base","taker_quote","ignore"]
        df = pd.DataFrame(klines, columns=cols)
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df = df[["open_time","open","high","low","close","volume"]]
    return df

def compute_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def is_engulfing(prev_open, prev_close, curr_open, curr_close):
    def body_size(o,c): return abs(c-o)
    prev_body = body_size(prev_open, prev_close)
    curr_body = body_size(curr_open, curr_close)
    tiny = 1e-8
    if prev_close < prev_open and curr_close > curr_open and curr_body > tiny:
        if curr_open <= prev_close + 1e-12 and curr_close >= prev_open - 1e-12:
            return True,"bullish"
    if prev_close > prev_open and curr_close < curr_open and curr_body > tiny:
        if curr_open >= prev_close - 1e-12 and curr_close <= prev_open + 1e-12:
            return True,"bearish"
    return False,""

def near_ema(price, ema_value, pct_threshold=PRICE_TOUCH_THRESHOLD_PCT):
    if ema_value == 0: return False
    return abs(price - ema_value)/ema_value <= pct_threshold

def send_telegram(text):
    payload = {"chat_id": TELEGRAM_CHAT_ID,"text":text,"parse_mode":"HTML"}
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print("Telegram send error:", e)
        return False

# === LOGIC CHÍNH ===
def analyze_symbol_timeframe(symbol, timeframe):
    try:
        kl = fetch_klines(symbol, timeframe)
        df = klines_to_df(kl)
        if len(df)<4: return None
        df["ema100"] = compute_ema(df["close"],100)
        df["ema200"] = compute_ema(df["close"],200)
        closed = df.iloc[-2]  # nến vừa đóng
        prev = df.iloc[-3]
        results=[]
        for ema_period in EMA_PERIODS:
            ema_val = closed[f"ema{ema_period}"]
            is_eng,direction = is_engulfing(prev["open"],prev["close"],closed["open"],closed["close"])
            if not is_eng: continue
            touched = closed["low"] <= ema_val <= closed["high"] or near_ema(closed["close"],ema_val)
            if touched:
                msg = (
                    f"📡 <b>SIGNAL</b>\nMarket: <b>{symbol}</b>\nTF: <b>{timeframe}</b>\n"
                    f"EMA: <b>{ema_period}</b>\nType: <b>{direction.upper()} engulfing</b>\n"
                    f"Price: {closed['close']:.8f}\nCandle Open/Close: {closed['open']:.8f}/{closed['close']:.8f}\n"
                    f"EMA{ema_period}: {ema_val:.8f}\nTime: {closed['open_time']}\nNote: Engulfing và chạm EMA (nến vừa đóng)."
                )
                results.append({"symbol":symbol,"tf":timeframe,"ema":ema_period,"dir":direction,"msg":msg})
        return results
    except Exception as e:
        print(f"Error analyze {symbol} {timeframe}: {e}")
        traceback.print_exc()
        return None

def main_loop():
    print("Starting signal bot...")
    last_sent = {}
    cooldown = 60*10
    while True:
        try:
            for symbol in SYMBOLS:
                for tf in TIMEFRAMES:
                    res = analyze_symbol_timeframe(symbol, tf)
                    if res:
                        for r in res:
                            key=(r["symbol"],r["tf"],r["ema"],r["dir"])
                            now=time.time()
                            prev_ts=last_sent.get(key,0)
                            if now-prev_ts<cooldown: continue
                            ok = send_telegram(r["msg"])
                            if ok:
                                print(f"Sent signal {key} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
                                last_sent[key]=now
                            else:
                                print("Failed to send telegram for",key)
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("Stopping by user")
            break
        except Exception as e:
            print("Main loop error:", e)
            traceback.print_exc()
            time.sleep(10)

if __name__=="__main__":
    main_loop()
