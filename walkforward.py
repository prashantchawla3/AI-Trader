#!/usr/bin/env python3
"""
walkforward.py — robustness test for the two strategies that survived the
single-split backtest: S10 (Donchian breakout, SPY) and S11 (QQQ/BND allocation).

A 60/40 split is ONE data point. This slices history into many windows and asks:
does the edge show up year after year, or did one lucky stretch carry it?

NOTE: S10 and S11 have FIXED rules (no parameters fit to the data), so this is
not walk-forward *optimization* — it's a robustness check across time and market
regimes. That's the relevant question for fixed-rule strategies.

    python walkforward.py

Needs catalog_strats.py and extras_backtest.py in the same folder.
"""
import numpy as np, pandas as pd
import catalog_strats
from extras_backtest import s11_alloc, load

COST_BPS = 5
C = COST_BPS / 10000.0

def strat_returns_position(df, pos):        # same engine as 04_backtest.py
    ret = df["Close"].pct_change().fillna(0)
    pos = pos.shift(1).fillna(0)
    cost = pos.diff().abs().fillna(0) * C
    return pos * ret - cost

def win_stats(ret):
    ret = ret.fillna(0)
    if len(ret) < 2 or ret.std() == 0:
        return 0.0, 0.0, 0.0
    eq = (1 + ret).cumprod()
    total = eq.iloc[-1] - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(252)
    dd = (eq / eq.cummax() - 1).min()
    return total, sharpe, dd

def by_year(ret, bench, label):
    print(f"\n{label}")
    print(f"  {'year':6s} {'return':>8s} {'sharpe':>7s} {'maxDD':>8s} "
          f"{'SPY':>8s} {'beat?':>6s}")
    beat = pos = tot = 0
    for y in sorted(set(ret.index.year)):
        r = ret[ret.index.year == y]
        if len(r) < 60:                      # skip partial first/last year
            continue
        t, s, d = win_stats(r)
        b = bench[bench.index.year == y]
        bt = (1 + b.fillna(0)).prod() - 1
        won = t > bt
        beat += won; pos += (t > 0); tot += 1
        print(f"  {y:6d} {t:8.1%} {s:7.2f} {d:8.1%} {bt:8.1%} "
              f"{'yes' if won else 'no':>6s}")
    print(f"  -> {pos}/{tot} years positive | {beat}/{tot} years beat SPY buy&hold")

def main():
    spy = load("SPY"); qqq = load("QQQ"); bnd = load("BND")
    spy_bh = spy["Close"].pct_change()

    pos = catalog_strats.s10_breakout(spy)
    r10 = strat_returns_position(spy, pos)
    by_year(r10, spy_bh, "S10  Donchian breakout (SPY)  -- benchmark: SPY buy&hold")

    r11 = s11_alloc(qqq, bnd)
    by_year(r11, spy_bh, "S11  QQQ/BND allocation  -- benchmark: SPY buy&hold")

    print("\nHow to read this:")
    print("  - 'years positive' = consistency.  'beat SPY' = did it earn its keep.")
    print("  - S11 runs at LOWER risk than 100% SPY, so also weigh Sharpe + maxDD,")
    print("    not just whether it out-returned a fully-invested benchmark.")
    print("  - A strategy that wins most years is robust. One that wins overall but")
    print("    loses most individual years was carried by one stretch -- fragile.")
    print("This is a research tool, not financial advice.")

if __name__ == "__main__":
    main()
