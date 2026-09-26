@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem เปิดให้เครื่องอื่นในเครือข่ายเข้าได้ ถ้าจะใช้แค่เครื่องนี้ให้ลบบรรทัดนี้
set "HOST=0.0.0.0"
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" server.py --open
pause
