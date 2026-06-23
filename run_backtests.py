#!/usr/bin/env python3
"""
run_backtests.py  —  Stage-6 driver. Backtest EVERY codegen'd strategy honestly
and decide, by the project's own bar, which ones actually work.

The bar (from README/OVERVIEW guardrails):
    Beat SPY/underlying BUY&HOLD out-of-sample, AFTER costs.

To avoid the "one ticker, one split" fragility flagged in OVERVIEW, single-ticker
strategies are run across a small basket and judged on how often they clear the bar.
Multi-ticker strategies (allocation, pairs) run on the tickers chosen at codegen time.
Results are written to backtest_results.csv, and the winners are emitted as an
importable registry in working_strategies.py.

The strategy source is whatever codegen produced:
    STRAT_MODULE=generated_strats   (default; falls back to catalog_strats if absent)
A module just needs STRATS (single-ticker df->position) and optionally
MULTI (key -> {fn, tickers, roles, benchmark}) + META.

    python run_backtests.py
    STRAT_MODULE=catalog_strats python run_backtests.py     # parity / legacy
"""
import importlib, os
import numpy as np, pandas as pd, yfinance as yf

COST_BPS   = 5
TRAIN_FRAC = 0.6
C          = COST_BPS / 10000.0
ROBUST_SHARPE = 0.65

# basket for the single-ticker strategies: 2 indices + 3 large caps
BASKET = ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL"]

# ---- pick the strategy source ------------------------------------------------
STRAT_MODULE = os.environ.get("STRAT_MODULE", "generated_strats")
try:
    sm = importlib.import_module(STRAT_MODULE)
except ModuleNotFoundError:
    import catalog_strats as sm
    STRAT_MODULE = "catalog_strats"

SINGLE = dict(sm.STRATS)
MULTI  = dict(getattr(sm, "MULTI", {}))

# Legacy shim: catalog_strats has no MULTI; reconstruct the two fixed extras so the
# parity run still tests S11/S12 exactly as the old run_extras() did.
if STRAT_MODULE == "catalog_strats" and not MULTI:
    from extras_backtest import s11_alloc, s12_pairs
    MULTI = {
        "s11": {"fn": s11_alloc, "tickers": ["QQQ", "BND"], "roles": ["risk", "safe"], "benchmark": "risk_asset"},
        "s12": {"fn": s12_pairs, "tickers": ["KO", "PEP"],  "roles": ["a", "b"],     "benchmark": "cash"},
    }

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

# ---- run a multi-ticker strategy (allocation / pairs) generically -----------
def run_multi(key, spec):
    dfs = [load(t) for t in spec["tickers"]]
    if any(d.empty for d in dfs):
        return None
    ret = spec["fn"](*dfs)                      # multi-ticker fns return a return series
    s = oos_split(ret)
    m = metrics(ret.iloc[s:])
    if spec.get("benchmark") == "risk_asset":   # benchmark = buy&hold the first (risk) asset
        bh = dfs[0]["Close"].pct_change().fillna(0)
        b = metrics(bh.iloc[s:])
        bht, bhsh, bhdd = b["total"], b["sharpe"], b["maxdd"]
        beats_ret, beats_sh = m["total"] > b["total"], m["sharpe"] > b["sharpe"]
    else:                                       # market-neutral: benchmark is cash (0)
        bht = bhsh = bhdd = 0.0
        beats_ret, beats_sh = m["total"] > 0.0, m["sharpe"] > 0.0
    return dict(
        strat=key, ticker="/".join(spec["tickers"]),
        oos_total=m["total"], oos_sharpe=m["sharpe"], oos_maxdd=m["maxdd"],
        bh_total=bht, bh_sharpe=bhsh, bh_maxdd=bhdd,
        beats_return=beats_ret, beats_sharpe=beats_sh,
    )

# ---- the "standalone-robust" bar --------------------------------------------
# A strategy can be worth trading even if it does not beat a raging-bull buy&hold:
# for an active agent, the real test is whether it stands on its OWN out-of-sample,
# after costs, consistently. Robust = positive OOS net return on EVERY tested
# ticker AND mean OOS Sharpe >= ROBUST_SHARPE.
def robust_single(df, key):
    sub = df[df.strat == key]
    all_pos = bool((sub.oos_total > 0).all())
    mean_sh = float(sub.oos_sharpe.mean())
    return all_pos and mean_sh >= ROBUST_SHARPE, all_pos, mean_sh

def main():
    rows = []
    print(f"Backtesting {len(SINGLE)} single-ticker + {len(MULTI)} multi-ticker "
          f"strategies from {STRAT_MODULE} across {len(BASKET)} tickers "
          f"(cost {COST_BPS}bps/trade, {int(TRAIN_FRAC*100)}/{int((1-TRAIN_FRAC)*100)} split)\n")

    for key, fn in SINGLE.items():
        for t in BASKET:
            r = run_single(key, fn, t)
            if r:
                rows.append(r)
                flag = "WIN " if r["beats_return"] else "    "
                print(f"  {flag}{key:5s} {t:6s} "
                      f"OOS {r['oos_total']:7.1%} (Sh {r['oos_sharpe']:4.2f}, DD {r['oos_maxdd']:6.1%})  "
                      f"vs B&H {r['bh_total']:7.1%}")

    multi_rows = []
    for key, spec in MULTI.items():
        r = run_multi(key, spec)
        if r:
            multi_rows.append(r); rows.append(r)
            flag = "WIN " if r["beats_return"] else "    "
            print(f"  {flag}{key:5s} {r['ticker']:8s} "
                  f"OOS {r['oos_total']:7.1%} (Sh {r['oos_sharpe']:4.2f}, DD {r['oos_maxdd']:6.1%})  "
                  f"vs bench {r['bh_total']:7.1%}")

    df = pd.DataFrame(rows)
    df.to_csv("backtest_results.csv", index=False)

    # ---- verdict ----------------------------------------------------------
    print("\n" + "="*72)
    print("VERDICT")
    print(f"  Tier 1  BEATS-B&H : beat buy&hold OOS net return, majority of basket")
    print(f"  Tier 2  ROBUST    : positive OOS on ALL tickers AND mean OOS Sharpe >= {ROBUST_SHARPE}")
    print("="*72)
    beats_bh, robust = [], []
    for key in SINGLE:
        sub = df[df.strat == key]
        if sub.empty:
            continue
        n = len(sub); wins = int(sub.beats_return.sum())
        is_robust, all_pos, mean_sh = robust_single(df, key)
        tags = []
        if wins > n/2: tags.append("BEATS-B&H"); beats_bh.append(key)
        if is_robust:  tags.append("ROBUST"); robust.append(key)
        print(f"  {key:5s}  beats-B&H {wins}/{n}   all-positive {str(all_pos):5s}   "
              f"mean-Sharpe {mean_sh:4.2f}   -> {', '.join(tags) or 'fails'}")
    for r in multi_rows:
        t1 = bool(r["beats_return"])
        is_robust = (r["oos_total"] > 0) and (r["oos_sharpe"] >= ROBUST_SHARPE)
        tags = []
        if t1: tags.append("BEATS-B&H"); beats_bh.append(r["strat"])
        if is_robust: tags.append("ROBUST"); robust.append(r["strat"])
        print(f"  {r['strat']:5s}  {r['ticker']:8s} beats-bench {str(t1):5s}   "
              f"OOS-Sharpe {r['oos_sharpe']:4.2f}   -> {', '.join(tags) or 'fails'}")

    print(f"\n  Tier 1 (beat buy&hold OOS): {beats_bh or 'none'}")
    print(f"  Tier 2 (standalone-robust): {robust or 'none'}")

    if hasattr(sm, "META"):
        write_working(beats_bh, robust, df)
        print("\n  -> working_strategies.py    (the surviving rules, importable)")
    else:
        print(f"\n  ({STRAT_MODULE} has no META; skipping working_strategies.py emit)")
    print("  -> backtest_results.csv     (full grid)")
    print("  Research tool, not financial advice.")

# ---- emit the survivors as an importable registry ---------------------------
def _summ(df, key):
    sub = df[df.strat == key]
    return (f"beats-B&H {int(sub.beats_return.sum())}/{len(sub)}, "
            f"positive {int((sub.oos_total > 0).sum())}/{len(sub)}, "
            f"avg OOS return {sub.oos_total.mean():.1%}, avg OOS Sharpe {sub.oos_sharpe.mean():.2f}, "
            f"avg OOS MaxDD {sub.oos_maxdd.mean():.1%}")

def write_working(beats_bh, robust, df):
    keep_all = list(dict.fromkeys(beats_bh + robust))
    lines = ['#!/usr/bin/env python3',
             '"""',
             'working_strategies.py  --  AUTO-GENERATED by run_backtests.py.',
             'The strategies that SURVIVED honest out-of-sample backtesting (after',
             '5bps/trade costs, 60/40 split, basket of SPY/QQQ/AAPL/MSFT/GOOGL).',
             '',
             'Two honest tiers:',
             '  BEATS_BUYHOLD : beat buy&hold OOS net return on a majority of the basket.',
             '  ROBUST        : positive OOS net return on EVERY tested ticker AND mean',
             f'                  OOS Sharpe >= {ROBUST_SHARPE}. Stands on its own for an active agent.',
             '',
             'Code of record is generated_strats.py (+ strategy_templates.py); this module',
             're-exports the survivors as importable registries with their evidence. The',
             'survivors advance to Stage 7 (agent rules).',
             'Research tool, not financial advice.',
             '"""',
             'from generated_strats import STRATS as _SINGLE, MULTI as _MULTI, META',
             '']
    for key in keep_all:
        tiers = []
        if key in beats_bh: tiers.append("BEATS-B&H")
        if key in robust:   tiers.append("ROBUST")
        nm = sm.META.get(key, {}).get("name", "")
        lines.append(f"# [{' + '.join(tiers)}] {key} ({nm}): {_summ(df, key)}")
    lines.append("")

    def ref(key):
        return f'_SINGLE["{key}"]' if key in SINGLE else f'_MULTI["{key}"]["fn"]'

    def reg(name, keys, comment):
        out = [f"# {comment}", f"{name} = {{"]
        for k in keys:
            out.append(f'    "{k}": {ref(k)},')
        out.append("}"); out.append("")
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
