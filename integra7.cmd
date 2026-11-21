@echo off
rem Windows shortcut: runs the WSL-side integra7 CLI from cmd or PowerShell.
rem The tool itself is installed in WSL by scripts/setup-wsl.sh.
rem Backslashes become forward slashes so Windows-style paths survive the Linux shell.
setlocal
set "ARGS=%*"
if defined ARGS set "ARGS=%ARGS:\=/%"
wsl.exe ~/.local/bin/integra7 %ARGS%
