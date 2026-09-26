@echo off
rem Remove auto-start. After this, use run.bat again.
net session >NUL 2>NUL
if errorlevel 1 (
  echo Please right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
schtasks /End /TN CentralStore >NUL 2>NUL
schtasks /Delete /TN CentralStore /F
echo Auto-start removed. Start the server with run.bat from now on.
pause
