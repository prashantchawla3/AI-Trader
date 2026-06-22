#!/usr/bin/env python3
"""
filter_strategies.py  -  STAGE 1 of the strategy pipeline.

Reads strategies.csv (the YouTube strategy catalog) and writes a RANKED
"to-translate" queue: only the rows worth your time -- mechanical, rule-based
strategies with a concrete entry AND a concrete exit, on a tradeable
instrument, that you could actually code into backtest_framework.py.

What it does NOT do (on purpose):
  - It does NOT translate English -> code. That is a human judgment step.
  - It does NOT decide if a strategy is GOOD. The backtester decides that,
    later, on out-of-sample data after costs.
  - It does NOT rank by claimed_performance. That column is the survivorship/
    cherry-pick trap. This script IGNORES it for ranking and only FLAGS rows
    whose claims look too good to trust.

Usage (Windows):
    py filter_strategies.py strategies.csv

Outputs:
    to_translate_queue.csv  - survivors, best first, with score + flags
    dropped.csv             - everything cut + the reason (AUDIT THIS)
Stdout: the funnel counts and the top of the queue.
"""

import csv, sys, re, argparse

# ---------------------------------------------------------------------------
# CONFIG  -  edit these lists to make the filter stricter or looser.
# ---------------------------------------------------------------------------

KEEP_APPROACH = "rule-based"                 # deterministic logic only
DROP_APPROACH_TOKENS = {"ml", "rl", "deep-learning", "sentiment", "other"}

# Nameable / mechanical -> codable.
MECHANICAL = [
    "sma","ema","moving average","rsi","macd","bollinger","atr","stochastic",
    "adx","cci","williams %","vwap","roc","rate of change","momentum",
    "donchian","keltner","obv","on-balance volume","mfi","money flow",
    "z-score","zscore","standard deviation","supertrend","super trend",
    "parabolic sar","psar","fibonacci","linear regression","garch","channel",
    "least squares","crossover","cross above","cross below","gap up","gap down",
    # plain price conditions (also mechanical / codable)
    "close above","close below","closes above","closes below","closes lower",
    "closes higher","breaks above","breaks below","previous close",
    "prior close","high of day","low of day","new high","new low",
]

# Subjective / hand-drawn. If a row has these and NO mechanical indicator,
# it's pure discretionary -> dropped. If it has both, kept but flagged.
DISCRETIONARY = [
    "key level","key psychological","psychological level","demand zone",
    "supply zone","supply and demand","area of value","order block",
    "smart money","ict","liquidity sweep","liquidity vacuum","fair value gap",
    "otz","optimal trading zone","support and resistance","support/resistance",
    "support & resistance","trend line","trendline","price action",
    "market structure","break of structure","neckline","head and shoulders",
    "double top","double bottom","triple top","triple bottom","engulfing",
    "shooting star","morning star","evening star","tweezer","pin bar",
    "chart pattern","candlestick pattern","liquidity level","stink bid",
    "accumulation","manipulation","distribution","pivot","seasonality",
    "timeality","1-2-3",
]

# Markets a simple stock/crypto/forex/futures backtester can't handle.
EXCLUDE_MARKET = [
    "prediction market","polymarket","kalshi","sports","e-sport","esport",
    "nba","nfl","mlb","tennis","cricket","weather","election","betting",
    "binary option",
]
OPTIONS_MARKET = ["option"]                  # needs greeks/expiries -> out of scope

NULL_PHRASES = [
    "not specified","not applicable","not detailed","not explicitly",
    "not fully","not provided","not stated","not disclosed","not mentioned",
    "not yet","unspecified","tbd","n/a",
]


def is_concrete(text):
    s = (text or "").strip()
    if len(s) < 8:
        return False
    low = s.lower()
    if low in ("none","na","n/a","-"):
        return False
    return not any(p in low for p in NULL_PHRASES)


def _pat(term):
    # token-bounded match: term not flanked by letters/digits.
    # handles spaces, %, - inside terms; kills 'ict' in 'predicted', etc.
    return re.compile(r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])')

_MECH_PATS = [(t, _pat(t)) for t in MECHANICAL]
_DISC_PATS = [(t, _pat(t)) for t in DISCRETIONARY]


def hits(text, pats):
    low = (text or "").lower()
    return [t for t, p in pats if p.search(low)]


def insane_perf(perf):
    """Flag claims that smell like overfitting / cherry-picking."""
    p = (perf or "").lower()
    for n in re.findall(r'(\d[\d,\.]*)\s*%', p):
        try:
            if float(n.replace(",", "")) >= 100:
                return True
        except ValueError:
            pass
    return bool(re.search(r'\b\d+\s*x\b', p)) or "fold" in p


def family_of(low_all):
    if "crossover" in low_all and any(x in low_all for x in ("sma","ema","moving average")):
        return "ma_crossover"
    if "rsi" in low_all:                                   return "rsi"
    if "bollinger" in low_all:                             return "bollinger"
    if "macd" in low_all:                                  return "macd"
    if "gap" in low_all:                                   return "gap"
    if any(x in low_all for x in ("pairs","co-integration","cointegration","spread")):
        return "pairs_meanrev"
    if any(x in low_all for x in ("breakout","donchian","channel")):
        return "breakout"
    return "other_mechanical"


def classify(row):
    rules = " ".join([row.get("indicators",""), row.get("entry_rules",""),
                      row.get("exit_rules","")])
    blob = " ".join([row.get("strategy_name",""), rules,
                     row.get("asset_class",""), row.get("notes","")])
    low_all = blob.lower()

    if str(row.get("has_strategy","")).strip().lower() != "true":
        return False, "no_strategy", 0, ""

    tokens = {t.strip() for t in (row.get("approach","") or "").lower().split("|")}
    if KEEP_APPROACH not in tokens:
        return False, "not_rule_based", 0, ""
    if tokens & DROP_APPROACH_TOKENS:
        return False, "rule_based_but_mixed_with_ML", 0, ""

    if any(m in low_all for m in EXCLUDE_MARKET):
        return False, "prediction_market_or_sports", 0, ""
    if any(m in (row.get("asset_class","") or "").lower() for m in OPTIONS_MARKET):
        return False, "options_market", 0, ""

    if not is_concrete(row.get("entry_rules","")):
        return False, "no_concrete_entry", 0, ""
    if not is_concrete(row.get("exit_rules","")):
        return False, "no_concrete_exit", 0, ""

    mech = set(hits(rules, _MECH_PATS))
    disc = set(hits(rules, _DISC_PATS))

    if not mech and disc:
        return False, "pure_discretionary", 0, ""
    if not mech and not disc:
        return False, "no_nameable_indicator", 0, ""

    score = 4 + min(len(mech), 4) * 2 - min(len(disc), 3) * 3
    flags = []
    if disc:
        flags.append("partly_discretionary")
    if insane_perf(row.get("claimed_performance","")):
        flags.append("distrust_claimed_perf")
    if "buy and hold" in low_all or "buy-and-hold" in low_all:
        flags.append("trivial_buy_hold"); score -= 3

    return True, ("|".join(flags) if flags else "clean"), score, family_of(low_all)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out", default="to_translate_queue.csv")
    ap.add_argument("--dropped", default="dropped.csv")
    args = ap.parse_args()

    with open(args.csv, newline="", encoding="utf-8-sig", errors="replace") as f:
        rows = list(csv.DictReader(f))

    kept, dropped, counts = [], [], {}
    for r in rows:
        keep, reason, score, family = classify(r)
        if keep:
            kept.append({"score": score, "family": family, "flags": reason,
                "strategy_name": r.get("strategy_name",""),
                "asset_class": r.get("asset_class",""),
                "timeframe": r.get("timeframe",""),
                "indicators": r.get("indicators",""),
                "entry_rules": r.get("entry_rules",""),
                "exit_rules": r.get("exit_rules",""),
                "claimed_performance": r.get("claimed_performance",""),
                "url": r.get("url",""), "video_id": r.get("video_id","")})
        else:
            counts[reason] = counts.get(reason, 0) + 1
            dropped.append({"drop_reason": reason,
                "strategy_name": r.get("strategy_name",""),
                "approach": r.get("approach",""),
                "asset_class": r.get("asset_class",""),
                "entry_rules": r.get("entry_rules",""),
                "exit_rules": r.get("exit_rules",""), "url": r.get("url","")})

    kept.sort(key=lambda x: x["score"], reverse=True)

    if kept:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(kept[0].keys()))
            w.writeheader(); w.writerows(kept)
    with open(args.dropped, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["drop_reason","strategy_name",
            "approach","asset_class","entry_rules","exit_rules","url"])
        w.writeheader(); w.writerows(dropped)

    print(f"\nTotal rows read:     {len(rows)}")
    print(f"KEPT to translate:   {len(kept)}")
    print(f"Dropped:             {len(dropped)}\n")
    print("Why rows were dropped:")
    for reason, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>4}  {reason}")
    print(f"\nWrote {args.out} and {args.dropped}\n")
    print("Top of the queue (translate these first):")
    for k in kept[:15]:
        print(f"  [{k['score']:>2}] {k['family']:<15} {k['strategy_name'][:44]:<44} ({k['flags']})")


if __name__ == "__main__":
    main()
