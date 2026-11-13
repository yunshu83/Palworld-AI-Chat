@echo off
rem Start the Palworld server and the chat bot together, detached from this window.
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start-all.ps1"
exit
