#!/usr/bin/env python3
"""
signal_bot.py
- Giám sát BTCUSDT (Binance)
- EMA100/EMA200 + Engulfing trên nến vừa đóng
- Điều kiện: Giá trên/dưới EMA200 → hồi về EMA100/EMA200 → nến engulfing → gửi Telegram
"""

import time
import requests
import traceback
import pandas as pd

# === CẤU HÌNH ===
TELEGRAM_TOKEN = "8230123317:AAEmQgEU2BVZy9xV1LvURMlN3bvmcZOzM4k"
TELEGRAM_CHAT_ID = "6146169999"

SYMBOL = "BTCUSDT"
TIMEFRAMES = ["5m", "15m", "1h"]
EMA_PERIODS = [100, 200]
POLL_INTERVAL = 60  # giây
PRICE_TOUCH_THRESHOLD_PCT = 0.0015  # ±0.15%
BINANCE_REST = "https://api.binance.com/api/v3/klines"

# === HỖ TRỢ HÀM ===

def fetch_klines(symbol, interval, limit=500):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(BINANCE_REST, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def klines_to_df(klines):
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
    tiny = 1e-8
    prev_body = body_size(prev_open, prev_close)
    curr_body = body_size(curr_open, curr_close)
    if prev_close < prev_open and curr_close > curr_open and curr_body > tiny:
        if curr_open <= prev_close + 1e-12 and curr_close >= prev_open - 1e-12:
            return True,"bullish"
    if prev_close > prev_open and curr_close < curr_open and curr_body > tiny:
        if curr_open >= prev_close - 1e-12 and curr_close <= prev_open + 1e-12:
            return True,"bearish"
    retu
