@echo off
REM ===========================================================================
REM benchmark_fast.bat — Quick benchmark: flash-lite-latest eliapi, both modes
REM
REM Benchmarks only the cheapest/most stable preset (google_flash_lite_latest_eliapi)
REM in both modes. Use this for a quick sanity check or cost verification.
REM Skips overwrite confirmation with --presets (no interactive prompt).
REM ===========================================================================

cd /d "%~dp0\..\.."

echo [Fast Benchmark] Preset: google_flash_lite_latest_eliapi, both modes...
echo.

python -m tools.benchmark ^
    --presets google_flash_lite_latest_eliapi ^
    --mode both ^
    --compact ^
    --verbose

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Benchmark failed with code %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [Done] Fast benchmark complete.
pause
