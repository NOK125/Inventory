@echo off
cd /d "%~dp0"
rem Temporary public HTTPS link for testing (https://xxxx.trycloudflare.com).
rem The link changes every time. Start run.bat first and keep it open.
where cloudflared >NUL 2>NUL || (
  echo cloudflared is not installed. Run this in an Administrator command prompt:
  echo   winget install --id Cloudflare.cloudflared
  echo Then close and reopen this window.
  pause
  exit /b 1
)
echo Look for a line with https://....trycloudflare.com below and share that link.
echo Keep this window open. Closing it stops the public link.
echo.
cloudflared tunnel --url http://localhost:8000
pause
