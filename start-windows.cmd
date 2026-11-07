@echo off
cd /d "%~dp0"
py -3 -m countermand.server %*
if errorlevel 1 pause
