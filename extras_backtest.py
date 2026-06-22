#!/usr/bin/env python3
"""
extras_backtest.py  —  the 4 strategies that DON'T fit your 04_backtest.py
position engine, run standalone with the same cost + split + stats conventions.

  S05 gap-up      : buy at Open, sell at Close (needs intraday open->close)
  S09 overnight   : buy at Close, sell at next Open (needs intraday close->open)
  S11 allocation  : QQQ/BND 80/20 <-> 20/80 by SMA30 (two tickers, fractional)
  S12 pairs       : KO/PEP z-score, market-neutral (two tickers, spread)

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

# ---- the four strategies -> daily return series -----------------------------
def s05_gap(df):
    gap = df["Open"] > df["Close"].shift(1)
    return (df["Close"]/df["Open"] - 1).where(gap, 0.0) - gap.astype(float)*2*C

def s09_overnight(df):
    return (df["Open"].shift(-1)/df["Close"] - 1).fillna(0) - 2*C

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
    spy = load("SPY"); qqq = load("QQQ"); bnd = load("BND")
    ko = load("KO");  pep = load("PEP")
    bh = spy["Close"].pct_change()

    report("S05  gap-up (SPY)        [buy open / sell close]", s05_gap(spy), bh)
    report("S09  overnight (SPY)     [buy close / sell next open]", s09_overnight(spy), bh)
    report("S11  allocation (QQQ/BND)[SMA30 regime 80/20<->20/80]", s11_alloc(qqq, bnd))
    report("S12  pairs (KO/PEP)      [z-score market-neutral]", s12_pairs(ko, pep))
    print("\nS12 caveat: run an ADF / Engle-Granger test on the KO/PEP spread first. "
          "If it isn't cointegrated, this result is meaningless no matter how it looks.")
    print("This is a research tool, not financial advice.")

if __name__ == "__main__":
    main()
