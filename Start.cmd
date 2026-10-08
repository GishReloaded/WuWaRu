@echo off
cd /d "%~dp0"
if exist WuwaRu.exe (
    start "" "%~dp0WuwaRu.exe"
) else (
    py -3.10 main.py gui
)
