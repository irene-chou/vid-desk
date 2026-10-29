# vid-desk Windows 原生安裝冒煙測試（只給 GitHub Actions 用）
# 依序跑下面的情境，共用同一份安裝；任一情境失敗就印出啟動器輸出與 $Root\logs\* 後 exit 1。
# 需要環境變數 VS_SMOKE_SHA：這次測試的 commit（workflow 傳入），用來走真正的「從 GitHub 更新」路徑：
# 啟動器查的 releases/latest 端點以本機 http.server 假冒（VS_UPDATE_API），tag_name 回這個 sha，
# 啟動器就會下載 github.com/<repo>/archive/<sha>.zip。
# 注意：此檔需存成 UTF-8 with BOM、CRLF，並相容 Windows PowerShell 5.1。

$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

$RepoDir = Split-Path $PSScriptRoot -Parent
$Launcher = Join-Path $RepoDir 'windows\launcher.ps1'

# 使用者資料夾放在含中文與空白的路徑，確認整條安裝流程都能處理
$TestHome = Join-Path $env:RUNNER_TEMP '測試 使用者'
$env:USERPROFILE = $TestHome
$env:LOCALAPPDATA = Join-Path $TestHome 'AppData\Local'
$env:VS_NO_BROWSER = '1'
$Root = Join-Path $env:LOCALAPPDATA 'vid-desk'
$ServerFile = Join-Path $Root 'server.json'
$AppDir = Join-Path $Root 'app'
$CommitMarker = Join-Path $Root 'state\installed-commit'
$RepairFlag = Join-Path $Root 'state\repair'
$ConfigFile = Join-Path $Root 'config\config'
# 後端在「自動更新下載工具後仍失敗」時寫的標記；vid-desk.ps1 看到就比照 -Upgrade 更新後刪掉（#31）
$UpgradeMarker = Join-Path $Root 'config\upgrade-pending'
$TorchDir = Join-Path $Root 'torch'
$Sentinel = Join-Path $AppDir 'ci-sentinel.txt'
# 與 vid-desk.ps1 的預設下載資料夾算法相同（系統的「音樂」資料夾，不受 USERPROFILE 影響）
$MusicDir = [Environment]::GetFolderPath('MyMusic')
if (-not $MusicDir) { $MusicDir = Join-Path $env:USERPROFILE 'Music' }
$DefaultOutputDir = Join-Path $MusicDir 'vid-desk'
$CustomOutputDir = Join-Path $TestHome '自訂 下載'

$Sha = "$env:VS_SMOKE_SHA".Trim()
# 假的 releases/latest：回應格式與 GitHub 相同（只需 tag_name），由 Start-MockApi 啟動
$MockApiPort = 8765
$MockApi = "http://127.0.0.1:$MockApiPort/latest.json"
$MockApiDir = Join-Path $env:RUNNER_TEMP 'mock-api'
$MockApiServer = $null
$OfflineApi = 'http://127.0.0.1:9/'

$SmokeLogDir = Join-Path $env:RUNNER_TEMP 'smoke-logs'
$EmptyInput = Join-Path $SmokeLogDir 'empty-stdin.txt'
$Backup = Join-Path $env:RUNNER_TEMP 'vid-desk-backup'

$Scenario = '準備'
$Launchers = New-Object System.Collections.ArrayList
$PortHolder = $null
$Failing = $false

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
    foreach ($f in @($ServerFile, $CommitMarker, (Join-Path $AppDir '.commit'))) {
        if (Test-Path -LiteralPath $f) { Show-File $f }
    }
}

function Fail([string]$msg) {
    # Fail 本身出錯時 trap 會再呼叫它，避免無限遞迴
    if ($script:Failing) { exit 1 }
    $script:Failing = $true
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
    if ($MockApiServer) { try { Stop-Process -Id $MockApiServer.Id -Force } catch { } }
    exit 1
}

# 沒被接住的錯誤（$ErrorActionPreference = 'Stop'）也要印出記錄檔
# trap 對整個腳本一開始就生效；Fail 還沒定義時（例如前面的設定出錯）也要印出原始錯誤
trap {
    $msg = "未預期的錯誤：$($_.Exception.Message)（$($_.InvocationInfo.PositionMessage)）"
    Write-Host "::error::$msg"
    if (Get-Command Fail -CommandType Function -ErrorAction SilentlyContinue) { Fail $msg }
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
    Write-Host "已啟動 $name（pid $($proc.Id)，VS_SOURCE=$env:VS_SOURCE，VS_UPDATE_API=$env:VS_UPDATE_API）"
    return $proc
}

# 啟動器（含它執行的 vid-desk.ps1）目前為止的輸出
function Get-LauncherOutput([string]$name) {
    $path = Join-Path $SmokeLogDir "$name.out.log"
    if (-not (Test-Path -LiteralPath $path)) { return '' }
    $fs = New-Object System.IO.FileStream($path, 'Open', 'Read', 'ReadWrite')
    try {
        $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8)
        return $sr.ReadToEnd()
    } finally {
        $fs.Dispose()
    }
}

function Assert-OutputContains([string]$name, [string]$text) {
    if (-not (Get-LauncherOutput $name).Contains($text)) { Fail "$name 的輸出沒有「$text」" }
    Write-Host "$name 的輸出有「$text」"
}

function Assert-OutputLacks([string]$name, [string]$text) {
    # 先確認讀得到中文輸出，才不會因為編碼問題誤判為「沒有」
    Assert-OutputContains $name '正在檢查更新'
    if ((Get-LauncherOutput $name).Contains($text)) { Fail "$name 的輸出不應有「$text」" }
    Write-Host "$name 的輸出沒有「$text」"
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

function Read-Text([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return '' }
    return ([System.IO.File]::ReadAllText($path)).Trim()
}

function Get-Text([string]$url) {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5
    return [System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
}

# 主腳本的 Wait-Health 通過後（清掉 state\repair、開瀏覽器）才印這行，進入主機端動作迴圈
$RunningLine = 'vid-desk 執行中'

function Get-LauncherName($proc) {
    foreach ($l in @($Launchers)) { if ($l.Proc.Id -eq $proc.Id) { return $l.Name } }
    return ''
}

function Get-Count([string]$text, [string]$part) {
    $n = 0
    $i = $text.IndexOf($part)
    while ($i -ge 0) { $n++; $i = $text.IndexOf($part, $i + $part.Length) }
    return $n
}

# 等到 server.json 出現且其 port 的 /api/health 有回應，而且主腳本也已確認就緒
# （輸出出現第 $runs 次「vid-desk 執行中」），才回傳 server.json 內容。
# 只看健康檢查會搶在主腳本自己的 Wait-Health 之前，之後馬上送 shutdown 時主腳本會當成
# 「啟動中就被要求結束」，不會清掉 state\repair。
# $exceptPid：忽略這個 pid（更新後要等新的伺服器）；$runs：同一個啟動器第幾次就緒
function Wait-Server($proc, [int]$seconds, [int]$exceptPid = 0, [int]$runs = 1) {
    $info = Wait-Health $proc $seconds $exceptPid
    $name = Get-LauncherName $proc
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ((Get-Count (Get-LauncherOutput $name) $RunningLine) -lt $runs) {
        if ($proc.HasExited) { Fail "啟動器在主腳本就緒前結束，結束碼 $($proc.ExitCode)" }
        if ($sw.Elapsed.TotalSeconds -ge 30) {
            Fail "健康檢查通過後 30 秒，$name 的輸出仍沒有第 $runs 次「$RunningLine」"
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Host ("主腳本已就緒（再等 {0:N1} 秒）" -f $sw.Elapsed.TotalSeconds)
    return $info
}

function Wait-Health($proc, [int]$seconds, [int]$exceptPid) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $nextReport = 60
    while ($sw.Elapsed.TotalSeconds -lt $seconds) {
        if ($proc.HasExited) { Fail "啟動器在伺服器就緒前結束，結束碼 $($proc.ExitCode)" }
        $info = Read-ServerJson
        if ($info -and $info.pid -ne $exceptPid) {
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

function Invoke-Post([int]$port, [string]$path, [string]$json) {
    try {
        if ($json) {
            Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$port$path" `
                -Headers @{ 'X-Vid-Desk' = '1' } -ContentType 'application/json; charset=utf-8' `
                -Body ([System.Text.Encoding]::UTF8.GetBytes($json)) -TimeoutSec 10 | Out-Null
        } else {
            Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$port$path" `
                -Headers @{ 'X-Vid-Desk' = '1' } -TimeoutSec 10 | Out-Null
        }
    } catch {
        Fail "POST $path 失敗：$($_.Exception.Message)"
    }
    Write-Host "已送出 POST $path $json"
}

# 關閉伺服器並確認啟動器 30 秒內以 0 結束、伺服器行程消失
function Stop-AndVerify($proc, $info, [string]$label) {
    Invoke-Post $info.port '/api/shutdown' ''
    Wait-Exit $proc 30 $label
    Assert-ProcessGone $info.pid
}

# HKCU\Software\Python 底下與 uv（Astral）或 $Root 有關的登錄項目
function Get-UvRegistryEntries {
    $base = 'HKCU:\Software\Python'
    $hits = New-Object System.Collections.ArrayList
    if (-not (Test-Path -LiteralPath $base)) { return @() }
    foreach ($k in @(Get-ChildItem -LiteralPath $base -Recurse -ErrorAction SilentlyContinue)) {
        $values = @()
        try { $values = @($k.GetValueNames() | ForEach-Object { "$($k.GetValue($_))" }) } catch { }
        if ($k.Name -match 'Astral' -or (($values -join '|').IndexOf($Root, [StringComparison]::OrdinalIgnoreCase) -ge 0)) {
            [void]$hits.Add($k.Name)
        }
    }
    return @($hits)
}

# $dir 底下所有檔案的「相對路徑|大小」，用來確認沒有多下載檔案
function Get-FileList([string]$dir) {
    if (-not (Test-Path -LiteralPath $dir)) { return '' }
    $items = @(Get-ChildItem -LiteralPath $dir -Recurse -File -Force | ForEach-Object {
        "$($_.FullName.Substring($dir.Length))|$($_.Length)"
    } | Sort-Object)
    return ($items -join "`n")
}

# 用 http.server 假冒 GitHub 的 releases/latest：latest.json 的 tag_name 填這次測試的 sha
function Start-MockApi {
    Remove-IfExists $MockApiDir
    New-Item -ItemType Directory -Force -Path $MockApiDir | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $MockApiDir 'latest.json'),
        "{`"tag_name`": `"$Sha`", `"name`": `"vid-desk smoke`"}", (New-Object System.Text.UTF8Encoding($false)))
    $python = (Get-Command python).Source
    $script:MockApiServer = Start-Process -FilePath $python `
        -ArgumentList '-m', 'http.server', "$MockApiPort", '--bind', '127.0.0.1', '--directory', "`"$MockApiDir`"" `
        -PassThru -WindowStyle Hidden
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not (Get-NetTCPConnection -LocalPort $MockApiPort -State Listen -ErrorAction SilentlyContinue)) {
        if ($MockApiServer.HasExited -or $sw.Elapsed.TotalSeconds -ge 30) { Fail "無法在 $MockApiPort 啟動假的 releases/latest 端點" }
        Start-Sleep -Milliseconds 500
    }
    $got = ''
    try { $got = "$((ConvertFrom-Json (Get-Text $MockApi)).tag_name)" } catch { Fail "假端點 $MockApi 讀不到：$($_.Exception.Message)" }
    if ($got -ne $Sha) { Fail "假端點回傳 tag_name「$got」，預期 $Sha" }
    Write-Host "假的 releases/latest 已就緒：$MockApi → tag_name $got"
}

function Invoke-Robocopy([string]$from, [string]$to, [string[]]$extra) {
    $rcArgs = @($from, $to, '/E', '/NFL', '/NDL', '/NJH', '/NP', '/R:1', '/W:1') + $extra
    # 外部程式寫 stderr 時不要被 'Stop' 當成例外
    $ErrorActionPreference = 'Continue'
    & robocopy.exe @rcArgs | Out-Host
    $ErrorActionPreference = 'Stop'
    # robocopy 的結束碼 0–7 都是成功
    if ($LASTEXITCODE -ge 8) { Fail "robocopy $from → $to 失敗，結束碼 $LASTEXITCODE" }
}

# ── 準備 ────────────────────────────────────
Remove-IfExists $TestHome
New-Item -ItemType Directory -Force -Path $env:LOCALAPPDATA | Out-Null
Remove-IfExists $SmokeLogDir
New-Item -ItemType Directory -Force -Path $SmokeLogDir | Out-Null
Remove-IfExists $Backup
Remove-IfExists $DefaultOutputDir
[System.IO.File]::WriteAllText($EmptyInput, '')
Write-Host "LOCALAPPDATA = $env:LOCALAPPDATA"
Write-Host "USERPROFILE  = $env:USERPROFILE"
Write-Host "預設下載資料夾 = $DefaultOutputDir"
Write-Host "VS_SMOKE_SHA = $Sha"
if ($Sha -notmatch '^[0-9a-f]{40}$') { Fail "VS_SMOKE_SHA 必須是 40 碼 commit sha，目前為「$Sha」" }
$RegistryBefore = @(Get-UvRegistryEntries)
Write-Host "安裝前 HKCU\Software\Python 的 uv 項目：$($RegistryBefore.Count) 個"

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

$RegistryAfter = @(Get-UvRegistryEntries | Where-Object { $RegistryBefore -notcontains $_ })
if ($RegistryAfter.Count -gt 0) { Fail "uv 把 Python 登錄到 HKCU\Software\Python：$($RegistryAfter -join '，')" }
Write-Host 'HKCU\Software\Python 沒有新增 uv 的登錄項目'

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

# ── 4. 去人聲 ───────────────────────────────
# 用 vid_desk 自己的 remove_vocals 處理一段 2 秒的合成立體聲 WAV（不需網路），
# 確認執行期依賴齊全、產生非空的 _no_vocals.mp3，且不會再下載模型
Start-Scenario '4. 去人聲'
$venvPython = Join-Path $Root 'venv\Scripts\python.exe'
$vocalDir = Join-Path $TestHome '去人聲 測試'
Remove-IfExists $vocalDir
New-Item -ItemType Directory -Force -Path $vocalDir | Out-Null
$vocalScript = Join-Path $SmokeLogDir 'remove_vocals_check.py'
[System.IO.File]::WriteAllText($vocalScript, @'
import math, struct, sys, time, wave
from pathlib import Path

# 路徑含中文；輸出被導向時 Windows 預設 cp1252，print 會失敗
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from vid_desk.core import remove_vocals

work = Path(sys.argv[1])
src = work / "測試 歌曲.wav"
rate = 44100
with wave.open(str(src), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(rate)
    frames = bytearray()
    for i in range(rate * 2):
        t = i / rate
        left = 0.3 * math.sin(2 * math.pi * 220 * t) + 0.2 * math.sin(2 * math.pi * 440 * t)
        right = 0.3 * math.sin(2 * math.pi * 220 * t) + 0.2 * math.sin(2 * math.pi * 330 * t)
        frames += struct.pack("<hh", int(left * 32767), int(right * 32767))
    w.writeframes(bytes(frames))

start = time.monotonic()
out = remove_vocals(src, work)
elapsed = time.monotonic() - start
size = out.stat().st_size if out.exists() else -1
print(f"remove_vocals: {out} ({size} bytes, {elapsed:.1f} s)")
sys.exit(0 if size > 0 else 2)
'@, (New-Object System.Text.UTF8Encoding($false)))
$HfHome = Join-Path $Root 'huggingface'
$weights = @(Get-ChildItem -LiteralPath $HfHome -Recurse -File -Filter '*.safetensors' -ErrorAction SilentlyContinue)
if ($weights.Count -lt 4) { Fail "$HfHome 只有 $($weights.Count) 個 .safetensors（預期 htdemucs_ft 的 4 個已預載）" }
Write-Host "$HfHome 有 $($weights.Count) 個 .safetensors"
# 模型可能被寫到的所有快取：Hugging Face、torch hub（demucs 的舊來源）、XDG
$watchDirs = @($HfHome, $TorchDir, (Join-Path $Root 'cache-xdg'))
$filesBefore = ($watchDirs | ForEach-Object { "[$_]`n" + (Get-FileList $_) }) -join "`n"
# 與 vid-desk.ps1 的伺服器環境相同：bin\ 在 PATH 最前面（demucs 用 ffmpeg 讀檔）、
# TORCH_HOME / HF_HOME 在 $Root 底下、HF_HUB_OFFLINE=1（證明不需要網路）
$envNames = @('TORCH_HOME', 'HF_HOME', 'HF_HUB_OFFLINE', 'HF_HUB_DISABLE_SYMLINKS_WARNING')
$savedPath = $env:PATH
$env:PATH = "$(Join-Path $Root 'bin');$env:PATH"
$env:TORCH_HOME = $TorchDir
$env:HF_HOME = $HfHome
$env:HF_HUB_OFFLINE = '1'
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
$ErrorActionPreference = 'Continue'
# -I 會忽略 PYTHON* 環境變數，所以 UTF-8 由腳本自己設定
& $venvPython -I $vocalScript $vocalDir | Out-Host
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
# 還原環境，後面的啟動器才是在測 vid-desk.ps1 自己的設定
$env:PATH = $savedPath
foreach ($n in $envNames) { Remove-Item "Env:\$n" -ErrorAction SilentlyContinue }
if ($code -ne 0) { Fail "remove_vocals 失敗，結束碼 $code" }
$mp3 = @(Get-ChildItem -LiteralPath $vocalDir -Filter '*_no_vocals.mp3' -File)
if ($mp3.Count -ne 1 -or $mp3[0].Length -le 0) { Fail "$vocalDir 沒有非空的 _no_vocals.mp3" }
Write-Host "已產生 $($mp3[0].Name)（$($mp3[0].Length) bytes）"
$filesAfter = ($watchDirs | ForEach-Object { "[$_]`n" + (Get-FileList $_) }) -join "`n"
if ($filesAfter -ne $filesBefore) {
    Fail "去人聲時模型快取有變動（不應再下載）。之前：`n$filesBefore`n之後：`n$filesAfter"
}
Write-Host "$($watchDirs -join '、') 都沒有變動"
$profileCache = Join-Path $env:USERPROFILE '.cache'
if (Test-Path -LiteralPath $profileCache) { Fail "使用者資料夾出現 $profileCache（快取應放在 $Root）" }
Write-Host "使用者資料夾沒有 .cache"

# ── 5. 從 GitHub 取得原始碼 ─────────────────
Start-Scenario '5. 從 GitHub 取得原始碼'
Remove-Item Env:\VS_SOURCE
Start-MockApi
$env:VS_UPDATE_API = $MockApi
$fetch = Start-Launcher 'launcher-fetch'
$info5 = Wait-Server $fetch (15 * 60)
# 啟動器把假端點回的 tag_name（這裡是 sha）寫進 app\.commit；封存檔下載失敗時會退回本機原始碼，.commit 就不會是它
if ((Read-Text (Join-Path $AppDir '.commit')) -ne $Sha) { Fail "app\.commit 是「$(Read-Text (Join-Path $AppDir '.commit'))」，預期 $Sha（封存檔 github.com/irene-chou/vid-desk/archive/$Sha.zip 下載失敗？）" }
if (-not (Test-Path -LiteralPath (Join-Path $AppDir 'vid-desk.ps1'))) { Fail 'app\vid-desk.ps1 不存在' }
if ((Read-Text $CommitMarker) -ne $Sha) { Fail "state\installed-commit 是「$(Read-Text $CommitMarker)」，預期 $Sha" }
Write-Host "app\ 與 state\installed-commit 都是 $Sha"
Stop-AndVerify $fetch $info5 '取得原始碼的啟動器'
Assert-OutputContains 'launcher-fetch' '正在安裝新版'

# ── 6. 已是最新 ─────────────────────────────
Start-Scenario '6. 已是最新'
[System.IO.File]::WriteAllText($Sentinel, 'keep')
$same = Start-Launcher 'launcher-same'
$info6 = Wait-Server $same 120
Stop-AndVerify $same $info6 '已是最新的啟動器'
if (-not (Test-Path -LiteralPath $Sentinel)) { Fail 'app\ 被重新下載了（版本相同應跳過）' }
Assert-OutputLacks 'launcher-same' '正在安裝新版'

# ── 7. 離線再啟動 ───────────────────────────
Start-Scenario '7. 離線再啟動'
$env:VS_UPDATE_API = $OfflineApi
$offline = Start-Launcher 'launcher-offline'
$info7 = Wait-Server $offline 120
Stop-AndVerify $offline $info7 '離線啟動器'
if (-not (Test-Path -LiteralPath $Sentinel)) { Fail '離線時 app\ 不應變動' }
Assert-OutputLacks 'launcher-offline' '正在安裝新版'

# ── 8. 更新 ─────────────────────────────────
Start-Scenario '8. 更新'
$env:VS_UPDATE_API = $MockApi
$upd = Start-Launcher 'launcher-update'
$info8 = Wait-Server $upd 120
# #31：can_upgrade 已移除（#27 的「更新」鈕不再有）
$settings8 = Get-Text "http://127.0.0.1:$($info8.port)/api/settings"
if ($settings8 -match '"can_upgrade"') { Fail "GET /api/settings 不應再有 can_upgrade：$settings8" }
Invoke-Post $info8.port '/api/rebuild' ''
$info8b = Wait-Server $upd (20 * 60) $info8.pid 2
Assert-ProcessGone $info8.pid
if ((Read-Text $CommitMarker) -ne $Sha) { Fail "更新後 state\installed-commit 是「$(Read-Text $CommitMarker)」，預期 $Sha" }
Stop-AndVerify $upd $info8b '更新後的啟動器'
Assert-OutputContains 'launcher-update' '正在更新元件'

# ── 9. 標記檔觸發升級 ───────────────────────
Start-Scenario '9. 標記檔觸發升級'
# 後端在「自動更新下載工具後仍失敗」時會寫 config\upgrade-pending（#31）；這裡直接寫檔模擬。
# 啟動器查到的版本沒變（不會傳 -Upgrade），主腳本單靠標記就要走升級流程，升級後刪掉標記
New-Item -ItemType Directory -Force -Path (Split-Path $UpgradeMarker -Parent) | Out-Null
[System.IO.File]::WriteAllText($UpgradeMarker, '1')
$mark = Start-Launcher 'launcher-marker'
$info9 = Wait-Server $mark (20 * 60)
if (Test-Path -LiteralPath $UpgradeMarker) { Fail '升級後 config\upgrade-pending 應被刪除' }
if ((Read-Text $CommitMarker) -ne $Sha) { Fail "標記檔升級後 state\installed-commit 是「$(Read-Text $CommitMarker)」，預期 $Sha" }
Stop-AndVerify $mark $info9 '標記檔升級的啟動器'
Assert-OutputContains 'launcher-marker' '上次下載失敗，這次啟動會先更新所有元件'
Assert-OutputContains 'launcher-marker' '正在更新元件'
Write-Host 'config\upgrade-pending 已刪除'

# ── 10. 中斷續裝 ────────────────────────────
Start-Scenario '10. 中斷續裝'
Remove-IfExists (Join-Path $Root 'venv')
Remove-IfExists $CommitMarker
Write-Host '已刪除 venv 與 state\installed-commit'
$env:VS_SOURCE = 'local'
$resume = Start-Launcher 'launcher-resume'
$info10 = Wait-Server $resume (25 * 60)
Stop-AndVerify $resume $info10 '續裝啟動器'
Remove-Item Env:\VS_SOURCE

# ── 11. 啟動失敗後修復 ──────────────────────
Start-Scenario '11. 啟動失敗後修復'
# 模擬上次健康檢查失敗留下的狀態
Remove-IfExists $CommitMarker
[System.IO.File]::WriteAllText($RepairFlag, '1')
$env:VS_UPDATE_API = $OfflineApi
$repair = Start-Launcher 'launcher-repair'
$info11 = Wait-Server $repair (15 * 60)
Stop-AndVerify $repair $info11 '修復啟動器'
Assert-OutputContains 'launcher-repair' '正在修復元件'
if (Test-Path -LiteralPath $RepairFlag) { Fail '成功啟動後 state\repair 應被清掉' }
if ((Read-Text $CommitMarker) -ne $Sha) { Fail "修復後 state\installed-commit 是「$(Read-Text $CommitMarker)」，預期 $Sha" }
Write-Host 'state\repair 已清除，state\installed-commit 已寫回'

# 兩種解除安裝都要有完整安裝；先備份（不含最大的 uv 快取，啟動不需要它）
Write-Host ''
Write-Host "備份 $Root → $Backup"
Invoke-Robocopy $Root $Backup @('/XD', (Join-Path $Root 'cache'))

# ── 12. 解除安裝（自訂下載資料夾） ──────────
Start-Scenario '12. 解除安裝（自訂下載資料夾）'
New-Item -ItemType Directory -Force -Path $CustomOutputDir | Out-Null
$customFile = Join-Path $CustomOutputDir '歌曲.mp3'
[System.IO.File]::WriteAllText($customFile, 'x')
New-Item -ItemType Directory -Force -Path (Split-Path $ConfigFile -Parent) | Out-Null
[System.IO.File]::WriteAllText($ConfigFile, "output_dir=$CustomOutputDir`n")
$un1 = Start-Launcher 'launcher-uninstall-custom'
$info12 = Wait-Server $un1 120
$settings = Get-Text "http://127.0.0.1:$($info12.port)/api/settings"
Write-Host "GET /api/settings：$settings"
Invoke-Post $info12.port '/api/uninstall' '{"delete_downloads": true}'
Wait-Exit $un1 300 '解除安裝的啟動器'
Assert-ProcessGone $info12.pid
if (Test-Path -LiteralPath $Root) { Fail "解除安裝後 $Root 仍存在" }
if (-not (Test-Path -LiteralPath $customFile)) { Fail "自訂下載資料夾不應被刪除：$customFile" }
Assert-OutputContains 'launcher-uninstall-custom' '解除安裝完成'
Write-Host "$Root 已刪除，自訂下載資料夾保留"

# ── 13. 解除安裝（預設下載資料夾） ──────────
Start-Scenario '13. 解除安裝（預設下載資料夾）'
Invoke-Robocopy $Backup $Root @()
Remove-IfExists $ConfigFile
New-Item -ItemType Directory -Force -Path $DefaultOutputDir | Out-Null
[System.IO.File]::WriteAllText((Join-Path $DefaultOutputDir '歌曲.mp3'), 'x')
$un2 = Start-Launcher 'launcher-uninstall-default'
$info13 = Wait-Server $un2 120
Invoke-Post $info13.port '/api/uninstall' '{"delete_downloads": true}'
Wait-Exit $un2 300 '解除安裝的啟動器'
Assert-ProcessGone $info13.pid
if (Test-Path -LiteralPath $Root) { Fail "解除安裝後 $Root 仍存在" }
if (Test-Path -LiteralPath $DefaultOutputDir) { Fail "預設下載資料夾應被刪除：$DefaultOutputDir" }
Assert-OutputContains 'launcher-uninstall-default' '已刪除下載檔案'
Write-Host "$Root 與預設下載資料夾都已刪除"

if ($MockApiServer) { try { Stop-Process -Id $MockApiServer.Id -Force } catch { } }
Write-Host ''
Write-Host '全部情境通過'
exit 0
