#!/usr/bin/env python3
"""
signal_bot.py
- Giám sát BTCUSDT và XAUUSDT trên Binance
- Kiểm tra EMA100/EMA200 và nến Engulfing
- Gửi cảnh báo qua Telegram khi thỏa điều kiện

Chạy: python3 signal_bot.py
(Trên server: chạy trong screen/pm2/systemd/docker để luôn online)
"""

import time
import requests
import math
import traceback
from typing import List, Dict
import pandas as pd

# === CẤU HÌNH (bạn có thể chỉnh) ===
TELEGRAM_TOKEN = "8230123317:AAEmQgEU2BVZy9xV1LvURMlN3bvmcZOzM4k"
TELEGRAM_CHAT_ID = "6146169999"

SYMBOLS = ["BTCUSDT", "XAUUSDT"]         # BTC và Vàng token (Binance)
TIMEFRAMES = ["5m", "15m", "1h"]         # đa khung, nếu muốn chỉ 5m: ["5m"]
EMA_PERIODS = [100, 200]                 # EMA cần check
POLL_INTERVAL = 30                       # giây giữa mỗi lần lấy data (thích hợp 5m frame)
KLINE_LIMIT = 500                        # số nến lấy về (đủ để tính EMA200)
BINANCE_REST = "https://api.binance.com/api/v3/klines"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
PRICE_TOUCH_THRESHOLD_PCT = 0.0015       # ngưỡng chạm EMA nếu không chính xác bằng (0.15%)

# === HỖ TRỢ HÀM ===

import yfinance as yf

def fetch_klines(symbol: str, interval: str, limit: int = 500) -> list:
    """
    Lấy dữ liệu nến.
    - BTCUSDT -> Binance
    - XAUUSD -> yfinance (TradingView / Yahoo)
    """
    if symbol == "BTCUSDT":
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = requests.get(BINANCE_REST, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    elif symbol in ["XAUUSD","XAUUSDT"]:  # vàng
        # yfinance mapping: 'XAUUSD=X'
        yf_symbol = "XAUUSD=X"
        # mapping interval
        interval_map = {
            "1m":"1m", "5m":"5m", "15m":"15m", "30m":"30m",
            "1h":"60m", "2h":"120m", "4h":"240m", "1d":"1d"
        }
        yf_interval = interval_map.get(interval, "1h")
        data = yf.download(yf_symbol, period="5d", interval=yf_interval)
        # convert to Binance-like list of lists
        klines = []
        for idx, row in data.iterrows():
            ts = int(idx.timestamp() * 1000)
            o = row["Open"]
            h = row["High"]
            l = row["Low"]
            c = row["Close"]
            v = row["Volume"]
            klines.append([ts,o,h,l,c,v,ts,0,0,0,0,0])
        return klines
    else:
        raise ValueError(f"No source defined for symbol {symbol}")

def compute_ema(series: pd.Series, period: int) -> pd.Series:
    # pandas ewm (exponential weighted mean) — tương đương EMA
    return series.ewm(span=period, adjust=False).mean()

def is_engulfing(prev_open, prev_close, curr_open, curr_close) -> (bool,str):
    """
    Kiểm tra bullish/bearish engulfing dạng cổ điển:
    - Bullish engulfing: prev is bearish (close < open), curr is bullish (close > open),
      curr.open <= prev.close and curr.close >= prev.open
    - Bearish engulfing: prev bullish, curr bearish, curr.open >= prev.close and curr.close <= prev.open
    """
    # tránh trường hợp doji: require body sizes > small threshold
    def body_size(o,c):
        return abs(c - o)
    prev_body = body_size(prev_open, prev_close)
    curr_body = body_size(curr_open, curr_close)
    tiny = 1e-8

    if prev_close < prev_open and curr_close > curr_open and curr_body > tiny:
        # bullish candidate
        if curr_open <= prev_close + 1e-12 and curr_close >= prev_open - 1e-12:
            return True, "bullish"
    if prev_close > prev_open and curr_close < curr_open and curr_body > tiny:
        # bearish candidate
        if curr_open >= prev_close - 1e-12 and curr_close <= prev_open + 1e-12:
            return True, "bearish"
    return False, ""

def touches_ema(low, high, ema_value) -> bool:
    # xem nếu EMA nằm giữa low và high (tức nến chạm EMA)
    if low <= ema_value <= high:
        return True
    # hoặc nếu close gần EMA trong ngưỡng %
    return False

def near_ema(price, ema_value, pct_threshold=PRICE_TOUCH_THRESHOLD_PCT) -> bool:
    if ema_value == 0: return False
    return abs(price - ema_value) / ema_value <= pct_threshold

def send_telegram(text: str):
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(TELEGRAM_API, json=payload, timeout=10)
        # optional: check r.json() for ok
        return r.status_code == 200
    except Exception as e:
        print("Telegram send error:", e)
        return False

# === LOGIC CHÍNH ===

def analyze_symbol_timeframe(symbol: str, timeframe: str):
    try:
        kl = fetch_klines(symbol, timeframe, KLINE_LIMIT)
        df = klines_to_df(kl)
        # tính EMA
        df["ema100"] = compute_ema(df["close"], 100)
        df["ema200"] = compute_ema(df["close"], 200)
        # lấy nến gần nhất và nến trước đó
        if len(df) < 3:
            return None
        last = df.iloc[-1]
        prev = df.iloc[-2]

        results = []
        for ema_period in EMA_PERIODS:
            ema_col = f"ema{ema_period}"
            ema_val = last[ema_col]
            prev_ema = prev[ema_col]
            # kiểm tra engulfing giữa last và prev
            is_eng, direction = is_engulfing(prev["open"], prev["close"], last["open"], last["close"])
            if not is_eng:
                continue

            # kiểm tra nến chạm EMA: EMA nằm giữa low-high của nến hoặc close gần EMA
            touched = False
            # first, ema within latest candle range
            if last["low"] <= ema_val <= last["high"]:
                touched = True
            # or previous candle touched (khoảng giá rebound): xét prev
            if prev["low"] <= ema_val <= prev["high"]:
                touched = True
            # or close gần EMA (threshold)
            if near_ema(last["close"], ema_val):
                touched = True

            if touched:
                # build message
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
    last_sent = {}  # tránh spam: key=(symbol,tf,ema,dir) -> timestamp last sent
    cooldown = 60 * 10  # 10 phút cooldown cho mỗi signal loại đó
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
                            if now - prev_ts < cooldown:
                                # đã gửi gần đây -> skip
                                continue
                            ok = send_telegram(r["msg"])
                            if ok:
                                print(f"Sent signal {key} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
                                last_sent[key] = now
                            else:
                                print("Failed to send telegram for", key)
            # vòng poll delay
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("Stopping by user")
            break
        except Exception as e:
            print("Main loop error:", e)
            traceback.print_exc()
            # sleep ngắn rồi tiếp tục (retry)
            time.sleep(10)

if __name__ == "__main__":
    main_loop()

