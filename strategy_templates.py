#!/usr/bin/env python3
"""
strategy_templates.py  --  the VETTED parameterized strategy-family bank.

This is the safe half of the hybrid codegen step (Stage 5). Instead of letting an
LLM write arbitrary Python for every strategy, the router (codegen.py) maps each
extracted strategy onto one of the families below and fills in its parameters; we
then instantiate a known-good position function. Only strategies that fit no family
fall through to free-form LLM codegen.

Every family is built from the hand-coded, already-backtested logic in
catalog_strats.py / extras_backtest.py, just generalized over its parameters.

Two interface conventions (matching the existing engine exactly):
  * single-ticker family  -> kind="position": fn(df) -> Series in {1,0,-1}
                             (run_backtests.backtest() applies returns + costs)
  * multi-ticker  family  -> kind="return"  : fn(df_a, df_b) -> daily RETURN series
                             (weighting + costs already baked in, like s11/s12)

Public API used by codegen.py and run_backtests.py:
  FAMILIES                 dict name -> Family
  validate_params(name, p) -> cleaned params dict (defaults applied, clamped) or ValueError
  build(name, params)      -> the position/return function
"""
import numpy as np, pandas as pd
from dataclasses import dataclass, field
from typing import Callable

# --------------------------------------------------------------------------- #
# shared indicator helpers (single source of truth for templates + free-form)
# --------------------------------------------------------------------------- #
def _sma(close, n):
    return close.rolling(int(n)).mean()

def _ema(close, n):
    return close.ewm(span=int(n), adjust=False).mean()

def _rsi(close, n):                       # Wilder-style RSI (from catalog_strats)
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1 + up/dn)

def _lsma(close, n):                       # least-squares MA = OLS endpoint
    n = int(n); x = np.arange(n)
    def f(y):
        b, a = np.polyfit(x, y, 1)
        return a + b*(n-1)
    return close.rolling(n).apply(f, raw=True)

def _macd(close, fast, slow, signal):
    line = _ema(close, fast) - _ema(close, slow)
    sig  = line.ewm(span=int(signal), adjust=False).mean()
    return line, sig

def _stoch_k(df, n):
    ll = df["Low"].rolling(int(n)).min(); hh = df["High"].rolling(int(n)).max()
    return 100 * (df["Close"] - ll) / (hh - ll)


# --------------------------------------------------------------------------- #
# family registry plumbing
# --------------------------------------------------------------------------- #
@dataclass
class Family:
    make: Callable                 # (**params) -> position/return function
    params: dict                   # name -> spec {type, default, min/max, choices}
    multi_asset: bool = False
    kind: str = "position"         # "position" (single) | "return" (multi)
    assets: list = field(default_factory=list)   # role names for multi-asset
    benchmark: str = ""            # "risk_asset" | "cash" (multi-asset only)
    desc: str = ""


def _coerce(spec, value):
    t = spec["type"]
    if t == "int":    v = int(round(float(value)))
    elif t == "float": v = float(value)
    elif t == "bool": v = bool(value) if not isinstance(value, str) else value.strip().lower() in ("1","true","yes","y")
    elif t == "choice":
        v = str(value).strip().lower()
        if v not in spec["choices"]:
            raise ValueError(f"{v!r} not in {spec['choices']}")
        return v
    else:
        raise ValueError(f"unknown param type {t}")
    if "min" in spec: v = max(spec["min"], v)
    if "max" in spec: v = min(spec["max"], v)
    return v


def validate_params(name, params):
    """Apply defaults, coerce types, clamp to sane ranges. Raises on a bad family."""
    if name not in FAMILIES:
        raise ValueError(f"unknown family {name!r}")
    spec = FAMILIES[name].params
    out, params = {}, (params or {})
    for k, s in spec.items():
        if k in params and params[k] not in (None, "", "null"):
            try:
                out[k] = _coerce(s, params[k])
            except Exception:
                out[k] = s["default"]            # bad value -> safe default
        else:
            out[k] = s["default"]
    return out


def build(name, params):
    cleaned = validate_params(name, params)
    return FAMILIES[name].make(**cleaned)


# --------------------------------------------------------------------------- #
# single-ticker families  (return a position Series in {1,0,-1})
# --------------------------------------------------------------------------- #
def make_ma_crossover(fast, slow, ma):
    avg = _ema if ma == "ema" else _sma
    def fn(df):
        f = avg(df["Close"], fast); s = avg(df["Close"], slow)
        return (f > s).astype(float)
    return fn

def make_rsi_meanrev(rsi_n, lower, upper, sma_filter, time_stop):
    def fn(df):
        r = _rsi(df["Close"], rsi_n)
        trend = (df["Close"] > _sma(df["Close"], sma_filter)) if sma_filter else pd.Series(True, index=df.index)
        entry = (trend & (r < lower)).fillna(False).values
        ex    = (r > upper).fillna(False).values
        return _long_flat_timestop(df, entry, ex, time_stop)
    return fn

def make_bollinger(n, k, rsi_n, rsi_lower, rsi_upper, time_stop):
    def fn(df):
        c = df["Close"]; m = _sma(c, n); sd = c.rolling(int(n)).std()
        lo, hi = m - k*sd, m + k*sd; r = _rsi(c, rsi_n)
        entry = ((c <= lo) & (r < rsi_lower)).fillna(False).values
        ex    = ((c >= hi) & (r > rsi_upper)).fillna(False).values
        return _long_flat_timestop(df, entry, ex, time_stop)
    return fn

def make_macd(fast, slow, signal):
    def fn(df):
        line, sig = _macd(df["Close"], fast, slow, signal)
        return (line > sig).astype(float)
    return fn

def make_donchian_breakout(entry_n, exit_n):
    def fn(df):
        hh = df["High"].rolling(int(entry_n)).max().shift(1)
        ll = df["Low"].rolling(int(exit_n)).min().shift(1)
        entry = (df["Close"] > hh).fillna(False).values
        ex    = (df["Close"] < ll).fillna(False).values
        pos = np.zeros(len(df)); st = 0
        for i in range(len(df)):
            if st == 0 and entry[i]: st = 1
            elif st == 1 and ex[i]: st = 0
            pos[i] = st
        return pd.Series(pos, index=df.index)
    return fn

def make_lsma_meanrev(n):
    def fn(df):
        return (df["Close"] < _lsma(df["Close"], n)).astype(float)
    return fn

def make_linreg_mr(n, sma_filter, allow_short):
    def fn(df):
        lr = _lsma(df["Close"], n)
        above = (df["Close"] > _sma(df["Close"], sma_filter)) if sma_filter else pd.Series(True, index=df.index)
        el = ((df["Close"] < lr) & above).fillna(False).values
        xl = (df["Close"] > lr).fillna(False).values
        es = ((df["Close"] > lr) & ~above).fillna(False).values if allow_short else np.zeros(len(df), bool)
        xs = (df["Close"] < lr).fillna(False).values
        pos = np.zeros(len(df)); st = 0
        for i in range(len(df)):
            if st == 0:
                if el[i]: st = 1
                elif es[i]: st = -1
            elif st == 1 and xl[i]: st = 0
            elif st == -1 and xs[i]: st = 0
            pos[i] = st
        return pd.Series(pos, index=df.index)
    return fn

def make_stochastic(k_n, lower, upper, sma_filter, time_stop):
    def fn(df):
        k = _stoch_k(df, k_n)
        trend = (df["Close"] > _sma(df["Close"], sma_filter)) if sma_filter else pd.Series(True, index=df.index)
        entry = (trend & (k < lower)).fillna(False).values
        ex    = (k > upper).fillna(False).values
        return _long_flat_timestop(df, entry, ex, time_stop)
    return fn

def _long_flat_timestop(df, entry, ex, time_stop):
    """Shared stateful long/flat loop with an optional N-bar time stop (0 = none)."""
    ts = int(time_stop)
    pos = np.zeros(len(df)); st = 0; bars = 0
    for i in range(len(df)):
        if st == 0 and entry[i]: st, bars = 1, 0
        elif st == 1:
            bars += 1
            if ex[i] or (ts and bars >= ts): st = 0
        pos[i] = st
    return pd.Series(pos, index=df.index)


# --------------------------------------------------------------------------- #
# multi-ticker families  (return a daily RETURN series; costs baked in)
# --------------------------------------------------------------------------- #
_C = 5 / 10000.0   # 5 bps/trade, matches run_backtests.COST_BPS

def make_allocation(sma_n, on_risk_w, off_risk_w):
    def fn(risk_df, safe_df):                       # (risk, safe) -> return series
        rc = risk_df["Close"]
        w = pd.Series(np.where(rc > _sma(rc, sma_n), on_risk_w, off_risk_w), index=risk_df.index)
        rq = rc.pct_change()
        rb = safe_df["Close"].pct_change().reindex(risk_df.index)
        return (w.shift(1)*rq + (1-w).shift(1)*rb - w.diff().abs()*_C).fillna(0)
    return fn

def make_pairs(lookback, z_in, z_out):
    def fn(a_df, b_df):
        df = pd.DataFrame({"a": a_df["Close"], "b": b_df["Close"]}).dropna()
        L = int(lookback)
        beta = df["a"].rolling(L).cov(df["b"]) / df["b"].rolling(L).var()
        spread = df["a"] - beta*df["b"]
        z = (spread - spread.rolling(L).mean()) / spread.rolling(L).std()
        pos = np.zeros(len(df)); st = 0
        for i in range(len(df)):
            if st == 0:
                if z.iloc[i] < -z_in: st = 1
                elif z.iloc[i] > z_in: st = -1
            elif abs(z.iloc[i]) < z_out: st = 0
            pos[i] = st
        pos = pd.Series(pos, index=df.index)
        ra, rb = df["a"].pct_change(), df["b"].pct_change()
        return (pos.shift(1)*(ra - rb) - pos.diff().abs()*2*_C).fillna(0)
    return fn


# --------------------------------------------------------------------------- #
# THE BANK
# --------------------------------------------------------------------------- #
FAMILIES = {
    "ma_crossover": Family(
        make_ma_crossover, desc="Moving-average crossover (golden/death cross), long/flat.",
        params={
            "fast": {"type":"int","default":50,"min":2,"max":200},
            "slow": {"type":"int","default":200,"min":5,"max":400},
            "ma":   {"type":"choice","default":"sma","choices":["sma","ema"]},
        }),
    "rsi_meanrev": Family(
        make_rsi_meanrev, desc="RSI dip mean-reversion with optional trend filter + time stop.",
        params={
            "rsi_n":      {"type":"int","default":10,"min":2,"max":50},
            "lower":      {"type":"float","default":30,"min":1,"max":50},
            "upper":      {"type":"float","default":40,"min":40,"max":99},
            "sma_filter": {"type":"int","default":200,"min":0,"max":400},   # 0 = no filter
            "time_stop":  {"type":"int","default":10,"min":0,"max":100},    # 0 = no stop
        }),
    "bollinger": Family(
        make_bollinger, desc="Bollinger-band mean-reversion gated by RSI, with time stop.",
        params={
            "n":         {"type":"int","default":20,"min":5,"max":100},
            "k":         {"type":"float","default":2.0,"min":0.5,"max":4.0},
            "rsi_n":     {"type":"int","default":14,"min":2,"max":50},
            "rsi_lower": {"type":"float","default":30,"min":1,"max":50},
            "rsi_upper": {"type":"float","default":70,"min":50,"max":99},
            "time_stop": {"type":"int","default":10,"min":0,"max":100},
        }),
    "macd": Family(
        make_macd, desc="MACD line vs signal crossover, long/flat.",
        params={
            "fast":   {"type":"int","default":12,"min":2,"max":100},
            "slow":   {"type":"int","default":26,"min":5,"max":200},
            "signal": {"type":"int","default":9,"min":2,"max":50},
        }),
    "donchian_breakout": Family(
        make_donchian_breakout, desc="Donchian channel breakout: long on N-high break, exit on M-low break.",
        params={
            "entry_n": {"type":"int","default":20,"min":2,"max":200},
            "exit_n":  {"type":"int","default":10,"min":2,"max":200},
        }),
    "lsma_meanrev": Family(
        make_lsma_meanrev, desc="Long while close is below its least-squares (regression) MA.",
        params={
            "n": {"type":"int","default":25,"min":3,"max":200},
        }),
    "linreg_mr": Family(
        make_linreg_mr, desc="Linear-regression mean-reversion vs SMA200 trend; long and (optionally) short.",
        params={
            "n":          {"type":"int","default":14,"min":3,"max":200},
            "sma_filter": {"type":"int","default":200,"min":0,"max":400},
            "allow_short":{"type":"bool","default":True},
        }),
    "stochastic": Family(
        make_stochastic, desc="Stochastic-%K oversold mean-reversion with trend filter + time stop.",
        params={
            "k_n":        {"type":"int","default":8,"min":2,"max":50},
            "lower":      {"type":"float","default":20,"min":1,"max":50},
            "upper":      {"type":"float","default":80,"min":50,"max":99},
            "sma_filter": {"type":"int","default":200,"min":0,"max":400},
            "time_stop":  {"type":"int","default":10,"min":0,"max":100},
        }),
    "allocation": Family(
        make_allocation, multi_asset=True, kind="return",
        assets=["risk","safe"], benchmark="risk_asset",
        desc="Two-asset regime allocation: tilt to risk asset when above its SMA, else to safe asset.",
        params={
            "sma_n":      {"type":"int","default":30,"min":5,"max":200},
            "on_risk_w":  {"type":"float","default":0.8,"min":0.0,"max":1.0},
            "off_risk_w": {"type":"float","default":0.2,"min":0.0,"max":1.0},
        }),
    "pairs": Family(
        make_pairs, multi_asset=True, kind="return",
        assets=["a","b"], benchmark="cash",
        desc="Z-score pairs trade on the rolling-beta spread of two assets, market-neutral.",
        params={
            "lookback": {"type":"int","default":252,"min":20,"max":756},
            "z_in":     {"type":"float","default":2.0,"min":0.5,"max":5.0},
            "z_out":    {"type":"float","default":0.5,"min":0.0,"max":3.0},
        }),
}


if __name__ == "__main__":   # quick self-test on a synthetic frame
    idx = pd.date_range("2020-01-01", periods=600, freq="D")
    rng = np.random.default_rng(0)
    close = pd.Series(100*np.exp(np.cumsum(rng.normal(0, 0.01, 600))), index=idx)
    df = pd.DataFrame({"Open": close, "High": close*1.01, "Low": close*0.99,
                       "Close": close, "Volume": 1e6}, index=idx)
    for name, fam in FAMILIES.items():
        fn = build(name, {})
        if fam.multi_asset:
            out = fn(df, df)            # both roles = same frame, just a smoke test
            ok = isinstance(out, pd.Series) and np.isfinite(out.fillna(0)).all()
            print(f"{name:18s} return-series ok={ok}")
        else:
            out = fn(df)
            vals = set(pd.unique(out.dropna()))
            ok = isinstance(out, pd.Series) and vals <= {-1.0, 0.0, 1.0}
            print(f"{name:18s} position ok={ok}  values={sorted(vals)}")
