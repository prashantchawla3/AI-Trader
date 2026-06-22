# AI-Trader

An AI-assisted research pipeline for finding and validating trading strategies.
It scrapes trading-tutorial transcripts, extracts candidate strategies, filters
them down to the ones worth testing, and **backtests them honestly** (out-of-sample,
after costs) so only strategies with real evidence move forward.

This is a **research tool, not financial advice.** Nothing here is live trading.

---

## Guardrails (non-negotiable)

1. No strategy is considered "working" without a backtest on real historical data.
   "Sounds reasonable" is not a result — win rate, expectancy, and max drawdown are.
2. Out-of-sample is the bar. A strategy that only looks good in-sample is overfit.
3. Costs and slippage are charged on every test. No frictionless backtests.
4. Human review before anything is acted on. No unattended automation yet.

---

## Pipeline (current state)

The project runs in stages. Each stage is a standalone script.

| Stage | Script | What it does |
|-------|--------|--------------|
| 0 | `yt-transcriber.py`, `extract_transcripts.py` | Pull transcripts from trading tutorials |
| 1 | `01_build_rag.py` | Build a searchable index over the transcripts |
| 2 | `02_query_rag.py` | Query the transcript corpus |
| 3 | `03_extract_strategies.py` | Extract candidate strategies into `strategies.csv` |
| 4 | `filter_strategies.py` | Filter ~400 candidates to a mechanical, backtestable shortlist (`to_translate_queue.csv` + `dropped.csv`) |
| 5 | `04_backtest.py` + `catalog_strats.py` + `extras_backtest.py` | Backtest the shortlisted strategies honestly |

---

## Backtesting (Stage 5)

The catalog was narrowed to **12 distinct, fully-specified, mechanical strategies**
(deduplicated — e.g. the 15+ moving-average-crossover variants collapse to one).
Each has a concrete entry rule, exit rule, and indicator set. After backtesting,
**2 were dropped** (S05 gap and S09 overnight — both strongly negative
out-of-sample), leaving **10 active strategies**.

- `04_backtest.py` — the engine. A strategy is a function `df -> position series`
  (1 = long, 0 = flat, -1 = short). The engine handles next-bar execution,
  transaction costs, the in/out-of-sample split, and metrics vs buy-and-hold.
- `catalog_strats.py` — **8 strategies** as drop-in position functions.
  Wired in via `STRATS.update(catalog_strats.STRATS)`.
- `extras_backtest.py` — **the other 2** (allocation, pairs).
  These don't fit a single-ticker close-to-close position series (they need
  two tickers), so they run standalone.

### Run it

```bash
pip install yfinance pandas numpy

# the 8 drop-in strategies (one at a time)
py 04_backtest.py SPY s01
py 04_backtest.py SPY s02
py 04_backtest.py SPY s03
py 04_backtest.py SPY s04
py 04_backtest.py SPY s06
py 04_backtest.py SPY s07
py 04_backtest.py SPY s08
py 04_backtest.py SPY s10

# the other 2 (all at once)
py extras_backtest.py
```

### The 12 strategies

| ID  | Strategy | Type | Runs via |
|-----|----------|------|----------|
| S01 | RSI(10) mean-reversion + SMA200 filter | mean reversion | `04_backtest.py` |
| S02 | SMA 50/200 crossover (canonical MA-cross) | trend | `04_backtest.py` |
| S03 | MACD(12,26,9) signal crossover | momentum | `04_backtest.py` |
| S04 | Bollinger(20,2) + RSI(14) mean reversion | mean reversion | `04_backtest.py` |
| S05 | Gap-up: buy open, sell close | gap/intraday | **dropped** (failed OOS) |
| S06 | LSMA(25) cross | regression MR | `04_backtest.py` |
| S07 | Stoch-K(8) oversold + SMA200 buy-limit | mean reversion | `04_backtest.py` |
| S08 | LinReg(14) mean reversion + SMA200 (long/short) | mean reversion | `04_backtest.py` |
| S09 | Overnight drift: buy close, sell next open | calendar | **dropped** (failed OOS) |
| S10 | Donchian range breakout | breakout | `04_backtest.py` |
| S11 | QQQ/BND SMA30 regime allocation | allocation | `extras_backtest.py` |
| S12 | KO/PEP z-score pairs (market-neutral) | stat-arb | `extras_backtest.py` |

---

## Results so far (SPY, out-of-sample, after costs)

Tested on a single 60/40 in/out split. **None of the 12 beat SPY buy-and-hold on
raw return out-of-sample** — which is the expected, honest outcome for strategies
sourced from trading tutorials, and exactly why we backtest instead of trusting them.

- **Most consistent across windows:** S10 (breakout) and S11 (allocation) — both held
  up or improved out-of-sample, both with lower drawdown than buy-and-hold. The two
  worth pursuing.
- **Overfit signatures (good in-sample, fade out, or only-recent winners):** S04, S06, S08.
- **Dead:** S05 and S09 — strongly negative on SPY (their source edge was futures-specific).
- **Too few trades to judge on one ticker:** S01, S07 — need their proper multi-name
  universe before any verdict.
- **S12 pairs:** roughly flat, and not trustworthy until a cointegration (ADF /
  Engle-Granger) test confirms the KO/PEP spread is stationary.

### Known limitations of the current results

- Single ticker, single split point. A 60/40 split is fragile — results can swing on
  where the line falls. **Next step: walk-forward validation (multiple rolling splits).**
- S01 is built for a wide universe (hundreds of names); SPY-only undersells it.
- S10 here is the Donchian-channel form, not the take-profit/stop-loss version
  (the close-to-close engine can't model intrabar TP/SL fills).

---

## Next steps

- [ ] Walk-forward validation so S10 / S11 are tested across many splits, not one
- [ ] Run S01 across a proper multi-name universe
- [ ] ADF / cointegration test before trusting S12 pairs
- [ ] Log every backtest run (including rejects) to a results store

---

## Files

```
01_build_rag.py            stage 1: index transcripts
02_query_rag.py            stage 2: query the corpus
03_extract_strategies.py   stage 3: extract candidate strategies
04_backtest.py             stage 5: backtest engine
catalog_strats.py          8 of 12 strategies (drop-in position functions)
extras_backtest.py         the other 2 strategies, standalone (S11, S12)
filter_strategies.py       stage 4: filter candidates -> shortlist
strategies.csv             extracted strategy catalog (~400 rows)
to_translate_queue.csv     filter output: strategies kept for backtesting
dropped.csv                filter output: strategies cut (audit trail)
```