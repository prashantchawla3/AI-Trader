#!/usr/bin/env python3
"""
gen_rules.py  --  STAGE 7: turn the backtest survivors into the agent hand-off spec.

Reads:
  working_strategies.py   (which strategies survived + their tier registries)
  generated_strats.py      (META: family, params, tickers, direction, type per gid)
  backtest_results.csv     (the OOS evidence grid)

Writes (regenerated, never hand-edited):
  agent_strategies_rules.json   machine-readable spec the bot parses
  agent_strategies_rules.md     human-readable rendering of the same data

The execution model + guardrails are static boilerplate (copied verbatim from the
original hand-authored spec -- they are already correct). Per-strategy entries are
built deterministically from each family's parameters; free-form strategies get a
short LLM pass to describe their rules (skipped gracefully if no API key).

    python gen_rules.py
"""
import csv, json, os
# working_strategies / generated_strats are imported lazily inside build_spec(): they
# are produced by earlier stages and may not exist when this module is merely imported.

OUT_JSON = "agent_strategies_rules.json"
OUT_MD   = "agent_strategies_rules.md"

# --------------------------------------------------------------------------- #
# static boilerplate (verbatim from the hand-authored agent_strategies_rules.json)
# --------------------------------------------------------------------------- #
EXECUTION_MODEL = {
    "timeframe": "1D",
    "bar_note": "Crypto is 24/7; treat one bar as a fixed-UTC 24h candle.",
    "signal_timing": "Compute from data up to and including the just-closed bar.",
    "fill_timing": "next_bar",
    "fill_note": "Never act on the bar that produced the signal (no look-ahead). Research engine shifts the position series by 1 bar.",
    "cost_bps_per_trade": 5,
    "position_encoding": {"long": 1, "flat": 0, "short": -1},
    "pyramiding": False,
}
DEPLOYMENT_PROVENANCE = {
    "validated_on": "US equities (SPY, QQQ, AAPL, MSFT, GOOGL), daily bars, last 10y",
    "target": "Hyperliquid crypto perps",
    "requirements": [
        "Re-validate every strategy out-of-sample on the actual target symbol before live size (guardrail #1).",
        "Do not add a short leg that was not validated; approved strategies are long/flat, allocation, or market-neutral.",
        "Lookbacks are in bars, not calendar days; keep them in bars across markets.",
    ],
}
GLOBAL_GUARDRAILS = [
    "No strategy trades live without an out-of-sample backtest on the target symbol.",
    "Out-of-sample after costs is the bar; in-sample-only performance is ignored as overfit.",
    "Costs and slippage are charged on every test.",
    "V1 human approval gate: the agent proposes {symbol, side, target, size, strategy_id, reason}; a human approves before the order is sent.",
    "Kill switch and risk caps (per-trade max risk, max concurrent positions, daily-loss limit) must exist before live.",
]
STATUS_LEGEND = {
    "APPROVED_FOR_PAPER": "Cleared backtest; may run in paper/sim behind the human gate. Not auto-live.",
    "HOLD": "Do not deploy until the listed blocker is resolved.",
}
DISCLAIMER = ("Research tool, not financial advice. Nothing here is approved for live "
              "unattended trading. V1 requires a human approval gate.")


# --------------------------------------------------------------------------- #
# per-family -> structured indicators + rules (deterministic)
# --------------------------------------------------------------------------- #
def _ma(kind):
    return "EMA" if kind == "ema" else "SMA"

def describe(meta):
    """Return {type, direction, min_history_bars, indicators[], rules{}, notes} for one strategy."""
    fam, p = meta.get("family"), meta.get("params", {})
    typ, direction = meta.get("type", "other"), meta.get("direction", "long_flat")

    if fam == "ma_crossover":
        m = _ma(p["ma"])
        return dict(type="trend-following", direction="long_flat", min_history_bars=p["slow"],
            indicators=[{"key":"ma_fast","formula":f"{m}(close,{p['fast']})"},
                        {"key":"ma_slow","formula":f"{m}(close,{p['slow']})"}],
            rules={"entry_long":"ma_fast > ma_slow","exit_to_flat":"ma_fast <= ma_slow"},
            notes=f"{m} {p['fast']}/{p['slow']} crossover; low-turnover trend filter, whipsaws in choppy markets.")
    if fam == "rsi_meanrev":
        ind = [{"key":"rsi","formula":f"RSI(close,{p['rsi_n']})"}]
        entry = f"rsi < {p['lower']}"
        if p["sma_filter"]:
            ind.append({"key":"sma_trend","formula":f"SMA(close,{p['sma_filter']})"})
            entry = f"close > sma_trend AND rsi < {p['lower']}"
        ex = f"rsi > {p['upper']}" + (f" OR held >= {p['time_stop']} bars" if p["time_stop"] else "")
        return dict(type="mean-reversion", direction="long_flat",
            min_history_bars=max(p["rsi_n"], p["sma_filter"]),
            indicators=ind, rules={"entry_long":entry,"exit_to_flat":ex},
            notes="RSI dip-buy mean-reversion; lean on global risk caps in sustained downtrends.")
    if fam == "bollinger":
        return dict(type="mean-reversion", direction="long_flat",
            min_history_bars=max(p["n"], p["rsi_n"]),
            indicators=[{"key":"mid","formula":f"SMA(close,{p['n']})"},
                        {"key":"lower","formula":f"mid - {p['k']}*std(close,{p['n']})"},
                        {"key":"upper","formula":f"mid + {p['k']}*std(close,{p['n']})"},
                        {"key":"rsi","formula":f"RSI(close,{p['rsi_n']})"}],
            rules={"entry_long":f"close <= lower AND rsi < {p['rsi_lower']}",
                   "exit_to_flat":f"close >= upper AND rsi > {p['rsi_upper']}"
                                  + (f" OR held >= {p['time_stop']} bars" if p["time_stop"] else "")},
            notes="Bollinger-band reversion gated by RSI, with a time stop.")
    if fam == "macd":
        return dict(type="trend-following", direction="long_flat", min_history_bars=p["slow"],
            indicators=[{"key":"macd_line","formula":f"EMA(close,{p['fast']}) - EMA(close,{p['slow']})"},
                        {"key":"signal","formula":f"EMA(macd_line,{p['signal']})"}],
            rules={"entry_long":"macd_line > signal","exit_to_flat":"macd_line <= signal"},
            notes=f"MACD({p['fast']},{p['slow']},{p['signal']}) signal crossover.")
    if fam == "donchian_breakout":
        return dict(type="breakout", direction="long_flat", min_history_bars=p["entry_n"]+1,
            indicators=[{"key":"upper","formula":f"max(high, {p['entry_n']}) over previous {p['entry_n']} bars (shift 1)"},
                        {"key":"lower","formula":f"min(low, {p['exit_n']}) over previous {p['exit_n']} bars (shift 1)"}],
            rules={"entry_long":"position == 0 and close > upper",
                   "exit_to_flat":"position == 1 and close < lower"},
            notes=f"Donchian {p['entry_n']}/{p['exit_n']} channel breakout; typically the lowest-drawdown of the set.")
    if fam == "lsma_meanrev":
        return dict(type="mean-reversion", direction="long_flat", min_history_bars=p["n"],
            indicators=[{"key":"lsma","formula":f"LSMA(close,{p['n']}): OLS endpoint a+b*({p['n']-1}) over last {p['n']} closes"}],
            rules={"entry_long":"close < lsma","exit_to_flat":"close >= lsma"},
            notes="Long while price is below its least-squares regression line (counter-trend).")
    if fam == "linreg_mr":
        ind = [{"key":"lr","formula":f"LSMA(close,{p['n']}) regression endpoint"}]
        if p["sma_filter"]:
            ind.append({"key":"sma_trend","formula":f"SMA(close,{p['sma_filter']})"})
        return dict(type="mean-reversion", direction="long_short" if p["allow_short"] else "long_flat",
            min_history_bars=max(p["n"], p["sma_filter"]), indicators=ind,
            rules={"entry_long":"close < lr" + (" AND close > sma_trend" if p["sma_filter"] else ""),
                   "exit_long":"close > lr",
                   **({"entry_short":"close > lr AND close < sma_trend","exit_short":"close < lr"} if p["allow_short"] else {})},
            notes="Linear-regression mean-reversion around the trend filter.")
    if fam == "stochastic":
        ind = [{"key":"stoch_k","formula":f"100*(close-min(low,{p['k_n']}))/(max(high,{p['k_n']})-min(low,{p['k_n']}))"}]
        entry = f"stoch_k < {p['lower']}"
        if p["sma_filter"]:
            ind.append({"key":"sma_trend","formula":f"SMA(close,{p['sma_filter']})"})
            entry = f"close > sma_trend AND stoch_k < {p['lower']}"
        return dict(type="mean-reversion", direction="long_flat",
            min_history_bars=max(p["k_n"], p["sma_filter"]), indicators=ind,
            rules={"entry_long":entry,
                   "exit_to_flat":f"stoch_k > {p['upper']}" + (f" OR held >= {p['time_stop']} bars" if p["time_stop"] else "")},
            notes="Stochastic-%K oversold reversion with a trend filter and time stop.")
    if fam == "allocation":
        return dict(type="allocation", direction="always_invested", min_history_bars=p["sma_n"],
            indicators=[{"key":"sma","formula":f"SMA(risk_close,{p['sma_n']})"}],
            rules={"risk_on":f"risk_close > sma -> {int(p['on_risk_w']*100)}% risk / {int((1-p['on_risk_w'])*100)}% safe",
                   "risk_off":f"risk_close <= sma -> {int(p['off_risk_w']*100)}% risk / {int((1-p['off_risk_w'])*100)}% safe"},
            notes="Two-asset regime allocation. Re-validate the SMA regime and weights on the chosen crypto pair.")
    if fam == "pairs":
        return dict(type="stat-arb", direction="market_neutral", min_history_bars=p["lookback"],
            indicators=[{"key":"beta","formula":f"rolling_cov(a,b,{p['lookback']})/rolling_var(b,{p['lookback']})"},
                        {"key":"spread","formula":"a_close - beta*b_close"},
                        {"key":"z","formula":f"(spread - mean(spread,{p['lookback']}))/std(spread,{p['lookback']})"}],
            rules={"long_spread":f"z < -{p['z_in']} (long a / short b)",
                   "short_spread":f"z > {p['z_in']} (short a / long b)",
                   "exit_to_flat":f"abs(z) < {p['z_out']}"},
            notes="Z-score pairs trade; meaningless unless the spread is cointegrated.")

    # free-form (no family): structured fields unknown -> optional LLM prose
    return _describe_freeform(meta)

def _describe_freeform(meta):
    base = dict(type=meta.get("type","other"), direction=meta.get("direction","long_flat"),
                min_history_bars=0, indicators=[],
                rules={"summary":"See the validated function in generated_strats.py."},
                notes="Free-form strategy generated by the LLM and validated by the codegen gauntlet.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return base
    try:
        from llm import chat
        import inspect, generated_strats as gs
        gid = meta["_gid"]
        src = inspect.getsource(getattr(gs, gid))
        sysmsg = ("Describe this trading position function in JSON only: "
                  '{"indicators":[{"key":"","formula":""}],'
                  '"rules":{"entry_long":"","exit_to_flat":""},"notes":""}. '
                  "Keep formulas symbolic and short. No prose outside JSON.")
        import re
        raw = chat(sysmsg, f"Strategy '{meta['name']}':\n\n{src}", max_tokens=400, temperature=0.0)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            d = json.loads(m.group(0))
            base.update({k: d[k] for k in ("indicators","rules","notes") if k in d})
    except Exception:
        pass
    return base


# --------------------------------------------------------------------------- #
def load_evidence():
    ev = {}
    if not os.path.exists("backtest_results.csv"):
        return ev
    rows = list(csv.DictReader(open("backtest_results.csv", encoding="utf-8")))
    by = {}
    for r in rows:
        by.setdefault(r["strat"], []).append(r)
    for key, rs in by.items():
        tot = [float(r["oos_total"]) for r in rs]
        sh  = [float(r["oos_sharpe"]) for r in rs]
        dd  = [float(r["oos_maxdd"]) for r in rs]
        pos = sum(1 for t in tot if t > 0)
        beats = sum(1 for r in rs if str(r["beats_return"]).lower() == "true")
        if len(rs) == 1:
            ev[key] = {"sharpe": round(sh[0],2), "return": round(tot[0],3),
                       "maxdd": round(dd[0],3)}
        else:
            ev[key] = {"sharpe_avg": round(sum(sh)/len(sh),2),
                       "return_avg": round(sum(tot)/len(tot),3),
                       "maxdd_avg": round(sum(dd)/len(dd),3),
                       "positive": f"{pos}/{len(rs)}", "beats_buyhold": f"{beats}/{len(rs)}"}
    return ev


def build_spec():
    import working_strategies as ws, generated_strats as gs
    ev = load_evidence()
    survivors = list(ws.STRATS.keys())          # everything that survived either tier
    robust = set(getattr(ws, "ROBUST", {}).keys())
    beats  = set(getattr(ws, "BEATS_BUYHOLD", {}).keys())

    strategies = []
    for gid in survivors:
        meta = dict(gs.META.get(gid, {})); meta["_gid"] = gid
        d = describe(meta)
        is_pairs = meta.get("family") == "pairs"
        tiers = [t for t, s in (("BEATS_BUYHOLD", beats), ("ROBUST", robust)) if gid in s]
        entry = {
            "id": gid.upper(),
            "name": meta.get("name", gid),
            "type": d["type"],
            "direction": d["direction"],
            "status": "HOLD" if is_pairs else "APPROVED_FOR_PAPER",
            "timeframe": "1D",
            "min_history_bars": d["min_history_bars"],
            "family": meta.get("family"),
            "method": meta.get("method"),
            "parameters": meta.get("params", {}),
            "indicators": d["indicators"],
            "rules": d["rules"],
            "evidence_oos": ev.get(gid, {}),
            "tier": " + ".join(tiers),
            "source": {"video_id": meta.get("video_id",""), "url": meta.get("url","")},
            "notes": d["notes"],
        }
        if meta.get("multi_asset"):
            entry["multi_asset"] = True
            entry["assets"] = dict(zip(gs.MULTI[gid]["roles"], gs.MULTI[gid]["tickers"]))
            entry["code_location"] = "generated_strats.py (MULTI)"
        if is_pairs:
            entry["blocker"] = ("Run an ADF / Engle-Granger cointegration test on the spread first. "
                                "If it is not stationary, discard. Do not trade until this passes.")
        strategies.append(entry)

    return {
        "version": "2.0",
        "generated": "auto",
        "source": "AI-Trader Stage 6 backtest. Code of record: generated_strats.py / strategy_templates.py. Evidence: backtest_results.csv.",
        "disclaimer": DISCLAIMER,
        "execution_model": EXECUTION_MODEL,
        "deployment_provenance": DEPLOYMENT_PROVENANCE,
        "global_guardrails": GLOBAL_GUARDRAILS,
        "status_legend": STATUS_LEGEND,
        "strategies": strategies,
    }


# --------------------------------------------------------------------------- #
def render_md(spec):
    L = ["# Agent Strategy Rules", "",
         "**Hand-off spec for the bot/agent developer.** Auto-generated from the Stage-6",
         "backtest survivors. Source of truth (code): `generated_strats.py` /",
         "`strategy_templates.py`. Evidence: `backtest_results.csv`.", "",
         f"> ⚠️ {spec['disclaimer']}", "",
         "## Execution model", ""]
    em = spec["execution_model"]
    L += [f"- **Timeframe:** {em['timeframe']} ({em['bar_note']})",
          f"- **Signal timing:** {em['signal_timing']}",
          f"- **Fill timing:** {em['fill_timing']} — {em['fill_note']}",
          f"- **Costs:** {em['cost_bps_per_trade']} bps per trade. Position encoding "
          f"{em['position_encoding']}. Pyramiding: {em['pyramiding']}.", "",
          "## Global guardrails (non-negotiable)", ""]
    L += [f"{i}. {g}" for i, g in enumerate(spec["global_guardrails"], 1)]
    L += ["", "### Validation provenance", "",
          f"- Validated on: {spec['deployment_provenance']['validated_on']}; target: "
          f"{spec['deployment_provenance']['target']}."]
    L += [f"- {r}" for r in spec["deployment_provenance"]["requirements"]]
    L += ["", "## Strategies", ""]
    for s in spec["strategies"]:
        L.append(f"### {s['id']} — {s['name']}  *({s['type']}, {s['direction']})*")
        L.append(f"**Status:** `{s['status']}`  ·  family `{s['family']}`  ·  method `{s['method']}`"
                 + (f"  ·  tier {s['tier']}" if s.get("tier") else ""))
        if s.get("multi_asset"):
            L.append(f"**Assets:** {s['assets']}  (code: {s['code_location']})")
        if s["indicators"]:
            L.append("\n**Indicators**")
            L += [f"- `{i['key']}` = {i['formula']}" for i in s["indicators"]]
        L.append("\n**Rules**")
        L += [f"- **{k}:** {v}" for k, v in s["rules"].items()]
        if s["parameters"]:
            L.append(f"\n**Parameters:** `{s['parameters']}`")
        if s["evidence_oos"]:
            L.append(f"\n**Evidence (OOS, after costs):** {s['evidence_oos']}")
        if s.get("blocker"):
            L.append(f"\n**⚠️ Blocker:** {s['blocker']}")
        L.append(f"\n**Notes:** {s['notes']}")
        L.append(f"\n*Source video:* {s['source']['url']}")
        L.append("\n---\n")
    L += ["## Quick reference", "",
          "| ID | Name | Type | Direction | Status |",
          "|----|------|------|-----------|--------|"]
    for s in spec["strategies"]:
        L.append(f"| {s['id']} | {s['name']} | {s['type']} | {s['direction']} | {s['status']} |")
    return "\n".join(L) + "\n"


def main():
    spec = build_spec()
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(render_md(spec))
    print(f"Wrote {OUT_JSON} and {OUT_MD}: {len(spec['strategies'])} strategies "
          f"({sum(1 for s in spec['strategies'] if s['status']=='APPROVED_FOR_PAPER')} approved-for-paper, "
          f"{sum(1 for s in spec['strategies'] if s['status']=='HOLD')} on hold).")

if __name__ == "__main__":
    main()
