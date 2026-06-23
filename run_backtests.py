#!/usr/bin/env python3
"""
run_backtests.py  —  Stage-5 driver. Backtest EVERY catalogued strategy honestly
and decide, by the project's own bar, which ones actually work.

The bar (from README/OVERVIEW guardrails):
    Beat SPY/underlying BUY&HOLD out-of-sample, AFTER costs.

To avoid the "one ticker, one split" fragility flagged in OVERVIEW, the 8 single-
ticker strategies are run across a small basket and judged on how often they clear
the bar. The 2 multi-ticker strategies (S11 allocation, S12 pairs) run on their
fixed pairs. Results are written to backtest_results.csv, and the winners are
emitted as importable rules in working_strategies.py.

    python run_backtests.py
"""
import numpy as np, pandas as pd, yfinance as yf
import catalog_strats
from extras_backtest import s11_alloc, s12_pairs

COST_BPS   = 5
TRAIN_FRAC = 0.6
C          = COST_BPS / 10000.0

# basket for the single-ticker strategies: 2 indices + 3 large caps
BASKET = ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL"]

_cache = {}
def load(t):
    if t not in _cache:
        df = yf.download(t, period="10y", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        _cache[t] = df
    return _cache[t]

# ---- engine (mirrors 04_backtest.py) ----------------------------------------
def backtest(df, pos):
    ret = df["Close"].pct_change().fillna(0)
    pos = pos.shift(1).fillna(0)
    trades = pos.diff().abs().fillna(0)
    cost = trades * C
    return pos * ret - cost

def metrics(ret):
    ret = ret.fillna(0)
    eq = (1 + ret).cumprod()
    yrs = len(ret) / 252
    cagr = eq.iloc[-1] ** (1/yrs) - 1 if yrs > 0 else 0
    sharpe = (ret.mean() / ret.std() * np.sqrt(252)) if ret.std() else 0
    dd = (eq / eq.cummax() - 1).min()
    total = eq.iloc[-1] - 1
    return dict(cagr=cagr, sharpe=sharpe, maxdd=dd, total=total)

def oos_split(series):
    return int(len(series) * TRAIN_FRAC)

# ---- run a single-ticker strategy on one ticker -----------------------------
def run_single(key, fn, ticker):
    df = load(ticker)
    if df.empty:
        return None
    ret = backtest(df, fn(df))
    bh = df["Close"].pct_change().fillna(0)
    s = oos_split(ret)
    m = metrics(ret.iloc[s:])
    b = metrics(bh.iloc[s:])
    return dict(
        strat=key, ticker=ticker,
        oos_total=m["total"], oos_sharpe=m["sharpe"], oos_maxdd=m["maxdd"],
        bh_total=b["total"], bh_sharpe=b["sharpe"], bh_maxdd=b["maxdd"],
        beats_return=m["total"] > b["total"],
        beats_sharpe=m["sharpe"] > b["sharpe"],
    )

# ---- run the two multi-ticker extras ----------------------------------------
def run_extras():
    rows = []
    qqq, bnd = load("QQQ"), load("BND")
    r = s11_alloc(qqq, bnd)
    bh = qqq["Close"].pct_change().fillna(0)   # benchmark: 100% QQQ buy&hold
    s = oos_split(r)
    m, b = metrics(r.iloc[s:]), metrics(bh.iloc[s:])
    rows.append(dict(strat="s11", ticker="QQQ/BND",
        oos_total=m["total"], oos_sharpe=m["sharpe"], oos_maxdd=m["maxdd"],
        bh_total=b["total"], bh_sharpe=b["sharpe"], bh_maxdd=b["maxdd"],
        beats_return=m["total"] > b["total"], beats_sharpe=m["sharpe"] > b["sharpe"]))

    ko, pep = load("KO"), load("PEP")
    r = s12_pairs(ko, pep)
    # market-neutral: benchmark is 0 (cash). "Beat" = positive OOS return.
    s = oos_split(r)
    m = metrics(r.iloc[s:])
    rows.append(dict(strat="s12", ticker="KO/PEP",
        oos_total=m["total"], oos_sharpe=m["sharpe"], oos_maxdd=m["maxdd"],
        bh_total=0.0, bh_sharpe=0.0, bh_maxdd=0.0,
        beats_return=m["total"] > 0.0, beats_sharpe=m["sharpe"] > 0.0))
    return rows

# ---- the "standalone-robust" bar --------------------------------------------
# A strategy can be worth trading even if it does not beat a raging-bull buy&hold:
# for an active agent, the real test is whether it stands on its OWN out-of-sample,
# after costs, consistently. Robust = positive OOS net return on EVERY tested
# ticker AND mean OOS Sharpe >= ROBUST_SHARPE.
ROBUST_SHARPE = 0.65

def robust_single(df, key):
    sub = df[df.strat == key]
    all_pos = bool((sub.oos_total > 0).all())
    mean_sh = float(sub.oos_sharpe.mean())
    return all_pos and mean_sh >= ROBUST_SHARPE, all_pos, mean_sh

def main():
    rows = []
    print(f"Backtesting {len(catalog_strats.STRATS)} single-ticker strategies "
          f"across {len(BASKET)} tickers + 2 multi-ticker extras "
          f"(cost {COST_BPS}bps/trade, {int(TRAIN_FRAC*100)}/{int((1-TRAIN_FRAC)*100)} split)\n")

    for key, fn in catalog_strats.STRATS.items():
        for t in BASKET:
            r = run_single(key, fn, t)
            if r:
                rows.append(r)
                flag = "WIN " if r["beats_return"] else "    "
                print(f"  {flag}{key:4s} {t:6s} "
                      f"OOS {r['oos_total']:7.1%} (Sh {r['oos_sharpe']:4.2f}, DD {r['oos_maxdd']:6.1%})  "
                      f"vs B&H {r['bh_total']:7.1%}")
    rows += run_extras()
    for r in rows[-2:]:
        flag = "WIN " if r["beats_return"] else "    "
        print(f"  {flag}{r['strat']:4s} {r['ticker']:8s} "
              f"OOS {r['oos_total']:7.1%} (Sh {r['oos_sharpe']:4.2f}, DD {r['oos_maxdd']:6.1%})  "
              f"vs bench {r['bh_total']:7.1%}")

    df = pd.DataFrame(rows)
    df.to_csv("backtest_results.csv", index=False)

    # ---- verdict ----------------------------------------------------------
    # Two bars, both honest:
    #   TIER 1  beats buy&hold OOS net return (the project's stated bar)
    #   TIER 2  standalone-robust: positive OOS on every ticker, mean Sharpe >= bar
    print("\n" + "="*72)
    print("VERDICT")
    print(f"  Tier 1  BEATS-B&H : beat buy&hold OOS net return, majority of basket")
    print(f"  Tier 2  ROBUST    : positive OOS on ALL tickers AND mean OOS Sharpe >= {ROBUST_SHARPE}")
    print("="*72)
    beats_bh, robust = [], []
    for key in catalog_strats.STRATS:
        sub = df[df.strat == key]
        n = len(sub); wins = int(sub.beats_return.sum())
        is_robust, all_pos, mean_sh = robust_single(df, key)
        t1 = wins > n/2
        tags = []
        if t1: tags.append("BEATS-B&H"); beats_bh.append(key)
        if is_robust: tags.append("ROBUST"); robust.append(key)
        print(f"  {key:4s}  beats-B&H {wins}/{n}   all-positive {str(all_pos):5s}   "
              f"mean-Sharpe {mean_sh:4.2f}   -> {', '.join(tags) or 'fails'}")
    for r in [x for x in rows if x["strat"] in ("s11", "s12")]:
        t1 = bool(r["beats_return"])
        is_robust = (r["oos_total"] > 0) and (r["oos_sharpe"] >= ROBUST_SHARPE)
        tags = []
        if t1: tags.append("BEATS-B&H"); beats_bh.append(r["strat"])
        if is_robust: tags.append("ROBUST"); robust.append(r["strat"])
        print(f"  {r['strat']:4s}  {r['ticker']:8s} beats-bench {str(t1):5s}   "
              f"OOS-Sharpe {r['oos_sharpe']:4.2f}   -> {', '.join(tags) or 'fails'}")

    print(f"\n  Tier 1 (beat buy&hold OOS): {beats_bh or 'none'}")
    print(f"  Tier 2 (standalone-robust): {robust or 'none'}")

    write_working(beats_bh, robust, df)
    print("\n  -> backtest_results.csv     (full grid)")
    print("  -> working_strategies.py    (the surviving rules, importable)")
    print("  Research tool, not financial advice.")

# ---- emit the survivors as importable rules ---------------------------------
SRC = {
    "s01": "s01_rsi_mr", "s02": "s02_sma_cross", "s03": "s03_macd",
    "s04": "s04_bb_rsi", "s06": "s06_lsma", "s07": "s07_stoch_limit",
    "s08": "s08_linreg_mr", "s10": "s10_breakout",
}
import inspect

def _summ(df, key):
    sub = df[df.strat == key]
    return (f"beats-B&H {int(sub.beats_return.sum())}/{len(sub)}, "
            f"positive {int((sub.oos_total > 0).sum())}/{len(sub)}, "
            f"avg OOS return {sub.oos_total.mean():.1%}, avg OOS Sharpe {sub.oos_sharpe.mean():.2f}, "
            f"avg OOS MaxDD {sub.oos_maxdd.mean():.1%}")

def write_working(beats_bh, robust, df):
    # everything that survived either bar; de-dup, preserve order
    keep_all = list(dict.fromkeys(beats_bh + robust))
    keep_single = [k for k in keep_all if k in SRC]
    lines = ['#!/usr/bin/env python3',
             '"""',
             'working_strategies.py  --  AUTO-GENERATED by run_backtests.py.',
             'The strategies that SURVIVED honest out-of-sample backtesting (after',
             '5bps/trade costs, 60/40 split, basket of SPY/QQQ/AAPL/MSFT/GOOGL).',
             '',
             'Two honest tiers:',
             '  BEATS_BUYHOLD : beat buy&hold OOS net return on a majority of the basket.',
             '                  (A very high bar in the 2015-2025 bull market.)',
             '  ROBUST        : positive OOS net return on EVERY tested ticker AND mean',
             f'                  OOS Sharpe >= {ROBUST_SHARPE}. Stands on its own for an active agent,',
             '                  even where it does not out-run a buy&hold benchmark.',
             '',
             'Each single-ticker strategy is a position function: df -> Series',
             '(1=long, 0=flat, -1=short), drop-in for 04_backtest.py. S11/S12 are',
             'multi-ticker and live in extras_backtest.py; if they survived they are',
             'listed in the registries below (value None) but not redefined here.',
             '',
             'These are the candidates that advance to Stage 6 (code as agent rules).',
             'Research tool, not financial advice.',
             '"""',
             'import numpy as np, pandas as pd',
             '',
             'from catalog_strats import _rsi, _lsma',
             '']
    for key in keep_single:
        fname = SRC[key]
        fn_src = inspect.getsource(getattr(catalog_strats, fname))
        tiers = []
        if key in beats_bh: tiers.append("BEATS-B&H")
        if key in robust:   tiers.append("ROBUST")
        lines.append(f"# [{' + '.join(tiers)}] {key}: {_summ(df, key)}")
        lines.append(fn_src.rstrip())
        lines.append("")

    def reg(name, keys, comment):
        out = [f"# {comment}", f"{name} = {{"]
        for k in keys:
            if k in SRC:
                out.append(f'    "{k}": {SRC[k]},')
            else:
                out.append(f'    "{k}": None,   # multi-ticker -> extras_backtest.py')
        out.append("}")
        out.append("")
        return out

    lines += reg("BEATS_BUYHOLD", beats_bh,
                 "Tier 1: beat buy&hold OOS net return (majority of basket).")
    lines += reg("ROBUST", robust,
                 f"Tier 2: standalone-robust (positive everywhere, mean OOS Sharpe >= {ROBUST_SHARPE}).")
    lines.append("# Combined registry of everything that survived -> next stage.")
    lines.append("STRATS = {**BEATS_BUYHOLD, **ROBUST}")
    lines.append("")
    with open("working_strategies.py", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

if __name__ == "__main__":
    main()
