@echo off
title FSRS-6 v1.4 Simulator
cd /d "%~dp0"
echo Starting FSRS-6 v1.4 Simulator...
echo.
python run_server.py
echo.
echo Server stopped.
pause
