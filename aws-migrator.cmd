@echo off
REM OS-Agnostic Windows CLI entrypoint (Command Prompt & PowerShell)
where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py -3 "%~dp0agent.py" %*
) else (
    python "%~dp0agent.py" %*
)
