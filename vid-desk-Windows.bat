@echo off
chcp 65001 >nul

:: vid-desk 一鍵啟動腳本 (Windows)
:: 雙擊此檔案即可使用；實際流程在 windows\launcher.ps1
:: 下載包配置的啟動器在 files\windows\，repo 配置在 windows\

setlocal
cd /d "%~dp0"
set "LAUNCHER=%~dp0windows\launcher.ps1"
if exist "%~dp0files\windows\launcher.ps1" set "LAUNCHER=%~dp0files\windows\launcher.ps1"
if not exist "%LAUNCHER%" goto missing
powershell -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%"
set "CODE=%errorlevel%"
:: 結束碼不是 0（含負數）就停住視窗，讓使用者看得到訊息
if not "%CODE%"=="0" pause
exit /b %CODE%

:missing
:: 直接在 zip 裡雙擊時，檔案總管只會把這個 .bat 解到暫存資料夾，旁邊沒有 launcher.ps1
echo.
echo 請先把 vid-desk.zip 解壓縮，再雙擊解壓後資料夾裡的 vid-desk-Windows.bat
echo.
pause
exit /b 1
