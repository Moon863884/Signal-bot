#!/usr/bin/env python3
"""
signal_bot.py
- Giám sát BTCUSDT (Binance) và XAUUSD (Yahoo Finance)
- Kiểm tra EMA100/EMA200 và nến Engulfing trên nến vừa đóng
- Gửi cảnh báo qua Telegram khi thỏa điều kiện

Chạy: python3 signal_bot.py
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

SYMBOLS = ["BTCUSDT", "XAUUSD"]
TIMEFRAMES = ["5m", "15m", "1h"]
EMA_PERIODS = [100, 200]
POLL_INTERVAL = 30
KLINE_L_
