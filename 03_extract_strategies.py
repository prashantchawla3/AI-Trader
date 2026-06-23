#!/usr/bin/env python3
"""
03_extract_strategies.py  —  Turn each transcript into a STRUCTURED strategy
record, building a catalog you can filter, rank and dedupe.

For every transcripts/*.txt it asks the LLM to extract a JSON record, then
writes one row per video to strategies.csv (and raw JSON to strategies.jsonl).
RESUMABLE: skips videos already in strategies.jsonl.

    python 03_extract_strategies.py
    # cheap+fast batch model recommended:
    export ANTHROPIC_API_KEY=...   LLM_MODEL=claude-haiku-4-5

Setup:
    pip install anthropic   # (or openai), and llm.py beside this file
"""
import csv, glob, json, os, re
from llm import chat

TRANSCRIPT_DIR=os.environ.get("TRANSCRIPT_DIR","transcripts"); MANIFEST="manifest.csv"
OUT_JSONL="strategies.jsonl"; OUT_CSV="strategies.csv"
MAX_CHARS=24000  # trim very long transcripts to control token cost

FIELDS=["video_id","title","url","has_strategy","strategy_name","asset_class",
        "approach","model_or_method","indicators","entry_rules","exit_rules",
        "timeframe","claimed_performance","libraries","notes"]

SYSTEM=("You extract trading-strategy details from a tutorial transcript and "
 "return ONE JSON object only — no prose, no markdown. Use this exact schema:\n"
 '{"has_strategy": true/false, "strategy_name": "", "asset_class": "", '
 '"approach": "ML|rule-based|sentiment|deep-learning|RL|other", '
 '"model_or_method": "", "indicators": "", "entry_rules": "", "exit_rules": "", '
 '"timeframe": "", "claimed_performance": "", "libraries": "", "notes": ""}\n'
 "If the video does not actually describe a concrete strategy, set has_strategy "
 "to false and leave other fields empty. Keep each field short. Do NOT invent "
 "details that aren't in the transcript.")

def load_meta():
    meta={}
    if os.path.exists(MANIFEST):
        for r in csv.DictReader(open(MANIFEST,encoding="utf-8")):
            meta[r["video_id"]]={"title":r.get("title",""),"url":r.get("url","")}
    return meta

def parse_json(s):
    s=s.strip()
    m=re.search(r"\{.*\}", s, re.DOTALL)
    if m: s=m.group(0)
    return json.loads(s)

def main():
    meta=load_meta()
    files=glob.glob(os.path.join(TRANSCRIPT_DIR,"*.txt"))
    if not files: print("No transcripts found."); return

    done=set()
    if os.path.exists(OUT_JSONL):
        for ln in open(OUT_JSONL,encoding="utf-8"):
            try: done.add(json.loads(ln)["video_id"])
            except Exception: pass

    jf=open(OUT_JSONL,"a",encoding="utf-8")
    for i,fp in enumerate(files,1):
        vid=os.path.splitext(os.path.basename(fp))[0]
        if vid in done: continue
        text=open(fp,encoding="utf-8").read()[:MAX_CHARS]
        try:
            rec=parse_json(chat(SYSTEM, f"Transcript:\n\n{text}", max_tokens=700))
        except Exception as e:
            rec={"has_strategy":False,"notes":f"extraction_error: {type(e).__name__}"}
        m=meta.get(vid,{})
        rec["video_id"]=vid; rec["title"]=m.get("title",""); rec["url"]=m.get("url","")
        jf.write(json.dumps(rec,ensure_ascii=False)+"\n"); jf.flush()
        print(f"[{i}/{len(files)}] {vid}  strategy={rec.get('has_strategy')}")
    jf.close()

    # rebuild CSV from the full jsonl
    rows=[json.loads(l) for l in open(OUT_JSONL,encoding="utf-8")]
    with open(OUT_CSV,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k:r.get(k,"") for k in FIELDS})
    n=sum(1 for r in rows if r.get("has_strategy"))
    print(f"\nDone. {len(rows)} videos processed, {n} with concrete strategies.")
    print(f"Catalog: ./{OUT_CSV}  (raw: ./{OUT_JSONL})")

if __name__ == "__main__":
    main()
