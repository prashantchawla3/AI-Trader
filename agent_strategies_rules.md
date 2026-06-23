# Agent Strategy Rules

**Hand-off spec for the bot/agent developer.** These are the trading strategies
that survived honest out-of-sample backtesting (Stage 5 of the pipeline). Each is
written here as explicit, unambiguous rules so the agent can implement them without
re-reading the research code.

- **Source of truth (code):** [working_strategies.py](working_strategies.py) — the exact position functions.
- **Evidence:** [backtest_results.csv](backtest_results.csv) — full per-ticker grid.
- **Machine-readable version of this doc:** [agent_strategies_rules.json](agent_strategies_rules.json) — parse this in the bot.
- **How they were chosen:** [OVERVIEW.md](OVERVIEW.md) + `run_backtests.py`.

> ⚠️ **This is a research tool, not financial advice. Nothing here is approved for
> live, unattended trading.** V1 runs behind a mandatory human approval gate.

---

## 0. How to read these rules (execution model)

Every strategy below is a function of price bars that outputs a **target position**:
`+1 = long`, `0 = flat`, `-1 = short`. The agent's job is to move the account toward
that target. The backtest that validated these used this exact model — match it:

| Aspect | Rule |
|--------|------|
| **Bar / timeframe** | Daily bars (`1D`). One bar = one decision. (Crypto is 24/7, so a "day" is a 24h candle — pick a fixed UTC close.) |
| **Signal timing** | Compute the signal from data **up to and including the just-closed bar**. |
| **Fill timing** | Act on the **next bar** — never on the bar that produced the signal (no look-ahead). The research engine enforces this by shifting the position series by 1 bar. |
| **Costs** | Assume **5 bps per trade** (per change in position). Real Hyperliquid fees + slippage must be modelled before any size goes live. |
| **One signal → one position** per symbol. No pyramiding/averaging unless a rule says so (none here do). |

### Validation provenance (read this before deploying)
These edges were measured on **US equities (SPY, QQQ, AAPL, MSFT, GOOGL) on daily bars,
2015–2025**. The bot targets **Hyperliquid crypto perps**. Therefore:

1. **Re-validate every strategy on the actual target symbols** (BTC, ETH, etc.) before it trades real size. An equity edge is a *hypothesis* on crypto, not a result. This is guardrail #1.
2. Strategies here are **long/flat** (or market-neutral / allocation). Crypto perps allow native shorts, but **do not add a short leg that wasn't validated** — the backtest didn't test it.
3. Lookback lengths are in **bars**, not calendar days. Keep them in bars when you switch markets.

---

## 1. Global guardrails (the agent must enforce these)

These are non-negotiable and sit *outside* any individual strategy:

1. **No strategy trades live without an out-of-sample backtest on the target symbol.** "Looks reasonable" is not a result.
2. **Out-of-sample, after costs, is the bar.** In-sample-only performance is overfit and ignored.
3. **Costs and slippage are charged on every test.** No frictionless assumptions.
4. **Human approval gate (V1).** The agent *proposes* a trade (symbol, side, size, reason, strategy id); a human approves before anything is sent to the exchange. No unattended execution in V1.
5. **Kill switch + risk caps.** Per-trade max risk, max concurrent positions, and a global daily-loss kill switch must exist before live. (Values are a deployment decision — not set by the backtest.)

---

## 2. Approved strategies (passed the standalone-robust bar)

"Robust" = positive out-of-sample net return on **every** tested ticker **and** mean
OOS Sharpe ≥ 0.65, after costs. None of these beat a 2015–2025 buy-and-hold (almost
nothing does), but each stands on its own — which is what matters for an active agent.

> **Status legend:** `APPROVED_FOR_PAPER` = cleared backtest, may run in paper/sim and
> behind the human gate; **not** auto-live. `HOLD` = do not deploy yet.

---

### S02 — SMA 50/200 Crossover  *(trend-following, long/flat)*
**Status:** `APPROVED_FOR_PAPER`

**Indicators**
- `sma_fast = SMA(close, 50)` — 50-bar simple moving average
- `sma_slow = SMA(close, 200)` — 200-bar simple moving average

**Rules**
- **Entry (→ long):** when `sma_fast > sma_slow` (the classic "golden cross" regime).
- **Exit (→ flat):** when `sma_fast <= sma_slow` ("death cross").
- Long-only. Position is simply `1 if sma_fast > sma_slow else 0`.

**Evidence (OOS, after costs):** positive 5/5 tickers · avg Sharpe **0.80** · avg return 75.7% · avg MaxDD −25.1% · beats buy&hold 0/5.

**Notes:** Slow, low-turnover trend filter. Whipsaws in choppy/range markets (hence the −25% drawdown). Needs ≥200 bars of history before it produces a signal.

```
if SMA(close,50) > SMA(close,200):  target = +1   # long
else:                               target =  0   # flat
```

---

### S06 — LSMA(25) Mean-Reversion  *(mean-reversion, long/flat)*
**Status:** `APPROVED_FOR_PAPER`

**Indicators**
- `lsma25 = LSMA(close, 25)` — **least-squares moving average**: fit an OLS line `y = a + b·x` over the last 25 closes (`x = 0..24`) and take the line's **endpoint** value `a + b·24`. (This is the linear-regression "value now", aka the regression trendline.)

**Rules**
- **Entry (→ long):** when `close < lsma25` — price has dipped below its own regression trendline (buy the dip).
- **Exit (→ flat):** when `close >= lsma25` — price has reverted back to/above the line.
- Long-only. Position is `1 if close < lsma25 else 0`.

**Evidence (OOS, after costs):** positive 5/5 · avg Sharpe **0.78** · avg return 62.2% · avg MaxDD −22.5% · beats buy&hold 0/5.

**Notes:** Counter-trend. Because it goes long *whenever* price is below the line, it can stay long through a sustained downtrend — pair it with the global risk caps / kill switch. Higher turnover than S02.

```
lsma = ols_endpoint(close[-25:])     # a + b*24 from polyfit(x=0..24, close, 1)
if close < lsma:  target = +1
else:             target =  0
```

---

### S10 — Donchian Channel Breakout  *(breakout, long/flat)*  ⭐ lowest drawdown
**Status:** `APPROVED_FOR_PAPER`

**Indicators**
- `upper = max(high, 20)` over the **previous** 20 bars (exclude the current bar — shift by 1).
- `lower = min(low, 10)` over the **previous** 10 bars (exclude the current bar — shift by 1).

**Rules**
- **Entry (→ long):** when `close > upper` — a fresh 20-bar high breakout.
- **Exit (→ flat):** when `close < lower` — price breaks the 10-bar low.
- Long-only.

**Parameters:** `entry_lookback = 20`, `exit_lookback = 10`.

**Evidence (OOS, after costs):** positive 5/5 · avg Sharpe **0.66** · avg return 38.4% · avg MaxDD **−20.0% (best of the set)** · beats buy&hold 0/5.

**Notes:** The OVERVIEW's pick for robustness + drawdown control. The original catalog version used an explicit take-profit/stop-loss; this is the channel form (the close-to-close engine can't model intrabar TP/SL — flagged). If the bot has intrabar fills, the TP/SL variant is worth re-testing.

```
upper = max(high[-21:-1])   # previous 20 bars
lower = min(low[-11:-1])    # previous 10 bars
if position == 0 and close > upper:  target = +1
elif position == +1 and close < lower: target = 0
```

---

### S11 — QQQ/BND Regime Allocation  *(2-asset allocation, always invested)*
**Status:** `APPROVED_FOR_PAPER` · **multi-asset** — defined in [extras_backtest.py](extras_backtest.py), not a single-symbol position function.

**Indicators**
- `sma30 = SMA(QQQ_close, 30)` — 30-bar SMA of the **risk asset** (QQQ).

**Rules** (rebalanced daily; cost charged on weight changes)
- **Risk-on:** when `QQQ_close > sma30` → **80% risk asset / 20% safe asset** (QQQ/BND).
- **Risk-off:** when `QQQ_close <= sma30` → **20% risk asset / 80% safe asset**.

**Evidence (OOS, after costs):** Sharpe **1.20** (highest in the set) · return 79.1% · MaxDD −19.4%. Benchmark is 100% QQQ buy&hold (173%), which it trails on raw return but with far less risk.

**Crypto mapping for the bot:** "risk asset" ≈ BTC/ETH, "safe asset" ≈ a stablecoin (USDC) or cash. **Re-validate the SMA30 regime on the chosen crypto pair before use** — the 80/20 split and 30-bar lookback are equity-tuned.

```
if QQQ_close > SMA(QQQ_close, 30):  weights = {risk: 0.80, safe: 0.20}
else:                               weights = {risk: 0.20, safe: 0.80}
```

---

## 3. On hold — do NOT deploy yet

### S12 — KO/PEP z-score Pairs  *(market-neutral stat-arb)*
**Status:** `HOLD — pending cointegration test`

**Indicators** (lookback `L = 252` bars)
- `beta = rolling_cov(KO, PEP, L) / rolling_var(PEP, L)`
- `spread = KO_close − beta · PEP_close`
- `z = (spread − rolling_mean(spread, L)) / rolling_std(spread, L)`

**Rules**
- **Long the spread** (long KO / short PEP) when `z < −2.0`.
- **Short the spread** (short KO / long PEP) when `z > +2.0`.
- **Exit to flat** when `|z| < 0.5`.

**Evidence (OOS, after costs):** Sharpe **0.22** · return 5.5% · MaxDD −14.8%. It nominally "beat" its cash benchmark only because it's market-neutral — the edge is weak.

**Why it's on hold:** A pairs trade is meaningless unless the spread is **cointegrated**
(stationary). **Run an ADF / Engle–Granger test on the spread first.** If it fails,
discard. Do not let the agent trade S12 until this passes. (Guardrail #1.)

---

## 4. Quick reference

| ID | Name | Type | Direction | Status | OOS Sharpe |
|----|------|------|-----------|--------|-----------|
| S02 | SMA 50/200 cross | trend | long/flat | APPROVED_FOR_PAPER | 0.80 |
| S06 | LSMA(25) | mean-reversion | long/flat | APPROVED_FOR_PAPER | 0.78 |
| S10 | Donchian breakout | breakout | long/flat | APPROVED_FOR_PAPER | 0.66 |
| S11 | QQQ/BND allocation | allocation | always-in | APPROVED_FOR_PAPER | 1.20 |
| S12 | KO/PEP pairs | stat-arb | market-neutral | **HOLD** | 0.22 |

**Next steps for the bot dev:** (1) parse `agent_strategies_rules.json`; (2) wire each
rule to live Hyperliquid candles; (3) emit `{symbol, side, target, size, strategy_id,
reason}` proposals to the human-approval gate; (4) re-validate each strategy on the
target crypto symbol before it is allowed past paper trading.
