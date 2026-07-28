@echo off
chcp 65001 > nul
title Benchmark - Gemini Flash Lite (Silver User Simulation)

cd /d "%~dp0\..\.."

echo ============================================================
echo   User Simulation: Silver Plan (Gemini Flash Lite / compact)
echo   Primary:  google_flash_lite_latest_eliapi
echo   Fallback: google_flash_lite_latest_hpof (same model, diff key)
echo ============================================================
echo.

python -m tools.benchmark ^
  --mode user ^
  --plan silver ^
  --presets google_flash_lite_latest_eliapi ^
  --fallback google_flash_lite_latest_hpof ^
  --compact

echo.
echo ============================================================
echo   Done! See tools/benchmark/reports/benchmark_usersim_* for report.
echo ============================================================
pause
