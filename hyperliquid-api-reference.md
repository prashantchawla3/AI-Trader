# Hyperliquid API — Reference & Bot Integration Guide

**Purpose:** Everything the team needs to know about Hyperliquid and its API to build our momentum agent against it. Written so each endpoint is explained as *what it is → what it lets you do → how our bot uses it*.

**Last updated:** 2026-06-22
**Source:** Official Hyperliquid docs (`hyperliquid.gitbook.io`) + current fee/venue reporting.

---

## 1. What Hyperliquid is (summary)

Hyperliquid is a decentralized perpetual-futures and spot exchange running on its own Layer-1 blockchain (HyperCore for the order book, HyperEVM for smart contracts). The thing that matters for us: it behaves like a centralized exchange (Binance/Bybit) — a real central limit order book, market/limit/stop orders, leverage — but it's **non-custodial**, so funds stay in your wallet and there's no account-approval process.

Key facts:
- **Order book, on-chain, ~1 second execution.** Not an AMM/pool. Limit orders, market orders, stop-losses, and leverage all behave normally.
- **150+ perpetual pairs.** Majors (BTC, ETH, SOL) have deep liquidity. Also lists altcoins, meme coins, and synthetic exposure to some US stocks and pre-IPO names — but **we trade majors only** (per our strategy decision).
- **Leverage up to 50x** (varies by asset). For us this is a hazard, not a feature — we cap at ≤2x in code.
- **No gas on order book actions.** Placing/modifying/canceling orders on HyperCore costs zero gas.
- **Two environments:** Mainnet (`api.hyperliquid.xyz`) and **Testnet** (`api.hyperliquid-testnet.xyz`). Testnet uses fake funds and is our paper-trading sandbox for the build phase.
- **SDKs:** official **Python SDK** (`hyperliquid-python-sdk`), community TypeScript/Rust SDKs, and **CCXT** support. We'll use CCXT for backtest data pulls and the Python SDK (or direct REST) for the live bot.

---

## 2. Pricing / fees

Fees are the silent killer on a $200 account, so understand them before sizing anything.

### Trading fees (base tier — under $5M 14-day volume, which is us)

| Market | Maker (resting limit order) | Taker (market / crossing order) |
|---|---|---|
| **Perpetuals** | 0.015% | 0.045% |
| Spot | 0.040% | 0.070% |

- Fees drop on a **rolling 14-day volume** schedule (assessed daily, UTC). We will never leave the base tier at our size — assume base rates.
- **HYPE staking** gives an additional discount up to 40%; a referral code gives ~4%. Not worth chasing at our scale.
- At the very top maker tiers, makers earn a small **rebate** (negative fee). Irrelevant to us, but it's why limit/post-only orders are always cheaper than market orders.

### Two fee facts that bite small accounts

1. **Fee is on notional, not margin.** A 2x-leveraged $100 position pays fees on the full $100 notional, not the $50 of margin. Round-trip taker on $100 notional ≈ $0.09. Small, but it compounds across many trades.
2. **Fees are debited from your USDC balance, not netted from PnL.** You pay fees even on losing trades, so the balance falls slightly faster than the mark price alone implies.

### Other costs

- **Funding rate:** paid **hourly**, peer-to-peer (Hyperliquid takes no cut). If the perp trades above the index, longs pay shorts; below, shorts pay longs. Typical magnitude ~0.001%/hour ≈ ~0.025%/day ≈ ~9% APR. **This matters for swing trades held overnight/over weekends — it must be in the backtester.**
- **Withdrawal:** flat **1 USDC** to Arbitrum.
- **Deposits:** no platform fee (only Arbitrum gas). USDC must arrive on **Arbitrum One** — not Ethereum mainnet.
- **Minimum order value: $10 notional.** Real constraint for us — see §6.

---

## 3. API structure (the three endpoints)

Everything runs through three URLs. The first two are HTTP POST; the third is WebSocket.

| Endpoint | URL | What it's for |
|---|---|---|
| **Info** | `POST https://api.hyperliquid.xyz/info` | Read data: prices, candles, order book, account state, fills, funding. No signature needed for market data. |
| **Exchange** | `POST https://api.hyperliquid.xyz/exchange` | Do things: place/cancel/modify orders, set leverage, transfers, withdrawals. **Every action must be cryptographically signed.** |
| **WebSocket** | `wss://api.hyperliquid.xyz/ws` | Real-time streams (trades, candles, book, your order/fill updates). Lower latency than polling Info. |

You pick the operation by the `type` field in the JSON body. Same URL, different `type`.

---

## 4. Authentication & the API wallet (do this right — it's a guardrail)

Exchange actions are signed with a private key. **Do not use your main wallet's key in the bot.** Instead use an **API wallet** (a.k.a. "agent wallet"):

- Created via the `approveAgent` action (or in the Hyperliquid app under More → API).
- It can **place and manage orders on behalf of your account but cannot withdraw funds.**
- You can have 1 unnamed + up to 3 named API wallets per account.
- Set a validity window (e.g. 180 days) and rotate.

**Why this is our security backbone:** even if the bot, the n8n server, or the key leaks, the worst case is bad trades — **nobody can drain the account.** This is exactly the non-custodial guarantee our guardrails require. The bot's scope is "trade only," enforced at the signing layer, not in a prompt.

Practical setup: fund a dedicated trading address with only the capital you're willing to risk (our $200), generate an API wallet for it, and keep your main holdings in a separate wallet.

---

## 5. The Info endpoint — market & account data

This is how the bot *sees* the market and its own state. You POST `{"type": "<request>", ...}`. Key request types:

### Market data (no signature)

| `type` | What it returns | How our bot uses it |
|---|---|---|
| `allMids` | All current mid prices, one call | Quick price snapshot across watchlist |
| `l2Book` | Order book depth (bids/asks) for a coin | **Slippage / spread check before sizing** — confirm the book is deep enough to enter without bad fills |
| `candleSnapshot` | Historical OHLCV candles for a coin + interval | **The workhorse.** Feeds our indicators (EMA, volume avg, swing highs) at runtime, and bulk-pulls history for the Phase-3 backtest |
| `meta` | Perp "universe": list of assets, their index (asset ID), max leverage | Resolve asset IDs; check per-asset max leverage |
| `metaAndAssetCtxs` | Meta + live context: mark price, oracle price, **funding rate**, open interest | Funding-rate context for Claude's judgment layer; mark price for PnL |

> **Pagination:** time-range queries return at most **500 elements** per call. For deep history, page backward using the last returned timestamp as the next `startTime`. (Or just use CCXT's `fetch_ohlcv`, which handles this.)

### Account data (your address; read-only)

| `type` | What it returns | How our bot uses it |
|---|---|---|
| `clearinghouseState` | Open positions, margin summary, **account value**, withdrawable | **Guardrail pre-check** — read account value + open positions to enforce max position size, daily-loss limit, and max-concurrent-positions before proposing anything |
| `openOrders` / `frontendOpenOrders` | Resting orders | Know what's already live before placing/canceling |
| `userFills` | Fill history (price, size, fee, closedPnl) | **Logging to Supabase** — record every fill and outcome |
| `userFunding` | Funding payments paid/received | Track the funding drag on swing positions |
| `orderStatus` | Status of a specific order | Confirm an order rested/filled/was rejected |

---

## 6. The Exchange endpoint — trading & account actions

Every call here is signed (by the API wallet). The bot only needs a handful of these; the rest exist but are **out of scope** for safety.

### The actions our bot actually uses

**`order` — place an order.** The core action.
- Fields (short keys): `a` asset index, `b` isBuy, `p` price, `s` size, `r` reduceOnly, `t` type, `c` optional client order id (cloid).
- **Time-in-force** for limit orders: `Alo` (post-only — cancels instead of crossing, guarantees maker fee), `Ioc` (immediate-or-cancel), `Gtc` (good-til-canceled, normal resting).
- **Trigger orders** (this is how we do stop-loss and take-profit): `t: {"trigger": {"isMarket": bool, "triggerPx": price, "tpsl": "tp" | "sl"}}`.
- `grouping`: `"normalTpsl"` or `"positionTpsl"` lets you attach a stop-loss + take-profit to an entry as one bracket.
- **Responses:** `resting` (returns `oid`), `filled` (returns `totalSz`, `avgPx`, `oid`), or `error` (e.g. *"Order must have minimum value of $10."*).
- **How we use it:** after human approval, place the entry as a limit order (`Alo`/`Gtc` to pay maker fee), with a `tpsl` trigger stop at the strategy's invalidation price. Use a `cloid` so we can track each trade end-to-end into Supabase.

**`cancel` / `cancelByCloid` — cancel orders.** Remove a resting order by `oid` or by our client id. Used to pull stale entries that didn't fill.

**`modify` / `batchModify` — change a resting order's price/size** without canceling and re-placing. Used to trail a stop or adjust an unfilled entry.

**`updateLeverage` — set cross or isolated leverage on a coin.** `{"type":"updateLeverage","asset":<idx>,"isCross":bool,"leverage":<int>}`. **We call this to force leverage to ≤2x before trading** — a hard guardrail set on-exchange, not just assumed.

**`scheduleCancel` — "dead man's switch."** Schedules a cancel-all at a future time; if the bot doesn't refresh it, all open orders auto-cancel. Min 5 seconds ahead, max 10 triggers/day. **Use this as a safety net:** if n8n crashes or loses connectivity, resting orders don't sit unmanaged forever.

### Actions the bot must NOT touch (lock them out)

`withdraw3`, `usdSend`, `spotSend`, `sendAsset`, `usdClassTransfer` (spot↔perp), staking/vault actions. The API wallet **can't withdraw** anyway, but we keep all money-movement out of the bot's code path entirely. Movement of funds is a manual, human-only action.

### Also available (not needed now)

`twapOrder` (time-weighted execution — useful only for large size we don't have), `approveBuilderFee` (builder-code fee routing), `reserveRequestWeight` (buy extra rate-limit headroom for 0.0005 USDC/request), prediction-market outcome actions (Polymarket-style — not our market).

---

## 7. WebSocket — real-time data

Connect to `wss://api.hyperliquid.xyz/ws` and send subscription messages. Useful subscriptions: `trades`, `l2Book`, `candle`, `allMids`, and user-specific streams like order updates and fills.

- Limits: 100 connections, 1000 subscriptions, 2000 messages/min per IP.
- **You must handle disconnects and reconnect gracefully** — the server drops connections periodically without warning; missed data arrives in the snapshot on reconnect.
- **For our swing/multi-hour timeframe we mostly don't need WebSocket** — polling `candleSnapshot` on the n8n schedule is simpler and enough. WebSocket matters for fast intraday, which we're deliberately not doing. Keep it optional.

---

## 8. Rate limits

Per IP (REST): an aggregated **weight budget of 1200 per minute**.
- Most Exchange actions weigh `1 + floor(batch_length / 40)`.
- Info requests: `l2Book`, `allMids`, `clearinghouseState`, `orderStatus` weigh **2**; most other info requests weigh **20**; `candleSnapshot` adds weight per 60 items returned.

Per address (Exchange): **1 request per 1 USDC of cumulative volume traded**, with an initial buffer of **10,000 requests**. Cancels get a higher allowance so you can always exit. If you ever need more headroom you can buy it via `reserveRequestWeight`.

**For us:** on a swing timeframe with a handful of majors and infrequent trades, we're nowhere near these limits. Worth knowing, not worth engineering around yet. Use WebSocket (not polling loops) only if we ever go faster.

---

## 9. How it all wires into our bot (the loop)

Mapping the endpoints to our pipeline and guardrails:

| Step | Hyperliquid call | Notes / guardrail |
|---|---|---|
| **Backtest (Phase 3)** | `candleSnapshot` (or CCXT `fetch_ohlcv`) | Pull BTC/ETH/SOL history; model fees + **hourly funding** + slippage |
| **Scheduled scan** | `candleSnapshot`, `metaAndAssetCtxs`, `l2Book` | Latest bars for indicators; funding context; book depth for slippage sanity |
| **Deterministic signal** | *(none — runs in our Code node on the candle data)* | Claude is **not** involved here |
| **Guardrail pre-check** | `clearinghouseState` | Read account value + positions → enforce max size, daily-loss, max-concurrent |
| **Set leverage** | `updateLeverage` | Force ≤2x on-exchange |
| **Claude judgment** | *(uses funding + position data already pulled)* | Structured decision; malformed → NO TRADE |
| **Human approval** | *(out-of-band: human confirms)* | Gate stays on until track record exists |
| **Execute** | `order` (limit + `tpsl` trigger stop), with `cloid` | Maker order (`Alo`/`Gtc`) to pay 0.015% not 0.045%; mind the **$10 min** |
| **Manage / safety** | `modify`, `cancel`, `scheduleCancel` | Trail stops; dead-man's switch if bot dies |
| **Log** | `userFills`, `orderStatus`, `userFunding` → Supabase | Every fill, skip, and outcome recorded |
| **Security** | `approveAgent` once, at setup | Trade-only API wallet; **cannot withdraw** |

### The two constraints to design around (don't forget)

1. **$10 minimum order value.** With $200 and a ≤2x cap, max notional is ~$400, so a single position is fine — but at the lower end, a trade has to be ≥$10 notional. That sets a floor on how finely you can size, and means risk-per-trade can't be arbitrarily tiny. Plan position sizing within the $10–$400 notional band.
2. **Hourly funding on swing holds.** A position held several days bleeds funding every hour. The backtest must charge it, or "profitable" setups will be fake.

---

## 10. Quick links

- API index: `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api`
- Exchange endpoint: `.../api/exchange-endpoint`
- Info endpoint: `.../api/info-endpoint`
- WebSocket: `.../api/websocket`
- Rate limits: `.../api/rate-limits-and-user-limits`
- Fees: `https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees`
- Python SDK: `https://github.com/hyperliquid-dex/hyperliquid-python-sdk`
- CCXT integration: `https://docs.ccxt.com/#/exchanges/hyperliquid`
