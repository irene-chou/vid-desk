@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: vid-snatch 一鍵啟動腳本 (Windows)
:: 雙擊此檔案即可使用

cd /d "%~dp0"

:: ── 設定檔 ──────────────────────────────────
set "CONFIG_DIR=%USERPROFILE%\.config\vid-snatch"
set "CONFIG_FILE=%CONFIG_DIR%\config"
set "DEFAULT_OUTPUT_DIR=%USERPROFILE%\Music\vid-snatch"
set "OUTPUT_DIR=%DEFAULT_OUTPUT_DIR%"

:: 載入設定
if exist "%CONFIG_FILE%" (
    for /f "usebackq tokens=1,* delims==" %%a in ("%CONFIG_FILE%") do (
        if "%%a"=="output_dir" set "OUTPUT_DIR=%%b"
    )
)

:: ── 檢查 Docker ─────────────────────────────
where docker >nul 2>&1
if errorlevel 1 (
    echo ============================================
    echo   需要先安裝 Docker Desktop
    echo   下載：https://docker.com/products/docker-desktop/
    echo ============================================
    pause
    start https://www.docker.com/products/docker-desktop/
    exit /b 1
)

:: 檢查 Docker 是否正在執行
docker info >nul 2>&1
if errorlevel 1 (
    echo 正在啟動 Docker Desktop...
    start "" "Docker Desktop"
    :wait_docker
    timeout /t 2 /nobreak >nul
    docker info >nul 2>&1
    if errorlevel 1 goto wait_docker
    echo Docker 已就緒！
)

:: 首次 build
docker image inspect vid-snatch >nul 2>&1
if errorlevel 1 (
    echo.
    echo 首次使用，正在建置環境（約 3-5 分鐘）...
    echo.
    docker build -t vid-snatch .
    echo.
    echo 建置完成！
)

:: ── 主迴圈 ───────────────────────────────────
:menu
echo.
echo ============================================
echo   vid-snatch
echo ============================================
echo.
echo   1) 下載音檔 (MP3)
echo   2) 下載去人聲音檔 (MP3)
echo   3) 下載影片 (MP4)
echo   4) 設定
echo   5) 重新建置 (更新程式後使用)
echo   6) 解除安裝
echo   q) 離開
echo.
set "choice="
set /p "choice=請選擇 [1/2/3/4/5/6/q]: "

if "%choice%"=="q" goto quit
if "%choice%"=="Q" goto quit
if "%choice%"=="1" goto download
if "%choice%"=="2" goto download
if "%choice%"=="3" goto download
if "%choice%"=="4" goto settings
if "%choice%"=="5" goto rebuild
if "%choice%"=="6" goto uninstall

echo 無效選擇，請輸入 1、2、3、4、5、6 或 q
goto menu

:: ── 下載 ─────────────────────────────────────
:download
echo.
set "url="
set /p "url=請貼上 YouTube 網址: "

if "%url%"=="" (
    echo 網址不能為空！
    goto menu
)

:: 確保輸出資料夾存在
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

:: 組裝指令
set "cmd="
if "%choice%"=="2" set "cmd=--no-vocals"
if "%choice%"=="3" set "cmd=--video"

echo.
echo 處理中...
if "%choice%"=="2" echo (去人聲需要 3-8 分鐘，首次會先下載約 320MB 模型)
echo.

docker run --rm -it -v "%OUTPUT_DIR%:/app/output" -v vid-snatch-models:/root/.cache/torch vid-snatch "%url%" %cmd%

echo.
echo ============================================
echo   完成！檔案已存到：
echo   %OUTPUT_DIR%
echo ============================================

:: 開啟資料夾
explorer "%OUTPUT_DIR%" 2>nul
goto menu

:: ── 設定 ─────────────────────────────────────
:settings
echo.
echo ============================================
echo   設定
echo ============================================
echo.
echo   目前儲存路徑: %OUTPUT_DIR%
echo.
set "new_dir="
set /p "new_dir=輸入新路徑（按 Enter 保持不變）: "

if "%new_dir%"=="" (
    echo   路徑未變更。
    goto menu
)

:: 建立資料夾
if not exist "%new_dir%" mkdir "%new_dir%" 2>nul

if exist "%new_dir%" (
    if not exist "%CONFIG_DIR%" mkdir "%CONFIG_DIR%"
    echo output_dir=%new_dir%> "%CONFIG_FILE%"
    set "OUTPUT_DIR=%new_dir%"
    echo.
    echo   路徑已更新為: %new_dir%
) else (
    echo.
    echo   無法建立資料夾: %new_dir%
)
goto menu

:: ── 重新建置 ─────────────────────────────────
:rebuild
echo.
set "confirm="
set /p "confirm=確定要重新建置嗎？這會需要 3-5 分鐘 [y/N]: "
if /i not "%confirm%"=="y" (
    echo 已取消。
    goto menu
)
echo.
echo 移除舊版本...
docker rmi vid-snatch 2>nul
docker builder prune -f 2>nul
echo 重新建置中（約 3-5 分鐘）...
docker build -t vid-snatch .
echo.
echo 建置完成！舊的暫存檔已清除。
goto menu

:: ── 解除安裝 ─────────────────────────────────
:uninstall
echo.
echo ============================================
echo   解除安裝 vid-snatch
echo ============================================
echo.
set "confirm="
set /p "confirm=確定要解除安裝嗎？(y/N): "
if /i not "%confirm%"=="y" (
    echo 已取消。
    goto menu
)

echo.
echo 移除 Docker 映像檔...
docker rmi vid-snatch 2>nul
docker builder prune -f 2>nul

echo 移除設定檔...
if exist "%CONFIG_DIR%" rmdir /s /q "%CONFIG_DIR%"

set "del_output="
set /p "del_output=是否也刪除您先前下載的音檔與影片？(%OUTPUT_DIR%) (y/N): "
if /i "%del_output%"=="y" (
    if exist "%OUTPUT_DIR%" rmdir /s /q "%OUTPUT_DIR%"
    echo 已刪除下載檔案。
)

echo.
echo ============================================
echo   解除安裝完成！
echo   如需完全移除，可手動刪除此專案資料夾：
echo   %~dp0
echo ============================================
pause
exit /b 0

:: ── 離開 ─────────────────────────────────────
:quit
echo Bye!
exit /b 0
