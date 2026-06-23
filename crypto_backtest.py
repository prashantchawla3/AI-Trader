#!/usr/bin/env python3
"""
crypto_backtest.py  --  Stage-6b: RE-VALIDATE every codegen'd strategy on the
actual target market (Hyperliquid crypto perps) instead of US stocks.

Why this file exists
--------------------
run_backtests.py validated the strategies on US equities (SPY/QQQ/AAPL/MSFT/GOOGL).
But we trade Hyperliquid *crypto perps*. agent_strategies_rules.json guardrail #1 is
explicit: "Re-validate every strategy out-of-sample on the actual target symbol
before live size." A 0.78 Sharpe on SPY says nothing about BTC.

What changes vs run_backtests.py (and what deliberately does NOT)
----------------------------------------------------------------
  * DATA   : Hyperliquid daily candles for BTC/ETH/SOL (crypto_data.fetch_hl_candles)
             instead of yfinance. 24/7 UTC bars. ~5.8y, spans the 2022 bear.
  * COSTS  : same 5bps/trade (HL perp taker is 4.5bps -> comparable) PLUS a new
             HOURLY FUNDING drag, modeled as an annualized rate charged daily on
             held notional. This is the cost the stock engine has no concept of and
             the API reference flags twice as mandatory for swing holds.
  * LOGIC  : UNCHANGED. Same strategy functions, same next-bar fill, same 60/40
             OOS split, same metrics, same ROBUST bar. Only the market is different.

Output
------
  * crypto_backtest_results.csv     full grid
  * working_strategies_crypto.py    the crypto survivors, importable (mirrors
                                    working_strategies.py) -> feeds the live agent

Run:  venv/Scripts/python.exe crypto_backtest.py
      FUNDING_APR=0.20 venv/Scripts/python.exe crypto_backtest.py   # stress funding

Research tool, not financial advice.
"""
import os
import numpy as np
import pandas as pd

from crypto_data import fetch_hl_candles, cash_frame
import generated_strats as sm

# ---- knobs ------------------------------------------------------------------
BASKET        = ["BTC", "ETH", "SOL"]            # majors only, per strategy decision
COST_BPS      = 5                                # ~HL perp taker; matches stock run
FUNDING_APR   = float(os.environ.get("FUNDING_APR", "0.10"))  # annualized funding drag
TRAIN_FRAC    = 0.6
ROBUST_SHARPE = 0.65
BARS_PER_YEAR = 365                              # crypto trades every day (not 252!)
C             = COST_BPS / 10000.0
FUND_DAILY    = FUNDING_APR / BARS_PER_YEAR      # funding charged per day held

SINGLE = dict(sm.STRATS)
MULTI  = dict(getattr(sm, "MULTI", {}))

_cache = {}
def load(coin):
    if coin not in _cache:
        _cache[coin] = fetch_hl_candles(coin, interval="1d")
    return _cache[coin]

# ---- engine (mirrors run_backtests.backtest, + funding) ---------------------
def backtest(df, pos, funding_apr=FUNDING_APR):
    """Net daily return after trading cost AND hourly funding drag.

    funding is paid every hour on the open notional; for daily long/flat bars we
    charge it once per day on |position|. Modeled as the conservative typical case
    (longs pay). Real funding fluctuates and can be negative -- stress with FUNDING_APR.
    """
    ret = df["Close"].pct_change().fillna(0)
    pos = pos.shift(1).fillna(0)                 # next-bar fill, no look-ahead
    trades = pos.diff().abs().fillna(0)
    cost = trades * C
    funding = pos.abs() * (funding_apr / BARS_PER_YEAR)
    return pos * ret - cost - funding

def metrics(ret):
    ret = ret.fillna(0)
    eq = (1 + ret).cumprod()
    yrs = len(ret) / BARS_PER_YEAR
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else 0
    sharpe = (ret.mean() / ret.std() * np.sqrt(BARS_PER_YEAR)) if ret.std() else 0
    dd = (eq / eq.cummax() - 1).min()
    total = eq.iloc[-1] - 1
    return dict(cagr=cagr, sharpe=sharpe, maxdd=dd, total=total)

def oos_split(series):
    return int(len(series) * TRAIN_FRAC)

# ---- single-ticker run ------------------------------------------------------
def run_single(key, fn, coin):
    df = load(coin)
    if df.empty:
        return None
    ret = backtest(df, fn(df))
    bh = df["Close"].pct_change().fillna(0)
    s = oos_split(ret)
    m = metrics(ret.iloc[s:])
    b = metrics(bh.iloc[s:])
    return dict(
        strat=key, ticker=coin,
        oos_total=m["total"], oos_sharpe=m["sharpe"], oos_maxdd=m["maxdd"],
        bh_total=b["total"], bh_sharpe=b["sharpe"], bh_maxdd=b["maxdd"],
        beats_return=m["total"] > b["total"],
        beats_sharpe=m["sharpe"] > b["sharpe"],
    )

# ---- multi-ticker (allocation): risk=BTC, safe=cash/USDC --------------------
def run_multi(key, spec):
    risk = load("BTC")
    safe = cash_frame(risk.index)                # no bond fund in crypto -> sit in USDC
    ret = spec["fn"](risk, safe)
    # allocation fn bakes in trade cost but not funding; approximate funding on the
    # average risk weight (we're long BTC most of the time it's risk-on).
    on_w = sm.META.get(key, {}).get("params", {}).get("on_risk_w", 0.8)
    ret = ret - on_w * FUND_DAILY
    s = oos_split(ret)
    m = metrics(ret.iloc[s:])
    bh = risk["Close"].pct_change().fillna(0)    # benchmark = buy&hold BTC
    b = metrics(bh.iloc[s:])
    return dict(
        strat=key, ticker="BTC/USDC",
        oos_total=m["total"], oos_sharpe=m["sharpe"], oos_maxdd=m["maxdd"],
        bh_total=b["total"], bh_sharpe=b["sharpe"], bh_maxdd=b["maxdd"],
        beats_return=m["total"] > b["total"], beats_sharpe=m["sharpe"] > b["sharpe"],
    )

def robust_single(df, key):
    sub = df[df.strat == key]
    all_pos = bool((sub.oos_total > 0).all())
    mean_sh = float(sub.oos_sharpe.mean())
    return all_pos and mean_sh >= ROBUST_SHARPE, all_pos, mean_sh

# ---- driver -----------------------------------------------------------------
def main():
    print(f"Re-validating {len(SINGLE)} single + {len(MULTI)} multi strategies on "
          f"Hyperliquid CRYPTO {BASKET}\n  cost {COST_BPS}bps/trade + funding "
          f"{FUNDING_APR:.0%} APR ({FUND_DAILY*1e4:.2f}bps/day held), "
          f"{int(TRAIN_FRAC*100)}/{int((1-TRAIN_FRAC)*100)} OOS split\n")

    rows = []
    for key, fn in SINGLE.items():
        for coin in BASKET:
            try:
                r = run_single(key, fn, coin)
            except Exception as e:
                print(f"  !! {key} {coin}: {e}"); continue
            if r:
                rows.append(r)
                flag = "WIN " if r["beats_return"] else "    "
                print(f"  {flag}{key:5s} {coin:4s} "
                      f"OOS {r['oos_total']:8.1%} (Sh {r['oos_sharpe']:5.2f}, DD {r['oos_maxdd']:6.1%})  "
                      f"vs B&H {r['bh_total']:8.1%}")

    multi_rows = []
    for key, spec in MULTI.items():
        try:
            r = run_multi(key, spec)
        except Exception as e:
            print(f"  !! {key}: {e}"); continue
        if r:
            multi_rows.append(r); rows.append(r)
            flag = "WIN " if r["beats_return"] else "    "
            print(f"  {flag}{key:5s} {r['ticker']:8s} "
                  f"OOS {r['oos_total']:8.1%} (Sh {r['oos_sharpe']:5.2f}, DD {r['oos_maxdd']:6.1%})  "
                  f"vs B&H {r['bh_total']:8.1%}")

    df = pd.DataFrame(rows)
    df.to_csv("crypto_backtest_results.csv", index=False)

    print("\n" + "=" * 74)
    print("VERDICT  (target market: Hyperliquid crypto perps)")
    print(f"  Tier 1  BEATS-B&H : beat buy&hold OOS net return, majority of basket")
    print(f"  Tier 2  ROBUST    : positive OOS on ALL coins AND mean OOS Sharpe >= {ROBUST_SHARPE}")
    print("=" * 74)
    beats_bh, robust = [], []
    for key in SINGLE:
        sub = df[df.strat == key]
        if sub.empty:
            continue
        n = len(sub); wins = int(sub.beats_return.sum())
        is_robust, all_pos, mean_sh = robust_single(df, key)
        tags = []
        if wins > n / 2: tags.append("BEATS-B&H"); beats_bh.append(key)
        if is_robust:    tags.append("ROBUST"); robust.append(key)
        nm = sm.META.get(key, {}).get("name", "")[:34]
        print(f"  {key:5s} {nm:34s} beats {wins}/{n}  pos {str(all_pos):5s}  "
              f"Sh {mean_sh:5.2f}  -> {', '.join(tags) or 'fails'}")
    for r in multi_rows:
        t1 = bool(r["beats_return"])
        is_robust = (r["oos_total"] > 0) and (r["oos_sharpe"] >= ROBUST_SHARPE)
        tags = []
        if t1: tags.append("BEATS-B&H"); beats_bh.append(r["strat"])
        if is_robust: tags.append("ROBUST"); robust.append(r["strat"])
        print(f"  {r['strat']:5s} {'allocation BTC/USDC':34s} "
              f"OOS-Sharpe {r['oos_sharpe']:5.2f}  -> {', '.join(tags) or 'fails'}")

    print(f"\n  Tier 1 (beat buy&hold OOS): {beats_bh or 'none'}")
    print(f"  Tier 2 (standalone-robust): {robust or 'none'}")

    write_working(beats_bh, robust, df)
    print("\n  -> working_strategies_crypto.py   (crypto survivors, importable)")
    print("  -> crypto_backtest_results.csv    (full grid)")
    print("  Research tool, not financial advice.")

# ---- emit survivors ---------------------------------------------------------
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
             'working_strategies_crypto.py  --  AUTO-GENERATED by crypto_backtest.py.',
             'Strategies that SURVIVED out-of-sample backtesting ON HYPERLIQUID CRYPTO',
             f'(BTC/ETH/SOL daily, {COST_BPS}bps/trade + {int(FUNDING_APR*100)}% APR funding, '
             f'{int(TRAIN_FRAC*100)}/{int((1-TRAIN_FRAC)*100)} split).',
             '',
             'This is the crypto re-validation required by agent_strategies_rules.json',
             'guardrail #1. These -- NOT the US-equity survivors in working_strategies.py --',
             'are the strategies cleared to advance to the live Hyperliquid agent.',
             '',
             'Two tiers:',
             '  BEATS_BUYHOLD : beat buy&hold BTC/ETH/SOL OOS net return (majority of basket).',
             f'  ROBUST        : positive OOS on EVERY coin AND mean OOS Sharpe >= {ROBUST_SHARPE}.',
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
                 "Tier 1: beat buy&hold OOS net return (majority of BTC/ETH/SOL).")
    lines += reg("ROBUST", robust,
                 f"Tier 2: standalone-robust on crypto (positive everywhere, mean OOS Sharpe >= {ROBUST_SHARPE}).")
    lines.append("# Combined registry of crypto survivors -> live Hyperliquid agent.")
    lines.append("STRATS = {**BEATS_BUYHOLD, **ROBUST}")
    lines.append("")
    with open("working_strategies_crypto.py", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

if __name__ == "__main__":
    main()
