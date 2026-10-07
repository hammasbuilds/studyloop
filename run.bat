@echo off
rem Starts StudyLoop and opens the browser. Close this window to stop the server.
set VIRTUAL_ENV=
cd /d "%~dp0"
title StudyLoop
uv run studyloop %*
if errorlevel 1 pause
