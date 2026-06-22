#!/usr/bin/env python3
"""
catalog_strats.py  —  8 of the 12 narrowed strategies, written to drop straight
into your 04_backtest.py. Each returns a POSITION SERIES (1=long, 0=flat,
-1=short) aligned to df.index, so your existing backtest()/stats() run them
unchanged.

USE:
  In 04_backtest.py, right after `STRATS = {"rsi": ..., "sma": ...}`, add:

      import catalog_strats
      STRATS.update(catalog_strats.STRATS)

  Then:
      python 04_backtest.py SPY s01
      python 04_backtest.py SPY s02      ... etc (keys: s01 s02 s03 s04 s06 s07 s08 s10)

THE OTHER 4 (S05 gap, S09 overnight, S11 allocation, S12 pairs) do NOT fit a
single-ticker close-to-close position series — gap/overnight need intraday
open->close accrual, and allocation/pairs need two tickers. Run those with
extras_backtest.py.
"""
import numpy as np, pandas as pd

def _rsi(close, n):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1 + up/dn)

def _lsma(close, n):                      # least-squares MA = OLS endpoint
    x = np.arange(n)
    def f(y):
        b, a = np.polyfit(x, y, 1)
        return a + b*(n-1)
    return close.rolling(n).apply(f, raw=True)


# ---- S01  RSI(10) mean-reversion + SMA200 filter (long, RSI>40 or 10-bar stop)
def s01_rsi_mr(df):
    r = _rsi(df["Close"], 10)
    above = df["Close"] > df["Close"].rolling(200).mean()
    entry = (above & (r < 30)).fillna(False).values
    ex    = (r > 40).fillna(False).values
    pos = np.zeros(len(df)); st = 0; bars = 0
    for i in range(len(df)):
        if st == 0 and entry[i]: st, bars = 1, 0
        elif st == 1:
            bars += 1
            if ex[i] or bars >= 10: st = 0
        pos[i] = st
    return pd.Series(pos, index=df.index)

# ---- S02  SMA 50/200 crossover (canonical for the whole MA-cross family)
def s02_sma_cross(df):
    f = df["Close"].rolling(50).mean(); s = df["Close"].rolling(200).mean()
    return (f > s).astype(float)

# ---- S03  MACD(12,26,9) signal crossover
def s03_macd(df):
    c = df["Close"]
    line = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sig  = line.ewm(span=9, adjust=False).mean()
    return (line > sig).astype(float)

# ---- S04  Bollinger(20,2) + RSI(14) mean reversion (10-bar time stop)
def s04_bb_rsi(df):
    c = df["Close"]; m = c.rolling(20).mean(); sd = c.rolling(20).std()
    lo, hi = m - 2*sd, m + 2*sd; r = _rsi(c, 14)
    entry = ((c <= lo) & (r < 30)).fillna(False).values
    ex    = ((c >= hi) & (r > 70)).fillna(False).values
    pos = np.zeros(len(df)); st = 0; bars = 0
    for i in range(len(df)):
        if st == 0 and entry[i]: st, bars = 1, 0
        elif st == 1:
            bars += 1
            if ex[i] or bars >= 10: st = 0
        pos[i] = st
    return pd.Series(pos, index=df.index)

# ---- S06  LSMA(25) cross (long while close below the regression line)
def s06_lsma(df):
    return (df["Close"] < _lsma(df["Close"], 25)).astype(float)

# ---- S07  Stoch-K(8)<5 + SMA200, 3% buy-limit valid 10 bars (approx fill)
def s07_stoch_limit(df):
    ll = df["Low"].rolling(8).min(); hh = df["High"].rolling(8).max()
    k = 100 * (df["Close"] - ll) / (hh - ll)
    f = df["Close"] > df["Close"].rolling(200).mean()
    sig = (f & (k < 5)).fillna(False).values
    low, close = df["Low"].values, df["Close"].values
    pos = np.zeros(len(df)); st = 0; bars = 0
    pending = False; plife = 0; limit = np.nan; fill = np.nan
    for i in range(len(df)):
        if st == 0 and not pending and sig[i]:
            pending, plife, limit = True, 0, close[i]*0.97
        if pending and st == 0:
            plife += 1
            if low[i] <= limit:                 # limit fills -> go long
                st, bars, fill, pending = 1, 0, limit, False
            elif plife >= 10:
                pending = False                  # order expired unfilled
        elif st == 1:
            bars += 1
            if close[i] > fill or bars >= 10: st = 0
        pos[i] = st
    return pd.Series(pos, index=df.index)
    # NOTE: entry price is the limit (3% below), but the engine accrues
    # close-to-close, so the first bar's P&L is slightly off. Approximation, flagged.

# ---- S08  LinReg(14) mean reversion + SMA200, LONG and SHORT
def s08_linreg_mr(df):
    lr = _lsma(df["Close"], 14); above = df["Close"] > df["Close"].rolling(200).mean()
    el = ((df["Close"] < lr) & above).fillna(False).values
    xl = (df["Close"] > lr).fillna(False).values
    es = ((df["Close"] > lr) & ~above).fillna(False).values
    xs = (df["Close"] < lr).fillna(False).values
    pos = np.zeros(len(df)); st = 0
    for i in range(len(df)):
        if st == 0:
            if el[i]: st = 1
            elif es[i]: st = -1
        elif st == 1 and xl[i]: st = 0
        elif st == -1 and xs[i]: st = 0
        pos[i] = st
    return pd.Series(pos, index=df.index)

# ---- S10  Donchian breakout: long on N-high break, exit on M-low break
#      (this is the position-series form; the catalog's TP/SL version needs
#       intrabar logic your close-to-close engine can't model — flagged)
def s10_breakout(df, n=20, exit_n=10):
    hh = df["High"].rolling(n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    entry = (df["Close"] > hh).fillna(False).values
    ex    = (df["Close"] < ll).fillna(False).values
    pos = np.zeros(len(df)); st = 0
    for i in range(len(df)):
        if st == 0 and entry[i]: st = 1
        elif st == 1 and ex[i]: st = 0
        pos[i] = st
    return pd.Series(pos, index=df.index)


STRATS = {
    "s01": s01_rsi_mr, "s02": s02_sma_cross, "s03": s03_macd, "s04": s04_bb_rsi,
    "s06": s06_lsma, "s07": s07_stoch_limit, "s08": s08_linreg_mr, "s10": s10_breakout,
}
