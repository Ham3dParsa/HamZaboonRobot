@echo off
REM ===========================================================================
REM benchmark_both_modes.bat — Compare single vs batch mode on one preset
REM
REM Benchmarks one preset in BOTH modes (single and batch) to compare cost,
REM latency, and quality of batched vs non-batched card generation.
REM Edit PRESET_NAME below to change the target.
REM ===========================================================================

cd /d "%~dp0\..\.."

REM ── Change this to the preset you want to test ──
set PRESET_NAME=google_flash_lite_latest_eliapi

echo [Both Modes] Preset: %PRESET_NAME%, comparing single vs batch...
echo.

python -m tools.benchmark ^
    --presets %PRESET_NAME% ^
    --mode both ^
    --compact ^
    --verbose

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Benchmark failed with code %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [Done] Both-modes benchmark complete.
pause
