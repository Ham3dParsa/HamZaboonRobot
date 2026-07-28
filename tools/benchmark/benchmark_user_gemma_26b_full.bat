@echo off
chcp 65001 > nul
title Benchmark - Gemma 4 26B (Silver User Simulation / full JSON)

cd /d "%~dp0\..\.."

echo ============================================================
echo   User Simulation: Silver Plan (Gemma 4 26B / full JSON)
echo   Primary:  google_gemma_4_26b_eliapi
echo   Fallback: google_gemma_4_26b_hpof  (same model, different key)
echo ============================================================
echo.

python -m tools.benchmark ^
  --mode user ^
  --plan silver ^
  --presets google_gemma_4_26b_eliapi ^
  --fallback google_gemma_4_26b_hpof ^
  --no-compact

echo.
echo ============================================================
echo   Done! See tools/benchmark/reports/benchmark_usersim_* for report.
echo ============================================================
pause
