@echo off
setlocal
cd /d "%~dp0"
if not defined CLIPPEDAI_PORT set "CLIPPEDAI_PORT=5000"
start "" "http://127.0.0.1:%CLIPPEDAI_PORT%/"
python app.py

