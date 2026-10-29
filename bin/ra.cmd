@echo off
rem Research-Agent CLI wrapper for Windows cmd / PowerShell.
set "RA_ROOT=%~dp0.."
set "PYTHONPATH=%RA_ROOT%\src;%PYTHONPATH%"
if not defined CLAUDE_PLUGIN_ROOT set "CLAUDE_PLUGIN_ROOT=%RA_ROOT%"
if exist "%USERPROFILE%\.research-agent\venv\Scripts\python.exe" (
  "%USERPROFILE%\.research-agent\venv\Scripts\python.exe" -m research_agent %*
) else (
  py -3 -m research_agent %*
)
