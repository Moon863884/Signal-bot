#!/usr/bin/env python3
"""
signal_bot.py
- Giám sát BTCUSDT (Binance) và XAUUSD (Yahoo Finance)
- Kiểm tra EMA100/EMA200 và nến Engulfing
- Gửi cảnh báo qua Telegram khi thỏa điều kiện

Chạy: python3 signal_bot.py
(Trên server: chạy trong screen/pm2/systemd/docker để luôn online)
"""

import time
import requests
import traceback
from typing import List
import pandas as pd
import yfinance as yf

# === CẤU HÌNH ===
TELEGRAM_TOKEN = "8230123317:AAEmQgEU2BVZy9xV1LvURMlN3bvmcZOzM4k"
TELEGRAM_CHAT_ID = "6146169999"

SYMBOLS = ["BTCUSDT", "XAUUSD"]  # BTC lấy Binance, Vàng lấy Yahoo
TIMEFRAMES = ["5m", "15m", "1h"]
EMA_PERIODS = [100, 200]
POLL_INTERVAL = 30
KLINE_LIMIT = 500
PRICE_TOUCH_THRESHOLD_PCT = 0.0015

BINANCE_REST = "https://api.binance.com/api/v3/klines"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# === HỖ TRỢ HÀM ===
def fetch_klines(symbol: str, interval: str, limit: int = 500) -> List:
    """
    Lấy dữ liệu nến.
    - BTCUSDT -> Binance
    - XAUUSD -> Yahoo Finance
    """
    if symbol == "BTCUSDT":
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = requests.get(BINANCE_REST, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    elif symbol == "XAUUSD":
        yf_symbol = "XAUUSD=X"
        interval_map = {
            "1m":"1m","5m":"5m","15m":"15m","30m":"30m",
            "1h":"60m","4h":"240m","1d":"1d"
        }
        yf_interval = interval_map.get(interval, "60m")
        data = yf.download(yf_symbol, period="5d", interval=yf_interval)
        klines = []
        for idx, row in data.iterrows():
            ts = int(idx.timestamp() * 1000)
            klines.append([ts, row["Open"], row["High"], row["Low"], row["Close"], row["Volume"], ts,0,0,0,0,0])
        return klines
    else:
        raise ValueError(f"No source for symbol {symbol}")

def klines_to_df(klines: List) -> pd.DataFrame:
    cols = ["open_time","open","high","low","close","volume","close_time",
            "qav","num_trades","taker_base","taker_quote","ignore"]
    df = pd.DataFrame(klines, columns=cols)
    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df[["open_time","open","high","low","close","volume"]]

def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def is_engulfing(prev_open, prev_close, curr_open, curr_close) -> (bool,str):
    def body_size(o,c): return abs(c - o)
    prev_body = body_size(prev_open, prev_close)
    curr_body = body_size(curr_open, curr_close)
    tiny = 1e-8
    if prev_close < prev_open and curr_close > curr_open and curr_body > tiny:
        if curr_open <= prev_close + 1e-12 and curr_close >= prev_open - 1e-12:
            return True, "bullish"
    if prev_close > prev_open and curr_close < curr_open and curr_body > tiny:
        if curr_open >= prev_close - 1e-12 and curr_close <= prev_open + 1e-12:
            return True, "bearish"
    return False, ""

def near_ema(price, ema_value, pct_threshold=PRICE_TOUCH_THRESHOLD_PCT) -> bool:
    if ema_value == 0: return False
    return abs(price - ema_value) / ema_value <= pct_threshold

def send_telegram(text: str):
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(TELEGRAM_API, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print("Telegram send error:", e)
        return False

# === LOGIC CHÍNH ===
def analyze_symbol_timeframe(symbol: str, timeframe: str):
    try:
        kl = fetch_klines(symbol, timeframe, KLINE_LIMIT)
        df = klines_to_df(kl)
        df["ema100"] = compute_ema(df["close"], 100)
        df["ema200"] = compute_ema(df["close"], 200)
        if len(df) < 3: return None
        last = df.iloc[-1]
        prev = df.iloc[-2]
        results = []
        for ema_period in EMA_PERIODS:
            ema_val = last[f"ema{ema_period}"]
            is_eng, direction = is_engulfing(prev["open"], prev["close"], last["open"], last["close"])
            if not is_eng: continue
            touched = last["low"] <= ema_val <= last["high"] or near_ema(last["close"], ema_val)
            if touched:
                msg = (
                    f"📡 <b>SIGNAL</b>\n"
                    f"Market: <b>{symbol}</b>\n"
                    f"TF: <b>{timeframe}</b>\n"
                    f"EMA: <b>{ema_period}</b>\n"
                    f"Type: <b>{direction.upper()} engulfing</b>\n"
                    f"Price: {last['close']:.8f}\n"
                    f"Candle Open/Close: {last['open']:.8f} / {last['close']:.8f}\n"
                    f"EMA{ema_period}: {ema_val:.8f}\n"
                    f"Time: {last['open_time']}\n"
                    f"Note: Engulfing và chạm EMA. Kiểm tra thêm trước khi hành động."
                )
                results.append({"symbol": symbol, "tf": timeframe, "ema": ema_period, "dir": direction, "msg": msg})
        return results
    except Exception as e:
        print(f"Error analyze {symbol} {timeframe}: {e}")
        traceback.print_exc()
        return None

def main_loop():
    print("Starting signal bot...")
    last_sent = {}
    cooldown = 60 * 10
    while True:
        try:
            for symbol in SYMBOLS:
                for tf in TIMEFRAMES:
                    res = analyze_symbol_timeframe(symbol, tf)
                    if res:
                        for r in res:
                            key = (r["symbol"], r["tf"], r["ema"], r["dir"])
                            now = time.time()
                            prev_ts = last_sent.get(key, 0)
                            if now - prev_ts < cooldown: continue
                            ok = send_telegram(r["msg"])
                            if ok:
                                print(f"Sent signal {key} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
                                last_sent[key] = now
                            else:
                                print("Failed to send telegram for", key)
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("Stopping by user")
            break
        except Exception as e:
            print("Main loop error:", e)
            traceback.print_exc()
            time.sleep(10)

if __name__ == "__main__":
    main_loop()
