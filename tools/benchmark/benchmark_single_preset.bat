@echo off
REM ===========================================================================
REM benchmark_single_preset.bat — Benchmark a single preset in single mode
REM
REM Edit the PRESET_NAME below to change which preset is tested.
REM Useful for focused testing of one model without interactive prompts.
REM ===========================================================================

cd /d "%~dp0\..\.."

REM ── Change this to the preset you want to test ──
set PRESET_NAME=google_36_flash_eliapi

echo [Single Preset] Preset: %PRESET_NAME%, mode: single (non-batched only)...
echo.

python -m tools.benchmark ^
    --presets %PRESET_NAME% ^
    --mode single ^
    --compact ^
    --verbose

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Benchmark failed with code %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [Done] Single-preset benchmark complete.
pause
