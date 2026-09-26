@echo off
rem Restart the background server, e.g. after downloading a new version.
net session >NUL 2>NUL
if errorlevel 1 (
  echo Please right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
schtasks /End /TN CentralStore >NUL 2>NUL
timeout /t 2 /nobreak >NUL
schtasks /Run /TN CentralStore
echo Restarted. Wait 5 seconds, then refresh the web page.
pause
