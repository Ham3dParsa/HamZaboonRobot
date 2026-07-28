@echo off
chcp 65001 > nul
title Benchmark - Gemini 3.6 Flash (Silver User Simulation)

cd /d "%~dp0\..\.."

echo ============================================================
echo   User Simulation: Silver Plan (Gemini 3.6 Flash / compact)
echo   Primary:  google_36_flash_eliapi
echo   Fallback: google_36_flash_hpof   (same model, different key)
echo ============================================================
echo.

python -m tools.benchmark ^
  --mode user ^
  --plan silver ^
  --presets google_36_flash_eliapi ^
  --fallback google_36_flash_hpof ^
  --compact

echo.
echo ============================================================
echo   Done! See tools/benchmark/reports/benchmark_usersim_* for report.
echo ============================================================
pause
