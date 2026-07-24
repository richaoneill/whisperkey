@echo off
REM Launch WhisperKey. Keyboard hooks need admin to inject into some apps
REM (elevated terminals, etc). Right-click -> Run as administrator if paste
REM doesn't land in a given window.
cd /d "%~dp0"
".venv\Scripts\python.exe" "src\main.py"
pause
