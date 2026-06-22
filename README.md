# AI‑Trader — Turn Trading YouTube Tutorials into Searchable, Backtestable Research

> **Read this first if you are new.** This project does **not** trade for you and does **not** give financial advice. It is a *research pipeline*: it takes a big list of "AI / Machine‑Learning trading" YouTube videos, pulls out what each video actually says, makes all of it **searchable and question‑answerable**, summarizes each video's strategy into a neat table, and finally lets you **honestly test** a couple of those strategies on real historical price data to see if they would have actually made money.

> 📄 **Looking for the short version + results?** See **[OVERVIEW.md](OVERVIEW.md)** — a concise project summary with the pipeline guardrails, the 12 backtested strategies, and how they actually performed out‑of‑sample. This README is the long, beginner‑oriented walkthrough.

---

## Table of contents

1. [What problem does this solve?](#1-what-problem-does-this-solve)
2. [The big picture (how everything connects)](#2-the-big-picture-how-everything-connects)
3. [What's in this repo (every file explained)](#3-whats-in-this-repo-every-file-explained)
4. [Before you start (prerequisites)](#4-before-you-start-prerequisites)
5. [Step‑by‑step: running the main pipeline](#5-step-by-step-running-the-main-pipeline)
6. [The DaytradeWarrior sub‑project](#6-the-daytradewarrior-sub-project)
7. [How the pieces coordinate (data flow recap)](#7-how-the-pieces-coordinate-data-flow-recap)
8. [Configuration & environment variables](#8-configuration--environment-variables)
9. [Troubleshooting](#9-troubleshooting)
10. [Glossary for beginners](#10-glossary-for-beginners)
11. [Important disclaimer](#11-important-disclaimer)

---

## 1. What problem does this solve?

There are **thousands** of YouTube videos teaching "AI trading bots," "machine‑learning stock prediction," "RSI strategies," and so on. Watching them all is impossible, and most of the strategies sound great but were never tested honestly.

This project automates the whole research loop:

| Stage | Question it answers | Tool |
|------|----------------------|------|
| **Collect** | *"What did each video actually say?"* | Transcript extractor |
| **Search** | *"Which videos talk about X, and what's the consensus?"* | RAG (semantic search + AI answer) |
| **Catalog** | *"Give me a clean table of every strategy: indicators, entry/exit, timeframe."* | Strategy extractor |
| **Verify** | *"Does this strategy actually beat buy‑and‑hold after costs?"* | Backtester |

The output is a searchable knowledge base of ~1,200 trading videos plus a structured catalog of ~1,000 strategies — and a tool to reality‑check any of them.

---

## 2. The big picture (how everything connects)

```
                ai_trading_youtube_tutorials.xlsx   (your list of videos: title, URL, channel)
                              │
                              ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │  STAGE 0  extract_transcripts.py                                  │
   │  Downloads/transcribes each video → one .txt per video            │
   │  Outputs:  transcripts/*.txt   +   manifest.csv (status log)      │
   └─────────────────────────────────────────────────────────────────┘
                              │
            ┌─────────────────┴───────────────────┐
            ▼                                      ▼
 ┌─────────────────────────┐          ┌──────────────────────────────┐
 │ STAGE 1  01_build_rag.py│          │ STAGE 3  03_extract_strategies│
 │ Embeds chunks into a     │          │ Asks an LLM to summarize each │
 │ local vector database    │          │ video into structured JSON    │
 │ Output: vectordb/        │          │ Output: strategies.csv/.jsonl │
 └─────────────────────────┘          └──────────────────────────────┘
            │                                      │
            ▼                                      ▼
 ┌─────────────────────────┐          ┌──────────────────────────────┐
 │ STAGE 2  02_query_rag.py│          │ STAGE 4  04_backtest.py       │
 │ "Ask a question" → AI    │          │ Re‑implement a strategy and   │
 │ answer with citations    │          │ test it honestly on real data │
 └─────────────────────────┘          └──────────────────────────────┘

        (Stages 1–2 and 3–4 are two independent branches —
         both feed off the same transcripts.)
```

`llm.py` is a small shared helper that Stages 2 and 3 use to talk to whichever AI provider you choose (Anthropic, OpenAI, or a local Ollama model).

---

## 3. What's in this repo (every file explained)

### 🟦 The main pipeline (project root)

| File | What it is | What it does, line‑by‑line in plain English |
|------|-----------|----------------------------------------------|
| **`ai_trading_youtube_tutorials.xlsx`** | **Input data** (Excel) | The master list of videos. Sheet `YouTube Tutorials`, columns: `#, Title, URL, Channel, Category, Skill, Length, Free/Paid, Notes`. The pipeline reads the **URL** column to get each video's ID. |
| **`extract_transcripts.py`** | **Stage 0 — the collector** | Reads video URLs from the xlsx. For each video it tries **three methods in order**: (1) `youtube-transcript-api` (existing captions — fastest), (2) `yt-dlp` auto‑subtitles (fallback), (3) **Whisper** speech‑to‑text on the audio (only when no captions exist at all). Cleans the text (removes timestamps/tags), and writes **one `transcripts/<video_id>.txt` per video** plus a row in `manifest.csv`. It is **resumable** — re‑running skips videos already done, and it pauses 1–3 s between videos so YouTube doesn't block you. |
| **`yt-transcriber.py`** | Duplicate of Stage 0 | **Identical** to `extract_transcripts.py` (just an alternate filename). Use either one; you don't need both. |
| **`manifest.csv`** | **Generated index** | Status log written by Stage 0: `video_id, url, title, channel, status, source, chars`. `status` is `ok` or `no_transcript`; `source` tells you which method worked (`api`/`ytdlp`/`whisper`). Later stages use it for **citations** (mapping a transcript file back to its title & URL). In this repo it already lists ~1,200 videos (≈983 transcribed). |
| **`01_build_rag.py`** | **Stage 1 — build the search index** | Reads every `transcripts/*.txt`, splits each into overlapping 3,000‑character **chunks**, converts each chunk into a **vector (embedding)** using a *local, free* model (`BAAI/bge-small-en-v1.5` — downloads ~130 MB once, runs on CPU), and stores everything in a persistent **Chroma** vector database at `vectordb/`. Pulls titles/URLs from `manifest.csv` so each chunk knows where it came from. Re‑running rebuilds the index from scratch (safe). |
| **`02_query_rag.py`** | **Stage 2 — ask questions (RAG)** | **RAG = Retrieval‑Augmented Generation.** You type a question; it embeds your question, finds the 12 most relevant transcript chunks in `vectordb/`, and feeds *only those chunks* to an LLM (via `llm.py`) with strict instructions to answer **only from the excerpts and cite the video title** after each claim. Run it interactively or one‑shot: `python 02_query_rag.py "best RSI strategies"`. |
| **`03_extract_strategies.py`** | **Stage 3 — build the strategy catalog** | For every transcript it asks the LLM to return **one JSON object** describing the strategy (fields: `has_strategy, strategy_name, asset_class, approach, indicators, entry_rules, exit_rules, timeframe, claimed_performance, libraries, notes`). Writes raw JSON to `strategies.jsonl` and a tidy spreadsheet to `strategies.csv`. **Resumable** (skips videos already in the jsonl). A cheap/fast model like `claude-haiku-4-5` is recommended because it runs over ~1,000 videos. |
| **`strategies.jsonl`** | **Generated** | One raw JSON record per video (the source of truth, append‑only). |
| **`strategies.csv`** | **Generated** | The human‑friendly version of the catalog — open it in Excel/Sheets, filter `has_strategy = True`, sort by approach, etc. Already populated with ~1,000 rows. |
| **`filter_strategies.py`** | **Stage 3.5 — narrow the catalog** | Reads `strategies.csv` and writes a **ranked shortlist of only the strategies worth testing** — mechanical, rule‑based ones with a concrete entry *and* exit on a tradeable instrument. It deliberately does **not** translate English→code, does **not** judge if a strategy is "good" (the backtester does that), and **ignores `claimed_performance` for ranking** (that's the cherry‑pick trap). Outputs `to_translate_queue.csv` (kept) and `dropped.csv` (cut, as an audit trail). Run: `py filter_strategies.py strategies.csv`. |
| **`to_translate_queue.csv`** | **Generated** | The filter's "keep" list — strategies that passed and are worth hand‑coding into a backtest. |
| **`dropped.csv`** | **Generated** | The filter's "cut" list with a `drop_reason` for each — so nothing is silently discarded. |
| **`04_backtest.py`** | **Stage 4 — the reality check (engine)** | Takes a strategy idea and tests it *honestly* on 10 years of real price data (downloaded free via `yfinance`). It ships two worked examples: **RSI mean‑reversion** (`rsi`) and **SMA crossover** (`sma`). It applies **transaction costs**, trades on the *next* bar (no look‑ahead cheating), and splits the data into **in‑sample** (60%) vs **out‑of‑sample** (40%). It prints CAGR, Sharpe, Max Drawdown, and — crucially — compares the **out‑of‑sample** result to simple **buy‑and‑hold**. If a strategy only shines in‑sample, it's overfit. |
| **`catalog_strats.py`** | **Backtest add‑on** | **8 of the 12** narrowed strategies (S01–S10, the ones that fit a single‑ticker close‑to‑close position series), written as drop‑in functions for `04_backtest.py`. Wire them in with `STRATS.update(catalog_strats.STRATS)`, then run e.g. `py 04_backtest.py SPY s01`. |
| **`extras_backtest.py`** | **Backtest add‑on (standalone)** | **The other 4** strategies that *don't* fit the main engine — S05 gap (intraday open→close), S09 overnight (close→next‑open), S11 allocation (two tickers), S12 pairs (two tickers, market‑neutral). Same cost/split/stats conventions so the numbers are comparable. Run: `py extras_backtest.py`. |
| **`llm.py`** | **Shared helper** | A tiny wrapper so Stages 2 & 3 can call any AI provider with the same `chat(system, user)` function. Switch providers with the `LLM_PROVIDER` env var (`anthropic` default, `openai`, or `ollama` for fully local). Pick the model with `LLM_MODEL`. No other code changes needed. |
| **`OVERVIEW.md`** | Companion doc | The concise project summary: guardrails, the 12 backtested strategies, and their out‑of‑sample results. Good once you've read this guide. |

### 🟩 The `DaytradeWarrior/` sub‑project

A **self‑contained, focused variant** of the same idea, aimed at a single YouTube channel ("DaytradeWarrior"). It uses only `yt-dlp` (no Whisper) and a different, even‑smaller embedding model. It has its **own** transcripts and its **own** vector DB — see [section 6](#6-the-daytradewarrior-sub-project).

| File | Role |
|------|------|
| `DaytradeWarrior_Video_List.xlsx` | Input list (sheet `Video List`: `Title, URL, Video ID`). |
| `extract_transcripts.py` | Downloads English subtitles with `yt-dlp`, writes `transcripts/<id>.txt`, a combined `transcripts_combined.jsonl`, and a `transcript_progress.csv` log. Resumable. |
| `build_index.py` | Sentence‑aware chunking → embeds with `all-MiniLM-L6-v2` → stores in `chroma_db/`. |
| `search.py` | Quick semantic search from the command line; prints the top 6 matching snippets with a similarity score, title, and URL. |
| `transcripts/` | ~3,400 already‑extracted transcript text files (committed). |
| `transcript_progress.csv` | The resumable progress log. |
| `.gitignore` | Excludes the heavy generated stuff (`chroma_db/`, `transcripts_combined.jsonl`, `venv/`, `__pycache__/`). |

---

## 4. Before you start (prerequisites)

You need **Python 3.9+** and `pip`. There is no single `requirements.txt` — each stage installs only what it needs, so you can run just the parts you care about.

**Optional but recommended:** create a virtual environment first so packages stay isolated.

```bash
# from the project folder
python -m venv venv
# Windows (PowerShell):
venv\Scripts\Activate.ps1
# macOS / Linux:
source venv/bin/activate
```

**An AI provider** is needed for Stages 2 and 3 only. Cheapest options:
- **Anthropic** (default) — set `ANTHROPIC_API_KEY`. `pip install anthropic`
- **OpenAI** — set `OPENAI_API_KEY`. `pip install openai`
- **Ollama** (100% local, free) — install [Ollama](https://ollama.com), run a model like `llama3.1:8b`, set `LLM_PROVIDER=ollama`. No key needed.

Stages 0, 1, and 4 do **not** need an AI key (embeddings and backtests run locally).

---

## 5. Step‑by‑step: running the main pipeline

Run these from the project root. You can stop after any stage — each produces useful output on its own.

### Stage 0 — Get the transcripts

```bash
pip install youtube-transcript-api yt-dlp faster-whisper openpyxl
# (Whisper fallback also needs ffmpeg installed and on your PATH)

python extract_transcripts.py            # process all videos
python extract_transcripts.py --limit 10 # just the first 10 (good first test)
python extract_transcripts.py --no-whisper  # captions only, skip slow transcription
```
➡️ **Produces:** `transcripts/*.txt` and `manifest.csv`.
💡 Run this on your **normal home/office internet**, not a cloud server — YouTube blocks datacenter IPs for bulk caption downloads. If you get blocked, set a `PROXY` at the top of the script or increase `DELAY`.

> This repo already ships a populated `manifest.csv` (and the DaytradeWarrior transcripts). The root `transcripts/` folder is generated when you run this stage.

### Stage 1 — Build the searchable index

```bash
pip install chromadb sentence-transformers
python 01_build_rag.py
```
➡️ **Produces:** `vectordb/` (the Chroma vector database). First run downloads the embedding model (~130 MB) once.

### Stage 2 — Ask questions across all videos

```bash
pip install anthropic        # or: openai
export ANTHROPIC_API_KEY=...  # Windows PowerShell: $env:ANTHROPIC_API_KEY="..."

python 02_query_rag.py                         # interactive Q&A loop
python 02_query_rag.py "best RSI strategies"   # one-shot question
```
➡️ **Prints:** a synthesized answer with `[Video Title]` citations. Needs Stage 1 done first.

### Stage 3 — Build the structured strategy catalog

```bash
pip install anthropic        # or: openai
export ANTHROPIC_API_KEY=...
export LLM_MODEL=claude-haiku-4-5   # cheap + fast for batch work

python 03_extract_strategies.py
```
➡️ **Produces / updates:** `strategies.jsonl` and `strategies.csv`. Resumable — safe to stop and restart. Needs Stage 0 transcripts.

### Stage 4 — Backtest a strategy

```bash
pip install yfinance pandas numpy

python 04_backtest.py AAPL rsi   # RSI mean-reversion on Apple
python 04_backtest.py SPY sma    # SMA crossover on the S&P 500 ETF
```
➡️ **Prints** a metrics table. **The row that matters is `OUT-SAMPLE`** — and whether it beats `BUY&HOLD (OOS)` after costs. This stage is fully standalone (no AI key, no transcripts needed).

**Want to test your own strategy?** Add a function to `04_backtest.py` that takes the price DataFrame and returns a *position series* (`1` = long, `0` = flat, `-1` = short), then register it in the `STRATS` dictionary.

---

## 6. The DaytradeWarrior sub‑project

A smaller, single‑channel version of the pipeline. Run everything from inside the `DaytradeWarrior/` folder.

```bash
cd DaytradeWarrior
pip install yt-dlp openpyxl chromadb sentence-transformers

# 1) Extract transcripts (already shipped, but you can refresh/extend):
python extract_transcripts.py
python extract_transcripts.py --limit 50   # test on first 50
python extract_transcripts.py --sleep 2.0  # be gentler on YouTube

# 2) Build the vector index from transcripts_combined.jsonl:
python build_index.py        # → chroma_db/

# 3) Search semantically:
python search.py "morning gap and go setup"
```
➡️ `search.py` prints the top 6 matching transcript snippets with a similarity score, the video title, and its URL. It's a lightweight "find the moment a strategy is explained" tool — no LLM, no API key.

**How it differs from the main pipeline:** it uses `yt-dlp` only (no Whisper), a different embedding model (`all-MiniLM-L6-v2`), sentence‑aware chunking, and a separate database (`chroma_db/` instead of `vectordb/`). The two projects do not share data.

---

## 7. How the pieces coordinate (data flow recap)

- **`manifest.csv` is the glue** between Stage 0 and Stages 1–3: the transcript files are named by `video_id`, and the manifest maps each `video_id` back to its human title and URL so answers and the catalog can cite sources.
- **Stages 1→2 are one branch** (search & Q&A) and **Stages 3→4 are another** (catalog & verify). Both read the same `transcripts/`. You can run either branch independently.
- **`llm.py` is shared** by Stages 2 and 3 — change provider/model once via env vars and both stages follow.
- **`vectordb/` and `strategies.*` are generated artifacts.** Delete them anytime; re‑running the relevant stage rebuilds them.

---

## 8. Configuration & environment variables

| Variable | Used by | Default | Purpose |
|----------|---------|---------|---------|
| `ANTHROPIC_API_KEY` | Stages 2, 3 | — | Required if `LLM_PROVIDER=anthropic`. |
| `OPENAI_API_KEY` | Stages 2, 3 | — | Required if `LLM_PROVIDER=openai`. |
| `LLM_PROVIDER` | Stages 2, 3 | `anthropic` | `anthropic` \| `openai` \| `ollama`. |
| `LLM_MODEL` | Stages 2, 3 | per‑provider | e.g. `claude-haiku-4-5`, `gpt-4o-mini`, `llama3.1:8b`. |

**Tunable constants** (edit at the top of each script): `CHUNK_CHARS`/`CHUNK_OVERLAP` and `EMBED_MODEL` in `01_build_rag.py`; `TOP_K` in `02_query_rag.py`; `MAX_CHARS` in `03_extract_strategies.py`; `COST_BPS`/`TRAIN_FRAC` in `04_backtest.py`; `DELAY`/`WHISPER_MODEL`/`PROXY` in `extract_transcripts.py`.

---

## 9. Troubleshooting

| Symptom | Likely cause & fix |
|---------|--------------------|
| `No transcripts found` (Stage 1/3) | You haven't run Stage 0 yet, or the `transcripts/` folder is empty. Run `extract_transcripts.py` first. |
| Lots of `NO TRANSCRIPT` in the log | YouTube is blocking you (often on cloud/datacenter IPs). Run locally, set a `PROXY`, or raise `DELAY`. |
| Whisper step fails | `ffmpeg` isn't installed / not on PATH. Install it, or run with `--no-whisper`. |
| Stage 2/3 errors about API key | Set `ANTHROPIC_API_KEY` (or switch `LLM_PROVIDER`). For zero‑cost, use Ollama. |
| Embedding model download is slow | It downloads once (~130 MB), then is cached locally. |
| `04_backtest.py` says "no data" | Bad ticker symbol, or `yfinance` is rate‑limited — try again or a different ticker. |

---

## 10. Glossary for beginners

- **Transcript** — the spoken words of a video, as plain text.
- **Embedding / vector** — a list of numbers representing the *meaning* of a piece of text, so a computer can measure how similar two texts are.
- **Vector database (Chroma)** — storage that finds the most *meaning‑similar* chunks to your question, fast.
- **RAG (Retrieval‑Augmented Generation)** — find the relevant text first, then let an AI answer using only that text. Reduces made‑up answers and gives citations.
- **LLM** — Large Language Model (the AI that reads/writes text), e.g. Claude, GPT, Llama.
- **Backtest** — simulating a trading strategy on past data to estimate how it would have performed.
- **In‑sample vs out‑of‑sample** — data the strategy was tuned on vs. fresh data it never "saw." Only out‑of‑sample results are trustworthy.
- **Sharpe ratio** — return per unit of risk (higher is better). **Max Drawdown** — worst peak‑to‑trough loss. **CAGR** — annualized growth rate.
- **Look‑ahead bias** — accidentally using future information; the backtester avoids it by trading on the *next* bar.

---

## 11. Important disclaimer

This is a **research and educational tool**, not financial advice and not a trading bot. Strategies described in videos are *unverified claims* — the whole point of Stage 4 is to test them skeptically. Past performance never guarantees future results. Do your own research and never risk money you can't afford to lose.
