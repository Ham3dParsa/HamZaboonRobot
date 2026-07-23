@echo off
REM ===========================================================================
REM benchmark_full.bat — Full benchmark: all enabled presets, both modes, compact
REM
REM Runs the benchmark on all active AI presets in both non-batched (single) and
REM batched modes using compact JSON format and the default 12-word vocabulary.
REM Prompts for overwrite confirmation per preset.
REM ===========================================================================

cd /d "%~dp0\..\.."

echo [Full Benchmark] Starting: all presets, both modes, compact format...
echo.

python -m tools.benchmark ^
    --mode both ^
    --compact ^
    --verbose

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Benchmark failed with code %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [Done] Full benchmark complete.
pause
