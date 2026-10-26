# vid-snatch Windows 原生安裝冒煙測試（只給 GitHub Actions 用）
# 依序跑五個情境；任一情境失敗就印出啟動器輸出與 $Root\logs\* 後 exit 1。
# 注意：此檔需存成 UTF-8 with BOM、CRLF，並相容 Windows PowerShell 5.1。

$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$RepoDir = Split-Path $PSScriptRoot -Parent
$Launcher = Join-Path $RepoDir 'windows\launcher.ps1'

# 使用者資料夾放在含中文與空白的路徑，確認整條安裝流程都能處理
$TestHome = Join-Path $env:RUNNER_TEMP '測試 使用者'
$env:USERPROFILE = $TestHome
$env:LOCALAPPDATA = Join-Path $TestHome 'AppData\Local'
$env:VS_NO_BROWSER = '1'
$Root = Join-Path $env:LOCALAPPDATA 'vid-snatch'
$ServerFile = Join-Path $Root 'server.json'

$SmokeLogDir = Join-Path $env:RUNNER_TEMP 'smoke-logs'
$EmptyInput = Join-Path $SmokeLogDir 'empty-stdin.txt'

$Scenario = '準備'
$Launchers = New-Object System.Collections.ArrayList
$PortHolder = $null

function Remove-IfExists([string]$path) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}

function Show-File([string]$path) {
    Write-Host ''
    Write-Host "----- $path"
    try {
        Get-Content -LiteralPath $path -Encoding UTF8 | ForEach-Object { Write-Host $_ }
    } catch {
        Write-Host "（無法讀取：$($_.Exception.Message)）"
    }
}

function Show-Logs {
    foreach ($l in @($Launchers)) {
        Show-File $l.Out
        Show-File $l.Err
    }
    $logDir = Join-Path $Root 'logs'
    if (Test-Path -LiteralPath $logDir) {
        foreach ($f in @(Get-ChildItem -LiteralPath $logDir -File)) { Show-File $f.FullName }
    } else {
        Write-Host ''
        Write-Host "----- $logDir 不存在"
    }
    if (Test-Path -LiteralPath $ServerFile) { Show-File $ServerFile }
}

function Fail([string]$msg) {
    Write-Host ''
    Write-Host "::error::情境「$Scenario」失敗：$msg"
    Show-Logs
    # 盡量收拾背景行程，避免卡住 job
    foreach ($l in @($Launchers)) {
        try { if (-not $l.Proc.HasExited) { Stop-Process -Id $l.Proc.Id -Force } } catch { }
    }
    $info = Read-ServerJson
    if ($info) { try { Stop-Process -Id $info.pid -Force } catch { } }
    if ($PortHolder) { try { Stop-Process -Id $PortHolder.Id -Force } catch { } }
    exit 1
}

function Start-Scenario([string]$name) {
    $script:Scenario = $name
    Write-Host ''
    Write-Host "===== 情境：$name"
}

# 在背景執行啟動器；標準輸入導向空檔，輸出寫到 smoke-logs\<名稱>.out.log / .err.log
function Start-Launcher([string]$name) {
    $out = Join-Path $SmokeLogDir "$name.out.log"
    $err = Join-Path $SmokeLogDir "$name.err.log"
    $proc = Start-Process powershell -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$Launcher`"" `
        -PassThru -RedirectStandardInput $EmptyInput -RedirectStandardOutput $out -RedirectStandardError $err
    # 先取 Handle，否則行程結束後在 PowerShell 5.1 讀不到 ExitCode
    $null = $proc.Handle
    [void]$Launchers.Add(@{ Name = $name; Proc = $proc; Out = $out; Err = $err })
    Write-Host "已啟動 $name（pid $($proc.Id)）"
    return $proc
}

function Read-ServerJson {
    if (-not (Test-Path -LiteralPath $ServerFile)) { return $null }
    try {
        $info = ConvertFrom-Json ([System.IO.File]::ReadAllText($ServerFile))
        return @{ pid = [int]$info.pid; port = [int]$info.port }
    } catch {
        return $null
    }
}

function Get-Text([string]$url) {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5
    return [System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
}

# 等到 server.json 出現且其 port 的 /api/health 有回應；回傳 server.json 內容
function Wait-Server($proc, [int]$seconds) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $nextReport = 60
    while ($sw.Elapsed.TotalSeconds -lt $seconds) {
        if ($proc.HasExited) { Fail "啟動器在伺服器就緒前結束，結束碼 $($proc.ExitCode)" }
        $info = Read-ServerJson
        if ($info) {
            try {
                [void](Get-Text "http://127.0.0.1:$($info.port)/api/health")
                Write-Host ("健康檢查通過（{0:N0} 秒，pid {1}，port {2}）" -f $sw.Elapsed.TotalSeconds, $info.pid, $info.port)
                return $info
            } catch { }
        }
        if ($sw.Elapsed.TotalSeconds -ge $nextReport) {
            Write-Host ("  已等待 {0:N0} 秒…" -f $sw.Elapsed.TotalSeconds)
            $nextReport += 60
        }
        Start-Sleep -Seconds 2
    }
    Fail "等了 $seconds 秒，健康檢查仍未通過"
}

function Wait-Exit($proc, [int]$seconds, [string]$label) {
    if (-not $proc.WaitForExit($seconds * 1000)) { Fail "$label 沒有在 $seconds 秒內結束" }
    $code = $proc.ExitCode
    if ($code -ne 0) { Fail "$label 結束碼為 $code（預期 0）" }
    Write-Host "$label 已結束，結束碼 0"
}

function Assert-ProcessGone([int]$id) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while (Get-Process -Id $id -ErrorAction SilentlyContinue) {
        if ($sw.Elapsed.TotalSeconds -ge 10) { Fail "伺服器行程 $id 仍存在" }
        Start-Sleep -Milliseconds 500
    }
    Write-Host "伺服器行程 $id 已不存在"
}

function Invoke-Shutdown([int]$port) {
    try {
        Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$port/api/shutdown" `
            -Headers @{ 'X-Vid-Snatch' = '1' } -TimeoutSec 10 | Out-Null
    } catch {
        Fail "POST /api/shutdown 失敗：$($_.Exception.Message)"
    }
    Write-Host '已送出 POST /api/shutdown'
}

# 關閉伺服器並確認啟動器 30 秒內以 0 結束、伺服器行程消失
function Stop-AndVerify($proc, $info, [string]$label) {
    Invoke-Shutdown $info.port
    Wait-Exit $proc 30 $label
    Assert-ProcessGone $info.pid
}

# ── 準備 ────────────────────────────────────
Remove-IfExists $TestHome
New-Item -ItemType Directory -Force -Path $env:LOCALAPPDATA | Out-Null
Remove-IfExists $SmokeLogDir
New-Item -ItemType Directory -Force -Path $SmokeLogDir | Out-Null
[System.IO.File]::WriteAllText($EmptyInput, '')
Write-Host "LOCALAPPDATA = $env:LOCALAPPDATA"
Write-Host "USERPROFILE  = $env:USERPROFILE"

# ── 1. 首次安裝 ─────────────────────────────
Start-Scenario '1. 首次安裝'
$env:VS_SOURCE = 'local'
$python = (Get-Command python).Source
$PortHolder = Start-Process -FilePath $python -ArgumentList '-m', 'http.server', '8080', '--bind', '127.0.0.1' `
    -PassThru -WindowStyle Hidden
$sw = [System.Diagnostics.Stopwatch]::StartNew()
while (-not (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue)) {
    if ($PortHolder.HasExited -or $sw.Elapsed.TotalSeconds -ge 30) { Fail '無法用 http.server 佔住 8080' }
    Start-Sleep -Milliseconds 500
}
Write-Host '已用 http.server 佔住 8080'

$first = Start-Launcher 'launcher-1'
$info1 = Wait-Server $first (25 * 60)
if ($info1.port -eq 8080) { Fail '伺服器用了已被佔住的 8080' }
try {
    $html = Get-Text "http://127.0.0.1:$($info1.port)/"
} catch {
    Fail "GET / 失敗：$($_.Exception.Message)"
}
if (-not $html.Contains('names-row')) { Fail 'GET / 的回應不含 names-row' }
Write-Host "port $($info1.port) ≠ 8080，GET / 含 names-row"
Stop-Process -Id $PortHolder.Id -Force
$PortHolder = $null

# ── 2. 重複啟動 ─────────────────────────────
Start-Scenario '2. 重複啟動'
$second = Start-Launcher 'launcher-2'
Wait-Exit $second 60 '第二個啟動器'
$info2 = Read-ServerJson
if (-not $info2) { Fail '重複啟動後 server.json 不見了' }
if ($info2.pid -ne $info1.pid) { Fail "server.json 的 pid 從 $($info1.pid) 變成 $($info2.pid)" }
if ($first.HasExited) { Fail "第一個啟動器意外結束，結束碼 $($first.ExitCode)" }
Write-Host "server.json 的 pid 仍為 $($info1.pid)"

# ── 3. 結束 ─────────────────────────────────
Start-Scenario '3. 結束'
Stop-AndVerify $first $info1 '第一個啟動器'

# ── 4. 離線再啟動 ───────────────────────────
Start-Scenario '4. 離線再啟動'
Remove-Item Env:\VS_SOURCE
$env:VS_UPDATE_API = 'http://127.0.0.1:9/'
$offline = Start-Launcher 'launcher-offline'
$info4 = Wait-Server $offline 60
Stop-AndVerify $offline $info4 '離線啟動器'
Remove-Item Env:\VS_UPDATE_API

# ── 5. 中斷續裝 ─────────────────────────────
Start-Scenario '5. 中斷續裝'
Remove-IfExists (Join-Path $Root 'venv')
Remove-IfExists (Join-Path $Root 'state\installed-commit')
Write-Host '已刪除 venv 與 state\installed-commit'
$env:VS_SOURCE = 'local'
$resume = Start-Launcher 'launcher-resume'
$info5 = Wait-Server $resume (25 * 60)
Stop-AndVerify $resume $info5 '續裝啟動器'

Write-Host ''
Write-Host '全部情境通過'
exit 0
