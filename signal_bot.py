#!/usr/bin/env python3
"""
signal_bot.py
- Giám sát BTCUSDT (Binance) và XAU/USD (Alpha Vantage)
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

SYMBOLS = ["BTCUSDT", "XAUUSD"]
TIMEFRAMES = ["5m", "15m", "1h"]
EMA_PERIODS = [100, 200]
POLL_INTERVAL = 60  # giây giữa mỗi lần kiểm tra
PRICE_TOUCH_THRESHOLD_PCT = 0.0015  # ±0.15% chạm EMA
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
        ts_key = f"Time Series FX ({av_inte
