@echo off
cd /d "%~dp0"
set "PY=python"
where python >NUL 2>NUL || set "PY=py"
"%PY%" server.py --backup
