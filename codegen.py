#!/usr/bin/env python3
"""
codegen.py  --  STAGE 5 of the pipeline: turn each filtered strategy (English) into
a runnable position function (Python), the HYBRID way.

For every row in to_translate_queue.csv:
  1. ROUTER (LLM, low temp): map the strategy onto ONE vetted family in
     strategy_templates.FAMILIES, with parameters -- or 'none'.
  2. TEMPLATE PATH: if a family matched, instantiate the vetted factory (safe).
  3. FREE-FORM FALLBACK: if 'none', ask the LLM to write a `def strat(df)` function.
  4. VALIDATION GAUNTLET (both paths, mandatory before a function is kept):
        - AST allowlist (free-form only): no imports/dunders/IO/eval/etc.
        - sandbox exec in a subprocess against a synthetic OHLC frame, with timeout
        - output contract: pd.Series aligned to df.index, values in {-1,0,1}, finite,
          non-trivial (it actually trades)

Outputs:
  generated_strats.py   importable: STRATS (single-ticker), MULTI (multi-ticker), META
  codegen_report.csv    per strategy: method (template/freeform/failed) + reason
  codegen_state.jsonl   resumable accumulator (one record per processed queue row)

RESUMABLE: skips video_ids already in codegen_state.jsonl.

    python codegen.py                 # process the whole queue
    python codegen.py --limit 8       # first 8 (handy for a test run)
    export ANTHROPIC_API_KEY=...  LLM_MODEL=claude-haiku-4-5
"""
import argparse, ast, csv, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd

from strategy_templates import FAMILIES, validate_params, build

QUEUE       = "to_translate_queue.csv"
OUT_PY      = "generated_strats.py"
OUT_REPORT  = "codegen_report.csv"
STATE       = "codegen_state.jsonl"
SANDBOX_TIMEOUT = 20          # seconds per candidate
PY = sys.executable           # whatever interpreter runs codegen runs the sandbox too

# default tickers when the router doesn't name them (multi-asset families)
DEFAULT_TICKERS = {"allocation": ["QQQ", "BND"]}


# --------------------------------------------------------------------------- #
# synthetic data + output contract (shared by template check and sandbox)
# --------------------------------------------------------------------------- #
def synth_df(n=600, seed=0):
    idx = pd.date_range("2018-01-01", periods=n, freq="D")
    rng = np.random.default_rng(seed)
    close = 100*np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    close = pd.Series(close, index=idx)
    high = close*(1 + np.abs(rng.normal(0, 0.005, n)))
    low  = close*(1 - np.abs(rng.normal(0, 0.005, n)))
    return pd.DataFrame({"Open": close.shift(1).fillna(close.iloc[0]),
                         "High": high, "Low": low, "Close": close,
                         "Volume": rng.integers(1e5, 1e7, n)}, index=idx)


def contract(out, df):
    """Return (ok, reason). The single position-series contract the engine needs."""
    if not isinstance(out, pd.Series):
        return False, f"not a Series (got {type(out).__name__})"
    if len(out) != len(df):
        return False, f"length {len(out)} != df length {len(df)}"
    filled = out.fillna(0)
    if not np.isfinite(filled.to_numpy(dtype="float64")).all():
        return False, "contains non-finite values"
    vals = set(np.unique(filled.to_numpy()))
    if not vals <= {-1.0, 0.0, 1.0}:
        bad = sorted(vals - {-1.0, 0.0, 1.0})[:5]
        return False, f"values outside {{-1,0,1}}: {bad}"
    if len(set(np.unique(filled.to_numpy()))) <= 1:
        return False, "trivial: position never changes"
    return True, "ok"


# --------------------------------------------------------------------------- #
# the gauntlet
# --------------------------------------------------------------------------- #
_BANNED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "getattr", "setattr",
    "delattr", "globals", "locals", "vars", "input", "breakpoint", "exit",
    "quit", "memoryview", "os", "sys", "subprocess", "socket", "shutil",
    "pathlib", "requests", "urllib", "importlib", "ctypes", "pickle", "marshal",
    "builtins", "__builtins__",
}

def check_ast(src):
    """AST allowlist for free-form code. Return (ok, reason)."""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return False, f"syntax error: {e}"
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if not any(f.name == "strat" for f in funcs):
        return False, "no `def strat(df)` defined"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return False, "imports are not allowed (np and pd are provided)"
        if isinstance(node, (ast.Name, ast.Attribute)):
            ident = node.id if isinstance(node, ast.Name) else node.attr
            if ident in _BANNED_NAMES:
                return False, f"banned name: {ident}"
            if ident.startswith("__") and ident.endswith("__"):
                return False, f"dunder access not allowed: {ident}"
    return True, "ok"


_RUNNER = r'''
import sys, numpy as np, pandas as pd
src = open(sys.argv[1], encoding="utf-8").read()
idx = pd.date_range("2018-01-01", periods=600, freq="D")
rng = np.random.default_rng(0)
close = pd.Series(100*np.exp(np.cumsum(rng.normal(0,0.012,600))), index=idx)
df = pd.DataFrame({"Open": close.shift(1).fillna(close.iloc[0]),
                   "High": close*1.005, "Low": close*0.995, "Close": close,
                   "Volume": 1_000_000}, index=idx)
SAFE = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
        for k in ("abs","min","max","range","len","float","int","bool","enumerate",
                  "zip","round","sum","list","dict","tuple","set","sorted","map",
                  "filter","print","isinstance","True","False","None")}
ns = {"np": np, "pd": pd, "__builtins__": SAFE}
try:
    exec(src, ns)
    out = ns["strat"](df)
    assert isinstance(out, pd.Series), "not a Series"
    assert len(out) == len(df), "length mismatch"
    filled = out.fillna(0)
    assert np.isfinite(filled.to_numpy(dtype="float64")).all(), "non-finite"
    vals = set(np.unique(filled.to_numpy()))
    assert vals <= {-1.0,0.0,1.0}, "values outside {-1,0,1}"
    assert len(vals) > 1, "trivial: never trades"
    print("OK")
except Exception as e:
    print("FAIL: " + repr(e))
'''

def run_in_sandbox(src):
    """Exec the free-form source in a locked-down subprocess. Return (ok, reason)."""
    with tempfile.TemporaryDirectory() as d:
        runner = os.path.join(d, "runner.py"); cand = os.path.join(d, "cand.py")
        open(runner, "w", encoding="utf-8").write(_RUNNER)
        open(cand, "w", encoding="utf-8").write(src)
        try:
            r = subprocess.run([PY, runner, cand], capture_output=True, text=True,
                               timeout=SANDBOX_TIMEOUT)
        except subprocess.TimeoutExpired:
            return False, f"sandbox timeout (>{SANDBOX_TIMEOUT}s)"
        out = (r.stdout or "").strip().splitlines()
        last = out[-1] if out else (r.stderr or "no output").strip()[:160]
        return (last == "OK"), last


def validate_freeform(src):
    ok, why = check_ast(src)
    if not ok:
        return False, f"ast: {why}"
    ok, why = run_in_sandbox(src)
    return ok, ("ok" if ok else f"sandbox: {why}")


def validate_template(name, params):
    """Instantiate a template and contract-check it in-process. Return (ok, reason)."""
    try:
        fn = build(name, params)
    except Exception as e:
        return False, f"build error: {e!r}"
    if FAMILIES[name].multi_asset:
        try:
            out = fn(synth_df(seed=1), synth_df(seed=2))
        except Exception as e:
            return False, f"run error: {e!r}"
        ok = bool(isinstance(out, pd.Series) and np.isfinite(out.fillna(0).to_numpy()).all())
        return ok, ("ok" if ok else "bad return series")
    try:
        out = fn(synth_df())
    except Exception as e:
        return False, f"run error: {e!r}"
    return contract(out, synth_df())


# --------------------------------------------------------------------------- #
# the LLM brains (router + free-form)
# --------------------------------------------------------------------------- #
def _catalog_text():
    lines = []
    for name, fam in FAMILIES.items():
        ps = ", ".join(f"{k}" for k in fam.params) or "(none)"
        tag = " [multi-asset: names 2 tickers]" if fam.multi_asset else ""
        lines.append(f"- {name}{tag}: {fam.desc}  params: {ps}")
    return "\n".join(lines)

ROUTER_SYS = (
 "You map ONE described trading strategy onto exactly one family from a fixed catalog, "
 "or 'none'. Return ONLY a JSON object, no prose, no markdown:\n"
 '{"family":"<name|none>","params":{...},"tickers":[],'
 '"direction":"long_flat|long_short|market_neutral|always_invested",'
 '"type":"trend-following|mean-reversion|breakout|allocation|stat-arb|momentum|other",'
 '"confidence":0.0,"reason":""}\n'
 "Rules: use the family's exact parameter names; omit any parameter you are unsure of "
 "(defaults apply). Pick 'none' only if NO family fits. For multi-asset families put the "
 "two tickers in `tickers` (risk asset then safe asset for allocation; the two legs for "
 "pairs). Catalog:\n")

FREEFORM_SYS = (
 "Write ONE Python function `def strat(df):` that returns a pandas Series of target "
 "positions (1=long, 0=flat, -1=short) aligned to df.index. df has daily-bar columns "
 "Open, High, Low, Close, Volume. numpy is available as np and pandas as pd -- do NOT "
 "import anything. No file, network, or system access. No look-ahead: at each bar use "
 "only data up to that bar (the backtester shifts positions by one bar). Encode the "
 "strategy's entry and exit rules. Return ONLY the function code -- no markdown fences, "
 "no prose.")

def _row_text(row):
    return (f"Strategy: {row.get('strategy_name','')}\n"
            f"Asset class: {row.get('asset_class','')}\n"
            f"Indicators: {row.get('indicators','')}\n"
            f"Entry: {row.get('entry_rules','')}\n"
            f"Exit: {row.get('exit_rules','')}\n"
            f"Timeframe: {row.get('timeframe','')}")

def _parse_json(s):
    import re
    s = s.strip()
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m: s = m.group(0)
    return json.loads(s)

def _strip_fences(s):
    s = s.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.lstrip().startswith("python"):
            s = s.lstrip()[6:]
    return s.strip().strip("`").strip()

def router(row):
    from llm import chat
    raw = chat(ROUTER_SYS + _catalog_text(), _row_text(row), max_tokens=400, temperature=0.0)
    return _parse_json(raw)

def freeform_codegen(row):
    from llm import chat
    return _strip_fences(chat(FREEFORM_SYS, _row_text(row), max_tokens=900, temperature=0.1))


# --------------------------------------------------------------------------- #
# ticker handling for multi-asset families
# --------------------------------------------------------------------------- #
def _clean_tickers(tickers):
    out = []
    for t in (tickers or []):
        t = str(t).upper().strip().split("/")[0].split("-")[0]
        if t.isalnum() and 1 <= len(t) <= 6:
            out.append(t)
    return out


# --------------------------------------------------------------------------- #
# process one queue row -> a state record
# --------------------------------------------------------------------------- #
def process_row(row):
    rec = {"video_id": row.get("video_id",""), "url": row.get("url",""),
           "strategy_name": row.get("strategy_name",""),
           "method": "failed", "family": None, "params": {}, "tickers": [],
           "direction": "long_flat", "type": "other", "source": "",
           "status": "rejected", "reason": ""}
    try:
        r = router(row)
    except Exception as e:
        rec["reason"] = f"router error: {type(e).__name__}: {str(e)[:120]}"
        return rec
    fam = (r.get("family") or "none").strip().lower()
    rec["direction"] = r.get("direction") or "long_flat"
    rec["type"] = r.get("type") or "other"

    if fam in FAMILIES:
        params = validate_params(fam, r.get("params", {}))
        ok, why = validate_template(fam, params)
        rec.update(family=fam, params=params)
        if not ok:
            rec["reason"] = f"template invalid: {why}"; return rec
        if FAMILIES[fam].multi_asset:
            tickers = _clean_tickers(r.get("tickers"))
            if len(tickers) < 2:
                tickers = DEFAULT_TICKERS.get(fam, [])
            if len(tickers) < 2:
                rec["reason"] = f"{fam} needs two tickers, router gave {r.get('tickers')}"
                return rec
            rec["tickers"] = tickers[:2]
        rec.update(method="template", status="accepted", reason="ok")
        return rec

    # free-form fallback
    try:
        src = freeform_codegen(row)
    except Exception as e:
        rec["reason"] = f"freeform error: {type(e).__name__}: {str(e)[:120]}"; return rec
    ok, why = validate_freeform(src)
    rec["source"] = src
    if not ok:
        rec["reason"] = why; return rec
    rec.update(method="freeform", status="accepted", reason="ok")
    return rec


# --------------------------------------------------------------------------- #
# emit generated_strats.py + codegen_report.csv from the state jsonl
# --------------------------------------------------------------------------- #
def _rename_strat(src, gid):
    tree = ast.parse(src)
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "strat":
            n.name = gid
    return ast.unparse(tree)

def emit(records):
    accepted = [r for r in records if r["status"] == "accepted"]
    # assign stable ids in jsonl order
    for i, r in enumerate(accepted, 1):
        r["gid"] = f"g{i:03d}"

    L = ['#!/usr/bin/env python3',
         '"""generated_strats.py  --  AUTO-GENERATED by codegen.py. DO NOT EDIT BY HAND.',
         'Position functions translated from to_translate_queue.csv via the hybrid',
         '(template-first, LLM-fallback) codegen step, each validated by the gauntlet.',
         'Single-ticker -> STRATS (df->position). Multi-ticker -> MULTI (returns series).',
         'Research tool, not financial advice."""',
         'import numpy as np, pandas as pd',
         'from strategy_templates import build',
         '']
    single, multi, meta = [], [], []
    for r in accepted:
        gid = r["gid"]; nm = r["strategy_name"].replace('"', "'")
        if r["method"] == "freeform":
            L.append(f"# {gid}  {nm}  (free-form)")
            L.append(_rename_strat(r["source"], gid)); L.append("")
            single.append(gid)
        elif FAMILIES[r["family"]].multi_asset:
            roles = FAMILIES[r["family"]].assets
            args = ", ".join(roles)
            L.append(f"# {gid}  {nm}  (template: {r['family']}, {r['tickers']})")
            L.append(f"_{gid} = build({r['family']!r}, {r['params']!r})")
            L.append(f"def {gid}({args}): return _{gid}({args})"); L.append("")
            multi.append(r)
        else:
            L.append(f"# {gid}  {nm}  (template: {r['family']})")
            L.append(f"_{gid} = build({r['family']!r}, {r['params']!r})")
            L.append(f"def {gid}(df): return _{gid}(df)"); L.append("")
            single.append(gid)
        meta.append(r)

    L.append("STRATS = {" + ", ".join(f'"{g}": {g}' for g in single) + "}")
    L.append("")
    L.append("MULTI = {")
    for r in multi:
        fam = FAMILIES[r["family"]]
        L.append(f'    "{r["gid"]}": {{"fn": {r["gid"]}, "tickers": {r["tickers"]!r}, '
                 f'"roles": {fam.assets!r}, "benchmark": {fam.benchmark!r}}},')
    L.append("}")
    L.append("")
    L.append("META = {")
    for r in meta:
        m = {"name": r["strategy_name"], "family": r["family"], "method": r["method"],
             "params": r["params"], "tickers": r["tickers"], "direction": r["direction"],
             "type": r["type"], "multi_asset": r["gid"] in [x["gid"] for x in multi],
             "video_id": r["video_id"], "url": r["url"]}
        L.append(f'    "{r["gid"]}": {m!r},')
    L.append("}")
    L.append("")
    with open(OUT_PY, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    with open(OUT_REPORT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["gid","strategy_name","method","family",
                            "tickers","status","reason","video_id","url"])
        w.writeheader()
        for r in records:
            w.writerow({"gid": r.get("gid",""), "strategy_name": r["strategy_name"],
                "method": r["method"], "family": r["family"] or "",
                "tickers": "/".join(r["tickers"]), "status": r["status"],
                "reason": r["reason"], "video_id": r["video_id"], "url": r["url"]})


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default=QUEUE)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    with open(args.queue, newline="", encoding="utf-8-sig", errors="replace") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[:args.limit]

    done = set()
    records = []
    if os.path.exists(STATE):
        for ln in open(STATE, encoding="utf-8"):
            try:
                rec = json.loads(ln); records.append(rec); done.add(rec["video_id"])
            except Exception:
                pass

    sf = open(STATE, "a", encoding="utf-8")
    for i, row in enumerate(rows, 1):
        vid = row.get("video_id","")
        if vid in done:
            continue
        rec = process_row(row)
        records.append(rec); done.add(vid)
        sf.write(json.dumps(rec, ensure_ascii=False) + "\n"); sf.flush()
        print(f"[{i}/{len(rows)}] {rec['strategy_name'][:42]:42s} "
              f"-> {rec['method']:8s} {rec.get('family') or '':16s} {rec['status']}"
              + ("" if rec["status"] == "accepted" else f"  ({rec['reason'][:60]})"))
    sf.close()

    emit(records)
    acc = [r for r in records if r["status"] == "accepted"]
    tpl = sum(1 for r in acc if r["method"] == "template")
    ff  = sum(1 for r in acc if r["method"] == "freeform")
    print(f"\nProcessed {len(records)} | accepted {len(acc)} "
          f"(template {tpl}, free-form {ff}) | rejected {len(records)-len(acc)}")
    print(f"  -> {OUT_PY}   (importable: STRATS, MULTI, META)")
    print(f"  -> {OUT_REPORT}  (per-strategy method + reason)")

if __name__ == "__main__":
    main()
