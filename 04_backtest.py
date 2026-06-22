#!/usr/bin/env python3
"""
04_backtest.py  —  The reality check. Re-implement a strategy from your catalog
and test it HONESTLY on clean data: out-of-sample split, transaction costs, and
metrics that matter. Transcripts give hypotheses; this tells you which survive.

Includes two worked examples (RSI mean-reversion, SMA crossover). Add your own
by writing a function that returns a position series (1=long, 0=flat, -1=short).

    python 04_backtest.py AAPL rsi
    python 04_backtest.py SPY sma

Setup:
    pip install yfinance pandas numpy
"""
import sys
import numpy as np, pandas as pd, yfinance as yf

COST_BPS = 5      # round-trip cost assumption, basis points per trade
TRAIN_FRAC = 0.6  # in-sample fraction; rest is out-of-sample (no peeking)

# ---- indicators -------------------------------------------------------------
def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1 + up/dn)

# ---- strategies: return a position series aligned to df.index ---------------
def strat_rsi(df, low=30, high=70):
    r = rsi(df["Close"])
    pos = pd.Series(np.nan, index=df.index)
    pos[r < low] = 1      # oversold -> long
    pos[r > high] = 0     # exit when no longer oversold
    return pos.ffill().fillna(0)

def strat_sma(df, fast=20, slow=50):
    f = df["Close"].rolling(fast).mean()
    s = df["Close"].rolling(slow).mean()
    return (f > s).astype(float)   # long when fast above slow

STRATS = {"rsi": strat_rsi, "sma": strat_sma}

# ---- backtest engine --------------------------------------------------------
def backtest(df, pos):
    ret = df["Close"].pct_change().fillna(0)
    pos = pos.shift(1).fillna(0)                 # trade on next bar (no look-ahead)
    trades = pos.diff().abs().fillna(0)
    cost = trades * (COST_BPS / 10000.0)
    strat_ret = pos * ret - cost
    return strat_ret

def stats(ret, label):
    eq = (1 + ret).cumprod()
    yrs = len(ret) / 252
    cagr = eq.iloc[-1] ** (1/yrs) - 1 if yrs > 0 else 0
    sharpe = (ret.mean() / ret.std() * np.sqrt(252)) if ret.std() else 0
    dd = (eq / eq.cummax() - 1).min()
    print(f"  {label:13s} CAGR {cagr:7.2%}  Sharpe {sharpe:5.2f}  "
          f"MaxDD {dd:7.2%}  Total {eq.iloc[-1]-1:7.2%}")
    return sharpe

def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    name   = sys.argv[2] if len(sys.argv) > 2 else "rsi"
    if name not in STRATS:
        print("strategies:", ", ".join(STRATS)); return

    df = yf.download(ticker, period="10y", auto_adjust=True, progress=False)
    if df.empty: print("no data for", ticker); return
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    pos = STRATS[name](df)
    ret = backtest(df, pos)

    split = int(len(df) * TRAIN_FRAC)
    print(f"\n{ticker}  strategy='{name}'  (cost {COST_BPS}bps/trade)")
    stats(ret, "FULL")
    stats(ret.iloc[:split], "IN-SAMPLE")
    stats(ret.iloc[split:], "OUT-SAMPLE")          # <- the number that matters
    stats(df["Close"].pct_change().fillna(0).iloc[split:], "BUY&HOLD (OOS)")

    print("\nRead the OUT-SAMPLE row: if a strategy only looks good in-sample, "
          "it's overfit. Beating BUY&HOLD out-of-sample, after costs, is the bar.")
    print("This is a research tool, not financial advice.")

if __name__ == "__main__":
    main()
