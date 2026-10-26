@echo off
chcp 65001 >nul

:: vid-snatch 一鍵啟動腳本 (Windows)
:: 雙擊此檔案即可使用；實際流程在 vid-snatch.ps1

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0vid-snatch.ps1"
if errorlevel 1 pause
