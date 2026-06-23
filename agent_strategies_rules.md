# Agent Strategy Rules

**Hand-off spec for the bot/agent developer.** Auto-generated from the Stage-6
backtest survivors. Source of truth (code): `generated_strats.py` /
`strategy_templates.py`. Evidence: `backtest_results.csv`.

> ⚠️ Research tool, not financial advice. Nothing here is approved for live unattended trading. V1 requires a human approval gate.

## Execution model

- **Timeframe:** 1D (Crypto is 24/7; treat one bar as a fixed-UTC 24h candle.)
- **Signal timing:** Compute from data up to and including the just-closed bar.
- **Fill timing:** next_bar — Never act on the bar that produced the signal (no look-ahead). Research engine shifts the position series by 1 bar.
- **Costs:** 5 bps per trade. Position encoding {'long': 1, 'flat': 0, 'short': -1}. Pyramiding: False.

## Global guardrails (non-negotiable)

1. No strategy trades live without an out-of-sample backtest on the target symbol.
2. Out-of-sample after costs is the bar; in-sample-only performance is ignored as overfit.
3. Costs and slippage are charged on every test.
4. V1 human approval gate: the agent proposes {symbol, side, target, size, strategy_id, reason}; a human approves before the order is sent.
5. Kill switch and risk caps (per-trade max risk, max concurrent positions, daily-loss limit) must exist before live.

### Validation provenance

- Validated on: US equities (SPY, QQQ, AAPL, MSFT, GOOGL), daily bars, last 10y; target: Hyperliquid crypto perps.
- Re-validate every strategy out-of-sample on the actual target symbol before live size (guardrail #1).
- Do not add a short leg that was not validated; approved strategies are long/flat, allocation, or market-neutral.
- Lookbacks are in bars, not calendar days; keep them in bars across markets.

## Strategies

### G001 — Price Channel Breakout Strategy  *(breakout, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `donchian_breakout`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `upper` = max(high, 20) over previous 20 bars (shift 1)
- `lower` = min(low, 20) over previous 20 bars (shift 1)

**Rules**
- **entry_long:** position == 0 and close > upper
- **exit_to_flat:** position == 1 and close < lower

**Parameters:** `{'entry_n': 20, 'exit_n': 20}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.78, 'return_avg': 0.59, 'maxdd_avg': -0.226, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** Donchian 20/20 channel breakout; typically the lowest-drawdown of the set.

*Source video:* https://www.youtube.com/watch?v=aMrKe4ndzCA

---

### G003 — Long-only Momentum Strategy with 200-day SMA Exit  *(trend-following, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `ma_crossover`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `ma_fast` = SMA(close,50)
- `ma_slow` = SMA(close,200)

**Rules**
- **entry_long:** ma_fast > ma_slow
- **exit_to_flat:** ma_fast <= ma_slow

**Parameters:** `{'fast': 50, 'slow': 200, 'ma': 'sma'}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.8, 'return_avg': 0.754, 'maxdd_avg': -0.251, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** SMA 50/200 crossover; low-turnover trend filter, whipsaws in choppy markets.

*Source video:* https://www.youtube.com/watch?v=unsa_gXPAJ4

---

### G004 — 8 SMA and 25 SMA Crossover Strategy  *(trend-following, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `ma_crossover`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `ma_fast` = SMA(close,8)
- `ma_slow` = SMA(close,25)

**Rules**
- **entry_long:** ma_fast > ma_slow
- **exit_to_flat:** ma_fast <= ma_slow

**Parameters:** `{'fast': 8, 'slow': 25, 'ma': 'sma'}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.88, 'return_avg': 0.759, 'maxdd_avg': -0.195, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** SMA 8/25 crossover; low-turnover trend filter, whipsaws in choppy markets.

*Source video:* https://www.youtube.com/watch?v=sYRCzSbvOpQ

---

### G010 — DCA Pop  *(mean-reversion, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `bollinger`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `mid` = SMA(close,20)
- `lower` = mid - 2.0*std(close,20)
- `upper` = mid + 2.0*std(close,20)
- `rsi` = RSI(close,14)

**Rules**
- **entry_long:** close <= lower AND rsi < 30.0
- **exit_to_flat:** close >= upper AND rsi > 70.0

**Parameters:** `{'n': 20, 'k': 2.0, 'rsi_n': 14, 'rsi_lower': 30.0, 'rsi_upper': 70.0, 'time_stop': 0}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.81, 'return_avg': 0.674, 'maxdd_avg': -0.237, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** Bollinger-band reversion gated by RSI, with a time stop.

*Source video:* https://www.youtube.com/watch?v=YQGp7Fk2X3E

---

### G012 — Moving Average Crossover  *(trend-following, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `ma_crossover`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `ma_fast` = SMA(close,5)
- `ma_slow` = SMA(close,20)

**Rules**
- **entry_long:** ma_fast > ma_slow
- **exit_to_flat:** ma_fast <= ma_slow

**Parameters:** `{'fast': 5, 'slow': 20, 'ma': 'sma'}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.82, 'return_avg': 0.61, 'maxdd_avg': -0.21, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** SMA 5/20 crossover; low-turnover trend filter, whipsaws in choppy markets.

*Source video:* https://www.youtube.com/watch?v=b3VFMdjBfKA

---

### G013 — Breakout Strategy  *(breakout, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `donchian_breakout`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `upper` = max(high, 20) over previous 20 bars (shift 1)
- `lower` = min(low, 10) over previous 10 bars (shift 1)

**Rules**
- **entry_long:** position == 0 and close > upper
- **exit_to_flat:** position == 1 and close < lower

**Parameters:** `{'entry_n': 20, 'exit_n': 10}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.66, 'return_avg': 0.384, 'maxdd_avg': -0.2, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** Donchian 20/10 channel breakout; typically the lowest-drawdown of the set.

*Source video:* https://www.youtube.com/watch?v=Z7MA_68HmF0

---

### G019 — Least Squares Moving Average (LSMA) Trading Strategy  *(mean-reversion, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `lsma_meanrev`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `lsma` = LSMA(close,25): OLS endpoint a+b*(24) over last 25 closes

**Rules**
- **entry_long:** close < lsma
- **exit_to_flat:** close >= lsma

**Parameters:** `{'n': 25}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.78, 'return_avg': 0.618, 'maxdd_avg': -0.225, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** Long while price is below its least-squares regression line (counter-trend).

*Source video:* https://www.youtube.com/watch?v=sESQpRoo994

---

### G020 — SMA Bot for HIP-3 Stock Trading  *(trend-following, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `ma_crossover`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `ma_fast` = SMA(close,50)
- `ma_slow` = SMA(close,200)

**Rules**
- **entry_long:** ma_fast > ma_slow
- **exit_to_flat:** ma_fast <= ma_slow

**Parameters:** `{'fast': 50, 'slow': 200, 'ma': 'sma'}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.8, 'return_avg': 0.754, 'maxdd_avg': -0.251, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** SMA 50/200 crossover; low-turnover trend filter, whipsaws in choppy markets.

*Source video:* https://www.youtube.com/watch?v=PdmdT0uMGj8

---

### G025 — Simple Moving Average Crossover Strategy  *(trend-following, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `ma_crossover`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `ma_fast` = SMA(close,2)
- `ma_slow` = SMA(close,100)

**Rules**
- **entry_long:** ma_fast > ma_slow
- **exit_to_flat:** ma_fast <= ma_slow

**Parameters:** `{'fast': 2, 'slow': 100, 'ma': 'sma'}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.79, 'return_avg': 0.644, 'maxdd_avg': -0.205, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** SMA 2/100 crossover; low-turnover trend filter, whipsaws in choppy markets.

*Source video:* https://www.youtube.com/watch?v=Ets0xGCjQ14

---

### G026 — Simple Moving Average Crossover  *(trend-following, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `ma_crossover`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `ma_fast` = SMA(close,10)
- `ma_slow` = SMA(close,20)

**Rules**
- **entry_long:** ma_fast > ma_slow
- **exit_to_flat:** ma_fast <= ma_slow

**Parameters:** `{'fast': 10, 'slow': 20, 'ma': 'sma'}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.69, 'return_avg': 0.597, 'maxdd_avg': -0.243, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** SMA 10/20 crossover; low-turnover trend filter, whipsaws in choppy markets.

*Source video:* https://www.youtube.com/watch?v=4YmRpo60kow

---

### G028 — Two Moving Average Crossover  *(trend-following, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `ma_crossover`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `ma_fast` = SMA(close,50)
- `ma_slow` = SMA(close,200)

**Rules**
- **entry_long:** ma_fast > ma_slow
- **exit_to_flat:** ma_fast <= ma_slow

**Parameters:** `{'fast': 50, 'slow': 200, 'ma': 'sma'}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.8, 'return_avg': 0.754, 'maxdd_avg': -0.251, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** SMA 50/200 crossover; low-turnover trend filter, whipsaws in choppy markets.

*Source video:* https://www.youtube.com/watch?v=29_FVmMtDWw

---

### G030 — Golden Cross Moving Average Strategy (EV Stocks)  *(trend-following, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `ma_crossover`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `ma_fast` = SMA(close,50)
- `ma_slow` = SMA(close,200)

**Rules**
- **entry_long:** ma_fast > ma_slow
- **exit_to_flat:** ma_fast <= ma_slow

**Parameters:** `{'fast': 50, 'slow': 200, 'ma': 'sma'}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.8, 'return_avg': 0.754, 'maxdd_avg': -0.251, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** SMA 50/200 crossover; low-turnover trend filter, whipsaws in choppy markets.

*Source video:* https://www.youtube.com/watch?v=6FQz7MDTogs

---

### G032 — Moving Average Crossover EA  *(trend-following, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `ma_crossover`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `ma_fast` = SMA(close,50)
- `ma_slow` = SMA(close,200)

**Rules**
- **entry_long:** ma_fast > ma_slow
- **exit_to_flat:** ma_fast <= ma_slow

**Parameters:** `{'fast': 50, 'slow': 200, 'ma': 'sma'}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.8, 'return_avg': 0.754, 'maxdd_avg': -0.251, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** SMA 50/200 crossover; low-turnover trend filter, whipsaws in choppy markets.

*Source video:* https://www.youtube.com/watch?v=xK_yac8QF-I

---

### G035 — SMA Crossover Strategy  *(trend-following, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `ma_crossover`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `ma_fast` = SMA(close,2)
- `ma_slow` = SMA(close,20)

**Rules**
- **entry_long:** ma_fast > ma_slow
- **exit_to_flat:** ma_fast <= ma_slow

**Parameters:** `{'fast': 2, 'slow': 20, 'ma': 'sma'}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.81, 'return_avg': 0.641, 'maxdd_avg': -0.201, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** SMA 2/20 crossover; low-turnover trend filter, whipsaws in choppy markets.

*Source video:* https://www.youtube.com/watch?v=j6K-pyF1hdI

---

### G036 — Bitcoin SMA Crossover Strategy  *(trend-following, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `ma_crossover`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `ma_fast` = SMA(close,20)
- `ma_slow` = SMA(close,40)

**Rules**
- **entry_long:** ma_fast > ma_slow
- **exit_to_flat:** ma_fast <= ma_slow

**Parameters:** `{'fast': 20, 'slow': 40, 'ma': 'sma'}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.73, 'return_avg': 0.601, 'maxdd_avg': -0.232, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** SMA 20/40 crossover; low-turnover trend filter, whipsaws in choppy markets.

*Source video:* https://www.youtube.com/watch?v=QLYmpGlZpG0

---

### G037 — Multi-Timeframe Trend-Following with Price Action  *(breakout, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `donchian_breakout`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `upper` = max(high, 20) over previous 20 bars (shift 1)
- `lower` = min(low, 10) over previous 10 bars (shift 1)

**Rules**
- **entry_long:** position == 0 and close > upper
- **exit_to_flat:** position == 1 and close < lower

**Parameters:** `{'entry_n': 20, 'exit_n': 10}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.66, 'return_avg': 0.384, 'maxdd_avg': -0.2, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** Donchian 20/10 channel breakout; typically the lowest-drawdown of the set.

*Source video:* https://www.youtube.com/watch?v=4r55Vo-mOM8

---

### G039 — AI Swing Trade Analyzer  *(breakout, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `donchian_breakout`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `upper` = max(high, 20) over previous 20 bars (shift 1)
- `lower` = min(low, 10) over previous 10 bars (shift 1)

**Rules**
- **entry_long:** position == 0 and close > upper
- **exit_to_flat:** position == 1 and close < lower

**Parameters:** `{'entry_n': 20, 'exit_n': 10}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.66, 'return_avg': 0.384, 'maxdd_avg': -0.2, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** Donchian 20/10 channel breakout; typically the lowest-drawdown of the set.

*Source video:* https://www.youtube.com/watch?v=86ZpQn85nCc

---

### G040 — Multi-Asset Trend Following with Price Action  *(trend-following, long_flat)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `ma_crossover`  ·  method `template`  ·  tier ROBUST

**Indicators**
- `ma_fast` = EMA(close,20)
- `ma_slow` = EMA(close,50)

**Rules**
- **entry_long:** ma_fast > ma_slow
- **exit_to_flat:** ma_fast <= ma_slow

**Parameters:** `{'fast': 20, 'slow': 50, 'ma': 'ema'}`

**Evidence (OOS, after costs):** {'sharpe_avg': 0.7, 'return_avg': 0.566, 'maxdd_avg': -0.225, 'positive': '5/5', 'beats_buyhold': '0/5'}

**Notes:** EMA 20/50 crossover; low-turnover trend filter, whipsaws in choppy markets.

*Source video:* https://www.youtube.com/watch?v=MnG2Ru_LVEw

---

### G005 — Dynamic Allocation Strategy (QQQ/BND)  *(allocation, always_invested)*
**Status:** `APPROVED_FOR_PAPER`  ·  family `allocation`  ·  method `template`  ·  tier ROBUST
**Assets:** {'risk': 'QQQ', 'safe': 'BND'}  (code: generated_strats.py (MULTI))

**Indicators**
- `sma` = SMA(risk_close,30)

**Rules**
- **risk_on:** risk_close > sma -> 80% risk / 19% safe
- **risk_off:** risk_close <= sma -> 20% risk / 80% safe

**Parameters:** `{'sma_n': 30, 'on_risk_w': 0.8, 'off_risk_w': 0.2}`

**Evidence (OOS, after costs):** {'sharpe': 1.19, 'return': 0.788, 'maxdd': -0.194}

**Notes:** Two-asset regime allocation. Re-validate the SMA regime and weights on the chosen crypto pair.

*Source video:* https://www.youtube.com/watch?v=-F3ITjfelrM

---

## Quick reference

| ID | Name | Type | Direction | Status |
|----|------|------|-----------|--------|
| G001 | Price Channel Breakout Strategy | breakout | long_flat | APPROVED_FOR_PAPER |
| G003 | Long-only Momentum Strategy with 200-day SMA Exit | trend-following | long_flat | APPROVED_FOR_PAPER |
| G004 | 8 SMA and 25 SMA Crossover Strategy | trend-following | long_flat | APPROVED_FOR_PAPER |
| G010 | DCA Pop | mean-reversion | long_flat | APPROVED_FOR_PAPER |
| G012 | Moving Average Crossover | trend-following | long_flat | APPROVED_FOR_PAPER |
| G013 | Breakout Strategy | breakout | long_flat | APPROVED_FOR_PAPER |
| G019 | Least Squares Moving Average (LSMA) Trading Strategy | mean-reversion | long_flat | APPROVED_FOR_PAPER |
| G020 | SMA Bot for HIP-3 Stock Trading | trend-following | long_flat | APPROVED_FOR_PAPER |
| G025 | Simple Moving Average Crossover Strategy | trend-following | long_flat | APPROVED_FOR_PAPER |
| G026 | Simple Moving Average Crossover | trend-following | long_flat | APPROVED_FOR_PAPER |
| G028 | Two Moving Average Crossover | trend-following | long_flat | APPROVED_FOR_PAPER |
| G030 | Golden Cross Moving Average Strategy (EV Stocks) | trend-following | long_flat | APPROVED_FOR_PAPER |
| G032 | Moving Average Crossover EA | trend-following | long_flat | APPROVED_FOR_PAPER |
| G035 | SMA Crossover Strategy | trend-following | long_flat | APPROVED_FOR_PAPER |
| G036 | Bitcoin SMA Crossover Strategy | trend-following | long_flat | APPROVED_FOR_PAPER |
| G037 | Multi-Timeframe Trend-Following with Price Action | breakout | long_flat | APPROVED_FOR_PAPER |
| G039 | AI Swing Trade Analyzer | breakout | long_flat | APPROVED_FOR_PAPER |
| G040 | Multi-Asset Trend Following with Price Action | trend-following | long_flat | APPROVED_FOR_PAPER |
| G005 | Dynamic Allocation Strategy (QQQ/BND) | allocation | always_invested | APPROVED_FOR_PAPER |
