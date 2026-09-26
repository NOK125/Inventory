@echo off
cd /d "%~dp0"
rem Allow other computers on the network to connect. Delete this line to allow only this computer.
set "HOST=0.0.0.0"
set "PY=python"
where python >NUL 2>NUL || set "PY=py"
"%PY%" server.py --open
echo.
echo Server stopped. Press any key to close.
pause >NUL
