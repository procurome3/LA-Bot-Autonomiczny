@echo off
setlocal
cd /d "%~dp0"
py profile_start.py symbiont %*
