#!/usr/bin/env python3
"""
extras_backtest.py  —  the strategies that DON'T fit your 04_backtest.py
position engine, run standalone with the same cost + split + stats conventions.

  S11 allocation  : QQQ/BND 80/20 <-> 20/80 by SMA30 (two tickers, fractional)
  S12 pairs       : KO/PEP z-score, market-neutral (two tickers, spread)

S05 (gap-up) and S09 (overnight) were here too, but both failed decisively
out-of-sample on SPY (~ -13% and -14% CAGR, drawdowns near -75% full-window).
Their edge in the source tutorials was futures-specific, not an SPY equity edge,
so they were dropped. See git history for the prior version that tested them.

    python extras_backtest.py

Same knobs as your main script so the numbers are comparable.
"""
import numpy as np, pandas as pd, yfinance as yf

COST_BPS   = 5          # per side, basis points (matches your engine's mechanism)
TRAIN_FRAC = 0.6
C          = COST_BPS / 10000.0

def load(t):
    df = yf.download(t, period="10y", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

def stats(ret, label):
    ret = ret.fillna(0); eq = (1 + ret).cumprod(); yrs = len(ret)/252
    cagr = eq.iloc[-1]**(1/yrs) - 1 if yrs > 0 else 0
    sharpe = (ret.mean()/ret.std()*np.sqrt(252)) if ret.std() else 0
    dd = (eq/eq.cummax() - 1).min()
    print(f"  {label:13s} CAGR {cagr:7.2%}  Sharpe {sharpe:5.2f}  "
          f"MaxDD {dd:7.2%}  Total {eq.iloc[-1]-1:7.2%}")

def report(name, ret, bh_oos=None):
    split = int(len(ret) * TRAIN_FRAC)
    print(f"\n{name}")
    stats(ret, "FULL")
    stats(ret.iloc[:split], "IN-SAMPLE")
    stats(ret.iloc[split:], "OUT-SAMPLE")
    if bh_oos is not None:
        stats(bh_oos.iloc[split:], "BUY&HOLD (OOS)")

# ---- the strategies -> daily return series ----------------------------------
def s11_alloc(qqq, bnd):
    w = pd.Series(np.where(qqq["Close"] > qqq["Close"].rolling(30).mean(), 0.8, 0.2),
                  index=qqq.index)
    rq = qqq["Close"].pct_change()
    rb = bnd["Close"].pct_change().reindex(qqq.index)
    return (w.shift(1)*rq + (1-w).shift(1)*rb - w.diff().abs()*C).fillna(0)

def s12_pairs(a, b, look=252, z_in=2.0, z_out=0.5):
    df = pd.DataFrame({"a": a["Close"], "b": b["Close"]}).dropna()
    beta = df["a"].rolling(look).cov(df["b"]) / df["b"].rolling(look).var()
    spread = df["a"] - beta*df["b"]
    z = (spread - spread.rolling(look).mean()) / spread.rolling(look).std()
    pos = np.zeros(len(df)); st = 0
    for i in range(len(df)):
        if st == 0:
            if z.iloc[i] < -z_in: st = 1
            elif z.iloc[i] > z_in: st = -1
        elif abs(z.iloc[i]) < z_out: st = 0
        pos[i] = st
    pos = pd.Series(pos, index=df.index)
    ra, rb = df["a"].pct_change(), df["b"].pct_change()
    return (pos.shift(1)*(ra - rb) - pos.diff().abs()*2*C).fillna(0)

def main():
    qqq = load("QQQ"); bnd = load("BND")
    ko = load("KO");  pep = load("PEP")

    report("S11  allocation (QQQ/BND)[SMA30 regime 80/20<->20/80]", s11_alloc(qqq, bnd))
    report("S12  pairs (KO/PEP)      [z-score market-neutral]", s12_pairs(ko, pep))
    print("\nS12 caveat: run an ADF / Engle-Granger test on the KO/PEP spread first. "
          "If it isn't cointegrated, this result is meaningless no matter how it looks.")
    print("This is a research tool, not financial advice.")

if __name__ == "__main__":
    main()