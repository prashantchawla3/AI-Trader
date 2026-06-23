#!/usr/bin/env python3
"""
clean_transcripts.py  --  STAGE 2: cheap, rule-based transcript cleaning.

Auto-captions are noisy: stuttered repeats ("the the the"), and YouTuber filler /
CTAs ("smash that like button", "link in the description") that waste extraction
tokens and add no strategy content. This collapses repeats and strips common filler,
writing a parallel transcripts_clean/ directory that Stage 3 reads from.

No LLM, no network -- just regex. Conservative on purpose: it only removes
boilerplate it is confident about, so real strategy talk is never dropped.
RESUMABLE: skips files already cleaned (unless --force).

    python clean_transcripts.py
    python clean_transcripts.py --src transcripts --dst transcripts_clean
"""
import argparse, glob, os, re

SRC = "transcripts"
DST = "transcripts_clean"

# CTA / sponsor / housekeeping fragments to delete (case-insensitive substrings).
FILLER = [
    r"smash (that|the) like button", r"hit the like button", r"like and subscribe",
    r"don'?t forget to subscribe", r"subscribe to (the|my) channel", r"hit the bell",
    r"turn on (the |post )?notifications", r"ring the bell",
    r"link(s)? (in|down) the description", r"link in the bio", r"check the description",
    r"join (my|our|the) discord", r"join (my|our) patreon", r"link to my discord",
    r"use (promo |discount )?code \w+", r"promo code", r"coupon code",
    r"sign up (using|with) (my|the) link", r"affiliate link",
    r"smash that subscribe", r"give this video a like", r"hit that subscribe button",
    r"comment (down )?below", r"let me know in the comments",
]
_FILLER_RE = re.compile("|".join(f"(?:{p})" for p in FILLER), re.IGNORECASE)


def collapse_repeats(text):
    """Collapse immediate word/short-phrase repeats from auto-caption stutter."""
    text = re.sub(r"\b(\w+)(\s+\1\b){1,}", r"\1", text, flags=re.IGNORECASE)   # "the the the" -> "the"
    text = re.sub(r"\b(\w+\s+\w+)(\s+\1\b){1,}", r"\1", text, flags=re.IGNORECASE)  # "i think i think" -> "i think"
    return text


def clean_text(text):
    text = collapse_repeats(text)
    text = _FILLER_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--dst", default=DST)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.dst, exist_ok=True)
    files = glob.glob(os.path.join(args.src, "*.txt"))
    if not files:
        print(f"No transcripts in {args.src}/"); return

    n_done = n_new = 0
    saved_chars = 0
    for fp in files:
        out = os.path.join(args.dst, os.path.basename(fp))
        if os.path.exists(out) and not args.force:
            n_done += 1; continue
        raw = open(fp, encoding="utf-8", errors="replace").read()
        cleaned = clean_text(raw)
        open(out, "w", encoding="utf-8").write(cleaned)
        saved_chars += max(0, len(raw) - len(cleaned))
        n_new += 1

    print(f"Cleaned {n_new} new, skipped {n_done} existing -> {args.dst}/  "
          f"(~{saved_chars:,} chars trimmed)")

if __name__ == "__main__":
    main()
