#!/usr/bin/env python3
"""
run_pipeline.py  --  "aiinit": the one command that runs the whole AI-Trader
research pipeline, from the YouTube video list to the agent strategy rules.

    S1 transcripts  extract_transcripts.py   xlsx video list -> transcripts/*.txt
    S2 clean        clean_transcripts.py      -> transcripts_clean/*.txt
    S3 extract      03_extract_strategies.py  -> strategies.csv / .jsonl
    S4 filter       filter_strategies.py      -> to_translate_queue.csv
   == GATE 1 (review the generated code) ==
    S5 codegen      codegen.py                -> generated_strats.py + codegen_report.csv
    S6 backtest     run_backtests.py          -> working_strategies.py + backtest_results.csv
   == GATE 2 (confirm the winners before they become rules) ==
    S7 rules        gen_rules.py              -> agent_strategies_rules.{json,md}

Each stage is SKIPPED if its output already exists (resumable). The two gates pause
for a human eyeball at the risky boundaries -- generated trading code, and the final
winner list -- before continuing.

    python run_pipeline.py                 # run everything, stopping at the gates
    python run_pipeline.py --yes           # auto-pass the gates (unattended)
    python run_pipeline.py --from codegen  # start at a stage (skip earlier ones)
    python run_pipeline.py --only backtest # run exactly one stage
    python run_pipeline.py --force         # re-run even stages whose output exists
    python run_pipeline.py --limit 20      # cap videos (S1) and strategies (S5)
    python run_pipeline.py --no-whisper    # captions only in S1 (skip Whisper)

Research tool, not financial advice. Nothing here is approved for live trading.
"""
import argparse, glob, os, subprocess, sys

PY = sys.executable

def has(pattern):                       # any file matching a glob exists
    return bool(glob.glob(pattern))

# id, human label, command, extra env, and a "done?" predicate for skip-if-exists.
def stages(args):
    return [
        dict(id="transcripts", label="S1 transcripts (YouTube -> text)",
             cmd=[PY, "extract_transcripts.py"]
                 + (["--limit", str(args.limit)] if args.limit else [])
                 + (["--no-whisper"] if args.no_whisper else []),
             env={}, done=lambda: has("transcripts/*.txt")),
        dict(id="clean", label="S2 clean transcripts",
             cmd=[PY, "clean_transcripts.py"],
             env={}, done=lambda: has("transcripts_clean/*.txt")),
        dict(id="extract", label="S3 extract strategies (LLM)",
             cmd=[PY, "03_extract_strategies.py"],
             env={"TRANSCRIPT_DIR": "transcripts_clean"},
             done=lambda: os.path.exists("strategies.csv")),
        dict(id="filter", label="S4 filter / rank",
             cmd=[PY, "filter_strategies.py", "strategies.csv"],
             env={}, done=lambda: os.path.exists("to_translate_queue.csv")),
        dict(id="codegen", label="S5 AI codegen (template + LLM, validated)",
             cmd=[PY, "codegen.py"] + (["--limit", str(args.limit)] if args.limit else []),
             env={}, done=lambda: os.path.exists("generated_strats.py"),
             gate="gate_codegen"),
        dict(id="backtest", label="S6 backtest grid",
             cmd=[PY, "run_backtests.py"],
             env={"STRAT_MODULE": "generated_strats"},
             done=lambda: os.path.exists("backtest_results.csv") and os.path.exists("working_strategies.py"),
             gate="gate_backtest"),
        dict(id="rules", label="S7 AI rules (agent hand-off)",
             cmd=[PY, "gen_rules.py"],
             env={}, done=lambda: os.path.exists("agent_strategies_rules.json")),
    ]

STAGE_IDS = ["transcripts","clean","extract","filter","codegen","backtest","rules"]


# --------------------------------------------------------------------------- #
# gates
# --------------------------------------------------------------------------- #
def gate_codegen():
    print("\n" + "#"*72 + "\n# GATE 1 - review the generated trading code\n" + "#"*72)
    try:
        import csv
        rows = list(csv.DictReader(open("codegen_report.csv", encoding="utf-8")))
        acc = [r for r in rows if r["status"] == "accepted"]
        tpl = sum(1 for r in acc if r["method"] == "template")
        ff  = sum(1 for r in acc if r["method"] == "freeform")
        print(f"  {len(acc)} accepted (template {tpl}, free-form {ff}), "
              f"{len(rows)-len(acc)} rejected.")
    except Exception as e:
        print(f"  (could not read codegen_report.csv: {e})")
    print("  Eyeball generated_strats.py (esp. free-form functions) before backtesting.")

def gate_backtest():
    print("\n" + "#"*72 + "\n# GATE 2 - confirm the winners before they become rules\n" + "#"*72)
    try:
        import importlib
        ws = importlib.import_module("working_strategies")
        importlib.reload(ws)
        print(f"  BEATS_BUYHOLD: {list(getattr(ws,'BEATS_BUYHOLD',{}))}")
        print(f"  ROBUST:        {list(getattr(ws,'ROBUST',{}))}")
        print(f"  -> {len(getattr(ws,'STRATS',{}))} survivor(s) will be written up as rules.")
    except Exception as e:
        print(f"  (could not read working_strategies.py: {e})")
    print("  See backtest_results.csv for the full evidence grid.")

GATES = {"gate_codegen": gate_codegen, "gate_backtest": gate_backtest}


def confirm(auto_yes):
    if auto_yes:
        print("  --yes: continuing automatically.\n"); return True
    try:
        ans = input("  Continue to the next stage? [y/N] ").strip().lower()
    except EOFError:
        ans = "n"
    print()
    return ans in ("y", "yes")


# --------------------------------------------------------------------------- #
def run_stage(st):
    env = dict(os.environ); env.update(st["env"])
    print(f"\n=== RUN {st['label']} ===")
    print("    $ " + " ".join(st["cmd"]))
    r = subprocess.run(st["cmd"], env=env)
    if r.returncode != 0:
        print(f"\n!! stage '{st['id']}' failed (exit {r.returncode}). Stopping.")
        sys.exit(r.returncode)


def main():
    ap = argparse.ArgumentParser(description="aiinit -- run the full strategy pipeline")
    ap.add_argument("--from", dest="start", choices=STAGE_IDS, help="start at this stage")
    ap.add_argument("--only", choices=STAGE_IDS, help="run exactly one stage")
    ap.add_argument("--force", action="store_true", help="re-run even if output exists")
    ap.add_argument("--yes", action="store_true", help="auto-pass the gates")
    ap.add_argument("--limit", type=int, default=0, help="cap videos (S1) and strategies (S5)")
    ap.add_argument("--no-whisper", action="store_true", help="captions only in S1")
    args = ap.parse_args()

    all_stages = stages(args)
    if args.only:
        selected = [s for s in all_stages if s["id"] == args.only]
        force_id = args.only                # an explicit --only always runs
    else:
        start_i = STAGE_IDS.index(args.start) if args.start else 0
        selected = [s for s in all_stages if STAGE_IDS.index(s["id"]) >= start_i]
        force_id = args.start               # --from forces only its START stage; later stages skip-if-done

    print("aiinit - AI-Trader pipeline")
    print("Stages:", " -> ".join(s["id"] for s in selected))

    for st in selected:
        run_it = args.force or st["id"] == force_id or not st["done"]()
        if run_it:
            run_stage(st)
        else:
            print(f"\n=== SKIP {st['label']}  (output exists; --force to re-run) ===")
        # a gate fires after its stage whether the stage ran or was skipped
        if st.get("gate") and not args.only:
            GATES[st["gate"]]()
            if not confirm(args.yes):
                print("Stopped at gate. Re-run `aiinit` (or `--from "
                      f"{STAGE_IDS[STAGE_IDS.index(st['id'])+1]}`) to resume.")
                return

    print("\n[done] Pipeline complete." if not args.only else "\n[done] Stage complete.")
    if any(s["id"] == "rules" for s in selected):
        print("  Agent rules: agent_strategies_rules.md / .json")
    print("  Research tool, not financial advice. V1 trades behind a human gate.")

if __name__ == "__main__":
    main()
