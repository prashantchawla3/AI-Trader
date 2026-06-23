@echo off
REM ===================== AI-Trader  -  live demo =====================
REM Double-click this file, or run  demo.bat  from the project folder.
REM It pauses between steps so you can talk. Press a key to advance.
REM ==================================================================
cd /d "%~dp0"
title AI-Trader demo

echo.
echo ============================================================
echo   STEP 1  -  The honest results dashboard
echo ============================================================
echo   Building the dashboard from the real backtest numbers...
py make_dashboard.py
echo   Opening it in your browser.
start "" "dashboard.html"
echo.
echo   SAY: "We tested 40 strategies on 10 years of real data.
echo         The black line is just holding the S^&P 500. Zero of
echo         ours beat it - that's why no real money is at risk."
echo.
pause

echo.
echo ============================================================
echo   STEP 2  -  What the bot can run
echo ============================================================
py bot.py --list
echo.
echo   SAY: "It runs any validated strategy, and it won't fake the
echo         ones that don't fit."
echo.
pause

echo.
echo ============================================================
echo   STEP 3  -  Prove the safety guardrails
echo ============================================================
py bot.py --selftest
echo.
echo   SAY: "Before it can place any order, it proves its own
echo         guardrails: spending cap, daily loss limit, and
echo         bad-signal-means-no-trade."
echo.
pause

echo.
echo ============================================================
echo   STEP 4  -  One live paper decision (you approve it)
echo ============================================================
REM clean slate so it shows a fresh BUY, not a HOLD
if exist bot_state.json del /q bot_state.json
if exist bot_log.csv del /q bot_log.csv
echo   Running one decision. When it asks, type  y  and press Enter.
echo.
py bot.py SPY s10
echo.
echo   SAY: "Every order stops and waits for a person. Nothing runs
echo         unattended, and every decision is logged."
echo.
echo ============================================================
echo   Demo complete.  System works. Discipline is the asset.
echo   No real money until a strategy earns it.
echo ============================================================
pause
