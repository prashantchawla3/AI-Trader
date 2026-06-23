#!/usr/bin/env python3
"""
bot.py — strategy-agnostic PAPER trading bot. ONE decision per run.

Runs any of the validated single-instrument strategies from catalog_strats.py,
enforces hard guardrails IN CODE, asks for human approval, and logs every
decision (including NO TRADE). This is paper scaffolding for demos and dry-runs.

HONEST STATUS: no strategy here beats buy-and-hold out-of-sample (verified by
hand and by run_backtests.py — BEATS_BUYHOLD is empty). That is exactly why this
bot is PAPER-ONLY and approval-gated. It demonstrates the SYSTEM, not profits.

GUARDRAILS (charter rules, enforced in code — not in a prompt):
  #2 human approval before any fill, even on paper
  #3 position size cap + daily loss limit
  #4 malformed / ambiguous signal -> NO TRADE (default-safe)
  #5 every decision logged: fills, holds, no-trades, declines

  python bot.py --list                 # show available strategies
  python bot.py SPY s10                 # one paper decision with strategy s10
  python bot.py --selftest              # prove the guardrails fire
  python bot.py SPY s10 --yes           # auto-approve (paper only, for demos)
"""
import sys, json, os, datetime as dt
import numpy as np, pandas as pd, yfinance as yf
import catalog_strats

# strategies that fit this bot's single-instrument, position-based model (8 of 12).
# S11 (allocation) and S12 (pairs) need a two-leg model this paper bot doesn't
# have yet; S05/S09 were dropped (dead out-of-sample). Labeled, not faked.
STRATS = dict(catalog_strats.STRATS)
NOT_SUPPORTED = {
    "s05": "dropped (dead OOS)", "s09": "dropped (dead OOS)",
    "s11": "needs 2-asset allocation model (not single-instrument)",
    "s12": "needs 2-leg pairs model (not single-instrument)",
}

MODE             = "paper"      # "live" is not implemented on purpose
START_CASH       = 10_000.0
MAX_POSITION_USD = 5_000.0      # hard cap on exposure (rule #3)
DAILY_LOSS_PCT   = 0.02         # flatten if down >2% from day start (rule #3)
COST_BPS         = 5
C                = COST_BPS / 10000.0
STATE_FILE       = "bot_state.json"
LOG_FILE         = "bot_log.csv"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f: return json.load(f)
    return {"shares": 0, "cash": START_CASH, "entry_price": 0.0,
            "day_start_equity": START_CASH, "last_date": "", "strategy": ""}

def save_state(s):
    with open(STATE_FILE, "w") as f: json.dump(s, f, indent=2)

def log(row):
    pd.DataFrame([row]).to_csv(LOG_FILE, mode="a",
                              header=not os.path.exists(LOG_FILE), index=False)

# ---- guardrails (pure functions) -------------------------------------------
def validate_signal(sig):
    if sig is None: return None, "signal is None"
    try:
        if np.isnan(sig): return None, "signal is NaN"
    except TypeError:
        return None, "signal not numeric"
    if sig not in (-1, 0, 1): return None, f"signal {sig} not in (-1,0,1)"
    return int(sig), None

def cap_position(target_signal, price):
    return target_signal * int(MAX_POSITION_USD // price)

def daily_loss_breached(equity, day_start_equity):
    return equity <= day_start_equity * (1 - DAILY_LOSS_PCT)

# ---- decision cycle ---------------------------------------------------------
def get_today_signal(ticker, fn):
    df = yf.download(ticker, period="2y", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty: return None, None, "no data"
    last = fn(df).dropna()
    if last.empty: return None, None, "strategy produced no signal"
    return float(last.iloc[-1]), float(df["Close"].iloc[-1]), None

def run(ticker, strat_key, auto_yes=False):
    if strat_key in NOT_SUPPORTED:
        print(f"'{strat_key}' not runnable here: {NOT_SUPPORTED[strat_key]}")
        return
    if strat_key not in STRATS:
        print(f"unknown strategy '{strat_key}'. try: python bot.py --list"); return
    fn = STRATS[strat_key]

    s = load_state()
    if s.get("strategy") and s["strategy"] != strat_key:
        print(f"NOTE: paper account was running '{s['strategy']}', now '{strat_key}'. "
              f"Positions/PnL carry over — reset bot_state.json for a clean run.")
    s["strategy"] = strat_key
    today = dt.date.today().isoformat()
    sig_raw, price, err = get_today_signal(ticker, fn)
    base = dict(ts=dt.datetime.now().isoformat(), mode=MODE, ticker=ticker, strategy=strat_key)

    if err:
        log({**base, "decision": "NO_TRADE", "reason": err})
        print(f"NO TRADE — {err}"); return

    equity_now = s["cash"] + s["shares"] * price
    if s["last_date"] != today:
        s["day_start_equity"] = equity_now; s["last_date"] = today

    sig, why = validate_signal(sig_raw)        # rule #4
    if sig is None:
        log({**base, "price": price, "decision": "NO_TRADE", "reason": why})
        save_state(s); print(f"NO TRADE — {why}"); return

    forced_flat = daily_loss_breached(equity_now, s["day_start_equity"])  # rule #3
    target_signal = 0 if forced_flat else sig
    desired_shares = cap_position(target_signal, price)                   # rule #3
    order = desired_shares - s["shares"]
    reason = ("daily loss limit hit -> flatten" if forced_flat
              else f"signal={sig}, target={desired_shares}sh")

    print(f"\n[{MODE}] {ticker} via {strat_key} @ {price:.2f}  equity ${equity_now:,.0f}")
    print(f"  current: {s['shares']}sh   target: {desired_shares}sh   -> order: {order:+d}sh")
    print(f"  reason: {reason}")

    if order == 0:
        log({**base, "price": price, "decision": "HOLD", "shares": s["shares"],
             "equity": round(equity_now, 2), "reason": reason})
        save_state(s); print("  HOLD — no order."); return

    if not auto_yes:                            # rule #2: human approval
        if input("  APPROVE this order? [y/N] ").strip().lower() != "y":
            log({**base, "price": price, "decision": "PROPOSED_DECLINED",
                 "order": int(order), "reason": "human declined"})
            print("  declined — nothing executed."); return

    s["cash"] -= order * price + abs(order) * price * C   # paper fill
    s["shares"] += order
    s["entry_price"] = price if s["shares"] != 0 else 0.0
    eq = s["cash"] + s["shares"] * price
    save_state(s)
    log({**base, "price": price, "decision": "FILLED_PAPER", "order": int(order),
         "shares": s["shares"], "equity": round(eq, 2), "reason": reason})
    print(f"  FILLED (paper): {order:+d}sh. new equity ${eq:,.0f}")

# ---- list + self-test -------------------------------------------------------
def show_list():
    print("Runnable strategies (single-instrument, paper):")
    names = {"s01":"RSI(10) mean-rev + SMA200","s02":"SMA 50/200 crossover",
             "s03":"MACD signal crossover","s04":"Bollinger+RSI mean-rev",
             "s06":"LSMA(25) cross","s07":"Stoch + buy-limit",
             "s08":"LinReg mean-rev (long/short)","s10":"Donchian breakout"}
    for k in STRATS: print(f"  {k:4s}  {names.get(k,'')}")
    print("Not runnable here (need other models):")
    for k, why in NOT_SUPPORTED.items(): print(f"  {k:4s}  {why}")
    print("\nReminder: none beat buy-and-hold OOS. Paper-only by design.")

def selftest():
    print("guardrail self-test:")
    ok = True
    for bad in [None, float("nan"), 2, 0.5, "long"]:
        v, why = validate_signal(bad); ok &= v is None
        print(f"  signal {str(bad):>5}  -> {'NO_TRADE' if v is None else 'LEAKED!'} ({why})")
    for g in [-1, 0, 1]:
        v, _ = validate_signal(g); ok &= (v == g)
    sh = cap_position(1, 100.0); capped = sh*100.0 <= MAX_POSITION_USD; ok &= capped
    print(f"  cap @ $100: {sh}sh = ${sh*100.0:,.0f}  -> {'within cap' if capped else 'OVER!'}")
    fires = daily_loss_breached(9_700, 10_000); holds = not daily_loss_breached(9_900, 10_000)
    ok &= fires and holds
    print(f"  loss limit: -3% fires={fires}, -1% holds={holds}")
    print("ALL GUARDRAILS PASS" if ok else "*** GUARDRAIL FAILURE ***")
    return ok

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--list" in args: show_list()
    elif "--selftest" in args: selftest()
    elif len(args) >= 2 and not args[0].startswith("-"):
        run(args[0], args[1], auto_yes=("--yes" in args))
    else:
        print("usage: python bot.py --list | python bot.py SPY s10 | python bot.py --selftest")
