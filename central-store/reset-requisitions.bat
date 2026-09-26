@echo off
cd /d "%~dp0"
rem Delete ALL requisitions and return issued stock (asks for YES first, backs up automatically).
set "PY=python"
where python >NUL 2>NUL || set "PY=py"
"%PY%" server.py --reset-requisitions
pause >NUL
