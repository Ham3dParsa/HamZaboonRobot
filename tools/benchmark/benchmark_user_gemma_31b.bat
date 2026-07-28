@echo off
chcp 65001 > nul
title Benchmark - Gemma 4 31B (Silver User Simulation / compact)

cd /d "%~dp0\..\.."

echo ============================================================
echo   User Simulation: Silver Plan (Gemma 4 31B / compact)
echo   Primary:  google_gemma_4_31b_eliapi
echo   Fallback: google_gemma_4_31b_hpof  (same model, different key)
echo ============================================================
echo.

python -m tools.benchmark ^
  --mode user ^
  --plan silver ^
  --presets google_gemma_4_31b_eliapi ^
  --fallback google_gemma_4_31b_hpof ^
  --compact

echo.
echo ============================================================
echo   Done! See tools/benchmark/reports/benchmark_usersim_* for report.
echo ============================================================
pause
