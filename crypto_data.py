#!/usr/bin/env python3
"""
crypto_data.py  --  Hyperliquid OHLCV adapter for the AI-Trader backtest engine.

This is the ONE new piece the stocks->crypto move needs. The strategy logic in
strategy_templates.py / generated_strats.py is symbol-agnostic (df -> position),
so nothing there changes; we only swap the *data feed* from yfinance (US stocks,
market-hours daily bars) to Hyperliquid candles (crypto perps, 24/7 UTC daily bars)
and normalize the frame to the exact columns the engine expects.

Hyperliquid Info endpoint, `candleSnapshot` (no auth needed for market data).
Returns a DataFrame indexed by UTC date with capitalized OHLCV columns
(Open/High/Low/Close/Volume) -- identical shape to the yfinance frames, so
run_backtests.backtest()/metrics() consume it unchanged.

Research tool, not financial advice.
"""
import time
import numpy as np
import pandas as pd
import requests

HL_INFO = "https://api.hyperliquid.xyz/info"


def fetch_hl_candles(coin, interval="1d", lookback_days=2200, drop_partial=True):
    """Pull daily (or other interval) candles for `coin` from Hyperliquid.

    Pages backward-safe: HL returns a large chunk per call; we loop until the
    window stops advancing, dedup by open-time, and stitch. Returns a clean
    OHLCV DataFrame with a UTC DatetimeIndex, sorted ascending.
    """
    end = int(time.time() * 1000)
    start = end - int(lookback_days) * 24 * 3600 * 1000
    rows, seen, cur = [], set(), start
    while cur < end:
        body = {"type": "candleSnapshot",
                "req": {"coin": coin, "interval": interval,
                        "startTime": cur, "endTime": end}}
        r = requests.post(HL_INFO, json=body, timeout=30)
        r.raise_for_status()
        d = r.json()
        if not d:
            break
        fresh = [c for c in d if c["t"] not in seen]
        for c in fresh:
            seen.add(c["t"])
        rows.extend(fresh)
        last = max(c["t"] for c in d)
        if last <= cur:          # no progress -> done
            break
        cur = last + 1

    if not rows:
        raise RuntimeError(f"Hyperliquid returned no candles for {coin!r}")

    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = (df.rename(columns={"o": "Open", "h": "High", "l": "Low",
                             "c": "Close", "v": "Volume"})
            .set_index("t").sort_index())
    df = df[~df.index.duplicated(keep="last")]
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = df[col].astype(float)
    df.index = df.index.tz_convert(None)         # naive UTC, like the yfinance frames
    df = df[["Open", "High", "Low", "Close", "Volume"]]

    if drop_partial and len(df) > 1:
        # the final bar is today's still-forming candle -> drop it so signals
        # only ever read fully-closed bars (no look-ahead).
        df = df.iloc[:-1]
    return df


def cash_frame(index, price=1.0):
    """A synthetic flat 'cash'/stablecoin series aligned to `index` (0% return).
    Used as the 'safe' leg for the allocation strategy on crypto, where there is
    no bond fund -- risk-off means sit in USDC."""
    s = pd.Series(price, index=index, dtype=float)
    return pd.DataFrame({"Open": s, "High": s, "Low": s, "Close": s,
                         "Volume": 0.0}, index=index)


if __name__ == "__main__":          # smoke test
    for c in ["BTC", "ETH", "SOL"]:
        df = fetch_hl_candles(c)
        print(f"{c:4s} {len(df):5d} bars  {df.index[0].date()} -> {df.index[-1].date()}  "
              f"last close {df['Close'].iloc[-1]:,.2f}")
