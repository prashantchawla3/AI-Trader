#!/usr/bin/env python3
"""
make_dashboard.py — builds dashboard.html, a single self-contained page a
non-technical person can open by double-clicking. No server, no install.

It reads the project's real output files and tells the honest story:
  backtest_results.csv  -> how every strategy did vs just holding the market
  codegen_report.csv    -> plain-English names/families for the strategies
  bot_log.csv           -> the paper bot's recent decisions (if any)

Re-run after a fresh backtest to refresh the numbers:
    python make_dashboard.py
"""
import os, datetime as dt
import pandas as pd

OUT = "dashboard.html"

FRIENDLY = {
    "ma_crossover": "Moving-average crossover",
    "donchian_breakout": "Price breakout",
    "rsi_meanrev": "Buy-the-dip (RSI)",
    "bollinger": "Buy-the-dip (Bollinger bands)",
    "stochastic": "Oversold bounce (Stochastic)",
    "linreg_mr": "Trend-line mean reversion",
    "allocation": "Stocks / bonds switch",
}

def pct(x): return f"{x*100:+.0f}%"

def load():
    res = pd.read_csv("backtest_results.csv")
    fam = {}
    if os.path.exists("codegen_report.csv"):
        rep = pd.read_csv("codegen_report.csv")
        for _, r in rep.iterrows():
            if isinstance(r.get("gid"), str):
                fam[r["gid"]] = FRIENDLY.get(str(r.get("family")), str(r.get("strategy_name", "")))
    return res, fam

def build():
    res, fam = load()
    tested = int(res["strat"].nunique())
    beat = int(res["beats_return"].sum())
    spy = res[res["ticker"] == "SPY"].copy()
    bh = float(spy["bh_total"].iloc[0]) if len(spy) else 0.0

    # collapse identical duplicates (same rounded OOS return = same underlying rule)
    spy["k"] = spy["oos_total"].round(3)
    distinct = spy.sort_values("oos_total", ascending=False).drop_duplicates("k")
    n_distinct = len(distinct)
    top = distinct.head(10)

    maxv = max(bh, float(top["oos_total"].max())) * 1.08
    bench_pct_h = bh / maxv * 100

    # ---- chart bars ----
    bars = []
    best = True
    for _, r in top.iterrows():
        label = fam.get(r["strat"], r["strat"])
        h = max(r["oos_total"], 0) / maxv * 100
        cls = "bar best" if best else "bar"
        best = False
        bars.append(
            f'<div class="col"><div class="track">'
            f'<div class="{cls}" style="height:{h:.1f}%"><span class="val">{pct(r["oos_total"])}</span></div>'
            f'</div><div class="lbl">{label}</div></div>'
        )
    bars_html = "".join(bars)

    # ---- paper bot activity ----
    if os.path.exists("bot_log.csv"):
        log = pd.read_csv("bot_log.csv").tail(8).iloc[::-1]
        rows = []
        for _, r in log.iterrows():
            when = str(r.get("ts", ""))[:16].replace("T", "  ")
            dec = str(r.get("decision", ""))
            badge = {"FILLED_PAPER": "fill", "HOLD": "hold",
                     "NO_TRADE": "skip", "PROPOSED_DECLINED": "skip"}.get(dec, "hold")
            nice = {"FILLED_PAPER": "Bought (paper)", "HOLD": "Held position",
                    "NO_TRADE": "No trade", "PROPOSED_DECLINED": "Declined"}.get(dec, dec)
            rows.append(
                f"<tr><td class='mono'>{when}</td><td>{r.get('ticker','')} · {r.get('strategy','')}</td>"
                f"<td><span class='pill {badge}'>{nice}</span></td>"
                f"<td class='mono'>${float(r.get('equity',0)):,.0f}</td></tr>"
            )
        activity = ("<table class='log'><thead><tr><th>When</th><th>Strategy</th>"
                    "<th>Decision</th><th>Paper balance</th></tr></thead><tbody>"
                    + "".join(rows) + "</tbody></table>")
    else:
        activity = ("<div class='empty'>No paper runs recorded yet. "
                    "Run <code>python bot.py SPY s10</code> and this fills in.</div>")

    best_row = top.iloc[0]
    best_lbl = fam.get(best_row["strat"], best_row["strat"])
    gen = dt.date.today().strftime("%B %d, %Y")

    html = TEMPLATE
    repl = {
        "{{TESTED}}": str(tested), "{{BEAT}}": str(beat),
        "{{BH}}": pct(bh), "{{BEST}}": pct(best_row["oos_total"]),
        "{{BEST_LBL}}": best_lbl, "{{BENCH_H}}": f"{bench_pct_h:.1f}",
        "{{BARS}}": bars_html, "{{ACTIVITY}}": activity,
        "{{N_DISTINCT}}": str(n_distinct), "{{GEN}}": gen,
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {OUT}  ({tested} strategies, {beat} beat buy & hold, "
          f"buy&hold {pct(bh)}, best {pct(best_row['oos_total'])})")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI-Trader — Honest Results</title>
<style>
  :root{
    --ink:#15233b; --ink2:#51617a; --paper:#eceef2; --card:#ffffff;
    --line:#15233b; --bar:#90a6c4; --best:#3f5d86; --good:#2f7d5b;
    --warn:#9a6a1f; --hair:#d7dce3;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);
    font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    line-height:1.55;-webkit-font-smoothing:antialiased}
  .mono{font-family:ui-monospace,Menlo,Consolas,monospace}
  .wrap{max-width:920px;margin:0 auto;padding:40px 24px 80px}
  .tag{display:inline-block;font-size:12px;letter-spacing:.14em;text-transform:uppercase;
    color:var(--warn);border:1px solid var(--warn);border-radius:999px;padding:4px 12px;font-weight:600}
  h1{font-size:clamp(30px,5vw,46px);line-height:1.05;letter-spacing:-.02em;margin:18px 0 6px;font-weight:800}
  .sub{color:var(--ink2);font-size:18px;max-width:640px;margin:0}
  .hero{background:var(--card);border:1px solid var(--hair);border-radius:16px;
    padding:30px 30px 26px;margin:26px 0 30px}
  .verdict{display:flex;gap:30px;flex-wrap:wrap;align-items:flex-end}
  .big{font-size:clamp(54px,9vw,84px);font-weight:800;letter-spacing:-.03em;line-height:.9}
  .big small{display:block;font-size:15px;font-weight:600;color:var(--ink2);letter-spacing:0;margin-top:10px}
  .verdict p{margin:0;max-width:420px;color:var(--ink2);font-size:16px}
  .verdict p b{color:var(--ink)}
  h2{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink2);
    margin:42px 0 14px;font-weight:700}
  .card{background:var(--card);border:1px solid var(--hair);border-radius:16px;padding:26px}
  /* chart */
  .chart{position:relative;height:340px;margin-top:8px;padding-top:6px}
  .bench{position:absolute;left:0;right:0;border-top:3px solid var(--line);z-index:3}
  .bench .b-lbl{position:absolute;right:0;top:-26px;background:var(--line);color:#fff;
    font-size:12px;font-weight:700;padding:3px 9px;border-radius:6px}
  .bench .b-note{position:absolute;left:0;top:-22px;font-size:12px;color:var(--ink2);font-style:italic}
  .bars{position:absolute;inset:0;display:flex;gap:10px;align-items:flex-end}
  .col{flex:1;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end}
  .track{width:100%;height:100%;display:flex;align-items:flex-end}
  .bar{width:100%;background:var(--bar);border-radius:6px 6px 0 0;position:relative;
    transition:height .9s cubic-bezier(.2,.7,.2,1)}
  .bar.best{background:var(--best)}
  .bar .val{position:absolute;top:-20px;left:0;right:0;text-align:center;font-size:12px;
    font-weight:700;font-family:ui-monospace,Menlo,Consolas,monospace}
  .lbl{font-size:11px;color:var(--ink2);text-align:center;margin-top:8px;min-height:30px;line-height:1.25}
  .cap{color:var(--ink2);font-size:14px;margin-top:18px}
  /* plain-english cards */
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}
  .pt{background:var(--card);border:1px solid var(--hair);border-radius:14px;padding:20px}
  .pt h3{margin:0 0 6px;font-size:17px}
  .pt p{margin:0;color:var(--ink2);font-size:15px}
  /* safety */
  .safe{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
  .s{display:flex;gap:11px;align-items:flex-start;background:var(--card);
    border:1px solid var(--hair);border-radius:12px;padding:16px}
  .s .dot{width:9px;height:9px;border-radius:50%;background:var(--good);margin-top:7px;flex:none}
  .s b{display:block;font-size:15px}.s span{font-size:13px;color:var(--ink2)}
  /* log */
  table.log{width:100%;border-collapse:collapse;font-size:14px}
  .log th{text-align:left;color:var(--ink2);font-weight:600;font-size:12px;
    text-transform:uppercase;letter-spacing:.08em;padding:0 10px 10px}
  .log td{padding:11px 10px;border-top:1px solid var(--hair)}
  .pill{font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px}
  .pill.fill{background:#e7f1ec;color:var(--good)}
  .pill.hold{background:#eef1f6;color:var(--ink2)}
  .pill.skip{background:#f6efe4;color:var(--warn)}
  .empty{color:var(--ink2);font-size:15px}
  code{background:#eef1f6;padding:2px 6px;border-radius:5px;font-size:13px}
  footer{margin-top:46px;color:var(--ink2);font-size:13px;border-top:1px solid var(--hair);padding-top:18px}
  @media (prefers-reduced-motion:reduce){.bar{transition:none}}
</style></head>
<body><div class="wrap">

  <span class="tag">Research · paper trading · no real money</span>
  <h1>What our trading research actually found</h1>
  <p class="sub">Plain-language summary of the strategies we built and tested on ten years of real market data.</p>

  <div class="hero">
    <div class="verdict">
      <div class="big">{{BEAT}} / {{TESTED}}<small>strategies that beat simply holding the market</small></div>
      <p>We generated and tested <b>{{TESTED}} strategies</b>. After real-world trading costs, on data they were never tuned on, <b>none</b> earned more than just buying the S&amp;P 500 and doing nothing (<b>{{BH}}</b> over the period). This is the honest result — and the reason we are <b>not</b> risking real money.</p>
    </div>
  </div>

  <h2>Every strategy vs. just holding the market</h2>
  <div class="card">
    <div class="chart">
      <div class="bench" style="bottom:{{BENCH_H}}%">
        <span class="b-note">Nothing clears this line</span>
        <span class="b-lbl">Buy &amp; hold the S&amp;P 500 · {{BH}}</span>
      </div>
      <div class="bars">{{BARS}}</div>
    </div>
    <p class="cap">Each bar is a strategy's total return over the test period on the S&amp;P 500. The black line is what you'd have made doing nothing. Our best one — {{BEST_LBL}} — returned {{BEST}}, still short of the line. (Showing the {{N_DISTINCT}} genuinely different strategies; many of the others were near-duplicates under different names.)</p>
  </div>

  <h2>What this means, in plain English</h2>
  <div class="grid">
    <div class="pt"><h3>“Doing nothing” won</h3><p>The benchmark is buying the whole market once and holding it. None of our active strategies beat that after costs.</p></div>
    <div class="pt"><h3>Some lower the risk</h3><p>A few dropped less in bad years — but they also earned less. Less risk, less return, not free money.</p></div>
    <div class="pt"><h3>So we stay on paper</h3><p>Because nothing has earned it, the bot trades pretend money only. Real money waits for real evidence.</p></div>
  </div>

  <h2>The safety system</h2>
  <div class="safe">
    <div class="s"><span class="dot"></span><div><b>Paper money only</b><span>No connection to a real exchange. Nothing can place a live order.</span></div></div>
    <div class="s"><span class="dot"></span><div><b>Spending cap</b><span>The bot can never put more than a set amount into one position.</span></div></div>
    <div class="s"><span class="dot"></span><div><b>Daily loss limit</b><span>If a day's losses cross a line, it stops taking new risk automatically.</span></div></div>
    <div class="s"><span class="dot"></span><div><b>Human approval</b><span>Every order waits for a person to say yes before it happens.</span></div></div>
    <div class="s"><span class="dot"></span><div><b>Bad signal = no trade</b><span>If the instructions are unclear, the safe default is to do nothing.</span></div></div>
    <div class="s"><span class="dot"></span><div><b>Everything recorded</b><span>Every decision — buys, holds, and skips — is logged for review.</span></div></div>
  </div>

  <h2>Paper bot — recent activity</h2>
  <div class="card">{{ACTIVITY}}</div>

  <footer>Generated {{GEN}} from the project's own backtest and bot logs · Research tool, not financial advice · Past results do not predict the future.</footer>

</div></body></html>"""

if __name__ == "__main__":
    build()
