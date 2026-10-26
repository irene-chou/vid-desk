@echo off
chcp 65001 >nul

:: vid-snatch 一鍵啟動腳本 (Windows)
:: 雙擊此檔案即可使用；實際流程在 windows\launcher.ps1
:: 下載包配置的啟動器在 files\windows\，repo 配置在 windows\

setlocal
cd /d "%~dp0"
set "LAUNCHER=%~dp0windows\launcher.ps1"
if exist "%~dp0files\windows\launcher.ps1" set "LAUNCHER=%~dp0files\windows\launcher.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%"
if errorlevel 1 pause
