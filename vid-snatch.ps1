# vid-snatch 一鍵啟動腳本 (Windows)
# 請雙擊 vid-snatch.bat，它會呼叫這個檔案。
# 注意：此檔需存成 UTF-8 with BOM，Windows PowerShell 5.1 才能正確讀取中文。
# 由 windows\launcher.ps1 以 -Commit <sha 或 local>（及更新時的 -Upgrade）呼叫；
# 這個檔案所在的資料夾即要安裝的原始碼（含 pyproject.toml）。

param(
    [string]$Commit = 'local',
    [switch]$Upgrade
)

$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }
Set-Location -LiteralPath $PSScriptRoot

# ── 安裝目錄 ────────────────────────────────
$Root = Join-Path $env:LOCALAPPDATA 'vid-snatch'
$BinDir = Join-Path $Root 'bin'
$UvExe = Join-Path $BinDir 'uv.exe'
$PythonDir = Join-Path $Root 'python'
$CacheDir = Join-Path $Root 'cache'
$VenvDir = Join-Path $Root 'venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$VenvExe = Join-Path $VenvDir 'Scripts\vid-snatch.exe'
$TorchDir = Join-Path $Root 'torch'
$ModelFile = Join-Path $TorchDir 'hub\checkpoints\955717e8-8726e21a.th'
$StateDir = Join-Path $Root 'state'
$CommitMarker = Join-Path $StateDir 'installed-commit'
$LogDir = Join-Path $Root 'logs'
$ServerLog = Join-Path $LogDir 'server.log'
$ServerErrLog = Join-Path $LogDir 'server.err.log'
$ServerFile = Join-Path $Root 'server.json'

$DEFAULT_PORT = 8080
$MAX_PORT = 8180
$Port = $DEFAULT_PORT
$Pickers = New-Object System.Collections.ArrayList

# ── 設定檔 ──────────────────────────────────
$ConfigDir = Join-Path $Root 'config'
$ConfigFile = Join-Path $ConfigDir 'config'
$DefaultOutputDir = Join-Path $env:USERPROFILE 'Music\vid-snatch'
$OutputDir = $DefaultOutputDir

function Get-CleanPath([string]$p) {
    $p = $p.Trim()
    # 去掉結尾的 \ 或 /（保留 C:\ 這種磁碟根目錄），路徑比對與顯示才一致
    while ($p.Length -gt 3 -and ($p.EndsWith('\') -or $p.EndsWith('/'))) {
        $p = $p.Substring(0, $p.Length - 1)
    }
    return $p
}

function Load-Config {
    $script:OutputDir = $DefaultOutputDir
    if (Test-Path -LiteralPath $ConfigFile) {
        foreach ($line in @(Get-Content -LiteralPath $ConfigFile -Encoding UTF8)) {
            if ("$line".StartsWith('output_dir=')) {
                $saved = "$line".Substring(11).Trim()
                if ($saved) {
                    # 展開 ~ 為使用者資料夾
                    if ($saved.StartsWith('~')) { $saved = $env:USERPROFILE + $saved.Substring(1) }
                    $script:OutputDir = Get-CleanPath $saved
                }
                break
            }
        }
    }
}

function Wait-AnyKey([string]$msg) {
    Write-Host -NoNewline $msg
    try { [void][Console]::ReadKey($true) } catch { [void](Read-Host) }
    Write-Host ''
}

# ── 安裝 ────────────────────────────────────
$UvUrl = 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip'
$DenoUrl = 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip'
$FfmpegUrl = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'
$ModelUrl = 'https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th'
$RetryHint = '請確認網路連線後重新雙擊 vid-snatch-Windows.bat'

function Remove-IfExists([string]$path) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop }
}

function Assert-SupportedArch {
    # 32 位元 PowerShell 跑在 64 位元 Windows 上時，真正的架構在 PROCESSOR_ARCHITEW6432
    if ($env:PROCESSOR_ARCHITEW6432 -eq 'ARM64' -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
        Write-Host '目前不支援 ARM 版 Windows'
        exit 1
    }
}

# 先寫到 <目標>.part，完成後才改名，中斷時不會留下看似完整的檔案
function Save-Download([string]$Url, [string]$Dest, [string]$Label) {
    Write-Host "正在下載 $Label…"
    $part = "$Dest.part"
    try {
        [void][System.IO.Directory]::CreateDirectory((Split-Path $Dest -Parent))
        Remove-IfExists $part
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $part -TimeoutSec 600 -UserAgent 'vid-snatch' -ErrorAction Stop
        Move-Item -LiteralPath $part -Destination $Dest -Force -ErrorAction Stop
    } catch {
        try { Remove-IfExists $part } catch { }
        Write-Host ''
        Write-Host "下載失敗，$RetryHint"
        exit 1
    }
}

# 下載 zip、從中找出 $ExeNames 這幾個檔案放進 bin\（ffmpeg 的 zip 內為 <資料夾>\bin\ffmpeg.exe）
function Install-ZipTool([string]$Url, [string]$Label, [string]$Key, [string[]]$ExeNames) {
    $tmp = Join-Path $Root "tmp-$Key"
    $zip = Join-Path $tmp "$Key.zip"
    $out = Join-Path $tmp 'out'
    try {
        try { Remove-IfExists $tmp } catch { }
        Save-Download $Url $zip $Label
        try {
            Expand-Archive -LiteralPath $zip -DestinationPath $out -Force -ErrorAction Stop
            [void][System.IO.Directory]::CreateDirectory($BinDir)
            foreach ($name in $ExeNames) {
                $found = @(Get-ChildItem -LiteralPath $out -Recurse -File -Filter $name -ErrorAction Stop)
                if ($found.Count -lt 1) { throw "$name not found in archive" }
                $dest = Join-Path $BinDir $name
                Copy-Item -LiteralPath $found[0].FullName -Destination "$dest.part" -Force -ErrorAction Stop
                Move-Item -LiteralPath "$dest.part" -Destination $dest -Force -ErrorAction Stop
            }
        } catch {
            Write-Host ''
            Write-Host "無法安裝 $Label，$RetryHint"
            exit 1
        }
    } finally {
        try { Remove-IfExists $tmp } catch { }
    }
}

function Set-InstallEnv {
    # PATH 只在本行程內前置 bin\，不修改系統或使用者設定
    if (-not ("$env:PATH".StartsWith("$BinDir;"))) { $env:PATH = "$BinDir;$env:PATH" }
    $env:TORCH_HOME = $TorchDir
    $env:UV_PYTHON_INSTALL_DIR = $PythonDir
    $env:UV_CACHE_DIR = $CacheDir
    # 一律用 uv 自己下載的 Python，避免日後移除系統 Python 時 venv 跟著壞掉
    $env:UV_PYTHON_PREFERENCE = 'only-managed'
}

function Install-Packages([string[]]$Extra) {
    $uvArgs = @('pip', 'install', '--python', $VenvPython) + $Extra + @($PSScriptRoot)
    & $UvExe @uvArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host "安裝元件失敗，$RetryHint"
        Write-Host '若仍然失敗，請把這個視窗的內容截圖給開發者'
        exit 1
    }
}

# 結束後保證 bin\ 四個執行檔、venv 內的 vid-snatch、去人聲模型都在，且本行程環境變數已設好
function Ensure-Installed([string]$Commit, [switch]$Upgrade) {
    Assert-SupportedArch
    Set-InstallEnv

    if (-not (Test-Path -LiteralPath $UvExe)) {
        Install-ZipTool $UvUrl '安裝工具 uv' 'uv' @('uv.exe')
    }
    if (-not (Test-Path -LiteralPath (Join-Path $BinDir 'ffmpeg.exe')) -or
        -not (Test-Path -LiteralPath (Join-Path $BinDir 'ffprobe.exe'))) {
        Install-ZipTool $FfmpegUrl '影音工具 ffmpeg' 'ffmpeg' @('ffmpeg.exe', 'ffprobe.exe')
    }
    # yt-dlp 靠 deno 解 YouTube 驗證，更新時一併換成最新版
    if ($Upgrade -or -not (Test-Path -LiteralPath (Join-Path $BinDir 'deno.exe'))) {
        Install-ZipTool $DenoUrl '執行環境 deno' 'deno' @('deno.exe')
    }

    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Host '正在準備 Python 環境…'
        try {
            # 殘缺的 venv 與其安裝紀錄一起清掉，下面會重新完整安裝
            Remove-IfExists $VenvDir
            Remove-IfExists $CommitMarker
        } catch {
            Write-Host "無法清除舊的 Python 環境，請自行刪除後再試：$VenvDir"
            exit 1
        }
        & $UvExe venv --seed --python 3.12 $VenvDir
        if ($LASTEXITCODE -ne 0) {
            Write-Host ''
            Write-Host "準備 Python 環境失敗，$RetryHint"
            exit 1
        }
    }

    $installed = $null
    if (Test-Path -LiteralPath $CommitMarker) {
        $installed = ([System.IO.File]::ReadAllText($CommitMarker)).Trim()
    }
    $changed = $false
    if ($null -eq $installed) {
        Write-Host ''
        Write-Host '正在安裝去人聲元件（約 1 GB，約 5–10 分鐘）…'
        Install-Packages @()
        $changed = $true
    } elseif ($Upgrade) {
        Write-Host '正在更新元件…'
        Install-Packages @('--upgrade', '--reinstall-package', 'vid-snatch')
        $changed = $true
    } elseif ($installed -ne $Commit -or $Commit -eq 'local' -or -not (Test-Path -LiteralPath $VenvExe)) {
        Write-Host '正在安裝新版 vid-snatch…'
        Install-Packages @('--reinstall-package', 'vid-snatch')
        $changed = $true
    }
    if ($changed) {
        try {
            [void][System.IO.Directory]::CreateDirectory($StateDir)
            [System.IO.File]::WriteAllText($CommitMarker, $Commit)
        } catch {
            Write-Host "無法寫入安裝紀錄：$CommitMarker"
            exit 1
        }
    }

    if (-not (Test-Path -LiteralPath $ModelFile)) {
        Save-Download $ModelUrl $ModelFile '去人聲模型（約 80 MB）'
    }
}

# 回傳 @{ Id = 伺服器行程 pid; Port = 連接埠 }；沒有或讀不到 server.json 時回傳 $null
function Read-ServerInfo {
    if (-not (Test-Path -LiteralPath $ServerFile)) { return $null }
    try {
        $info = ConvertFrom-Json ([System.IO.File]::ReadAllText($ServerFile))
        return @{ Id = [int]$info.pid; Port = [int]$info.port }
    } catch {
        return $null
    }
}

# pid 的行程存在、且 /api/health 有回應才算在跑（避免 pid 被別的行程重用）
function Test-ServerRunning {
    $info = Read-ServerInfo
    if (-not $info) { return $false }
    if (-not (Get-Process -Id $info.Id -ErrorAction SilentlyContinue)) { return $false }
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$($info.Port)/api/health" -TimeoutSec 2 | Out-Null
    } catch {
        return $false
    }
    $script:Port = $info.Port
    return $true
}

function Test-PortInUse([int]$p) {
    return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Start-Server {
    $p = $DEFAULT_PORT
    while (Test-PortInUse $p) {
        $p++
        if ($p -gt $MAX_PORT) {
            Write-Host "找不到可用的連接埠（$DEFAULT_PORT-$MAX_PORT 都被占用）"
            return $false
        }
    }
    $script:Port = $p
    try {
        [void][System.IO.Directory]::CreateDirectory($OutputDir)
    } catch {
        Write-Host "無法建立資料夾：$OutputDir"
        return $false
    }
    try {
        [void][System.IO.Directory]::CreateDirectory($ConfigDir)
        [void][System.IO.Directory]::CreateDirectory($LogDir)
    } catch {
        Write-Host "無法建立資料夾：$Root"
        return $false
    }
    $env:VS_OUTPUT_DIR = $OutputDir
    $env:VS_HOST_OUTPUT_DIR = $OutputDir
    $env:VS_CONFIG_DIR = $ConfigDir
    $env:VS_BIND = '127.0.0.1'
    try {
        $proc = Start-Process -WindowStyle Hidden -FilePath $VenvExe -ArgumentList @('--web', '--port', "$p") `
            -RedirectStandardOutput $ServerLog -RedirectStandardError $ServerErrLog -PassThru -ErrorAction Stop
    } catch {
        Write-Host "無法啟動 vid-snatch：$VenvExe"
        return $false
    }
    try {
        $json = ConvertTo-Json @{ pid = $proc.Id; port = $p } -Compress
        [System.IO.File]::WriteAllText($ServerFile, $json)
    } catch {
        # 沒有 server.json 就無法在結束時停止伺服器，所以直接停掉
        try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch { }
        Write-Host "無法寫入伺服器紀錄：$ServerFile"
        return $false
    }
    return $true
}

# Windows PowerShell 5.1 的 Invoke-RestMethod 在回應沒有標 charset 時會用 ISO-8859-1 解碼，
# 中文路徑會變亂碼；所以改用 Invoke-WebRequest 取原始位元組，自己用 UTF-8 解碼。
function Invoke-ApiGet([string]$path, [int]$timeout) {
    $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port$path" -TimeoutSec $timeout
    $text = [System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
    return (ConvertFrom-Json $text)
}

function Wait-Health {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt 60) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 | Out-Null
            return
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    Write-Host ''
    Write-Host '啟動失敗，請把這個視窗的內容截圖給開發者'
    Write-Host ''
    if (Test-Path -LiteralPath $ServerErrLog) {
        Get-Content -LiteralPath $ServerErrLog -Tail 20 -Encoding UTF8 -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host $_ }
    }
    Write-Host ''
    # 由 vid-snatch.bat 的 `if errorlevel 1 pause` 停住視窗
    exit 1
}

function Open-Browser {
    $url = "http://localhost:$Port"
    if ($env:VS_NO_BROWSER -eq '1') {
        Write-Host $url
    } else {
        Start-Process $url
    }
}

# 伺服器行程與其所有子孫行程（Python、deno、ffmpeg…）的 pid
function Get-ProcessTreeIds([int]$rootId) {
    $ids = New-Object System.Collections.ArrayList
    [void]$ids.Add($rootId)
    try {
        $all = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
        $i = 0
        while ($i -lt $ids.Count) {
            foreach ($p in $all) {
                $childId = [int]$p.ProcessId
                if ([int]$p.ParentProcessId -eq $ids[$i] -and -not $ids.Contains($childId)) {
                    [void]$ids.Add($childId)
                }
            }
            $i++
        }
    } catch { }
    return @($ids)
}

# 停止伺服器並等到行程真的結束（更新時要覆寫 deno.exe 與 venv）；停不掉時回傳 $false 並保留 server.json
function Stop-VidSnatch {
    $info = Read-ServerInfo
    if ($info) {
        $main = Get-Process -Id $info.Id -ErrorAction SilentlyContinue
        # 行程名稱不符代表伺服器早已結束、pid 被別的程式重用，不能動它
        if ($main -and $main.ProcessName -eq 'vid-snatch') {
            $procs = @(Get-Process -Id (Get-ProcessTreeIds $info.Id) -ErrorAction SilentlyContinue)
            foreach ($proc in $procs) {
                try { Stop-Process -InputObject $proc -Force -ErrorAction SilentlyContinue } catch { }
            }
            foreach ($proc in $procs) {
                try {
                    if (-not $proc.WaitForExit(15000)) { return $false }
                } catch { }
            }
        }
    }
    try {
        if (Test-Path -LiteralPath $ServerFile) { Remove-Item -LiteralPath $ServerFile -Force -ErrorAction Stop }
    } catch { }
    return $true
}

# ── 主機端動作 ──────────────────────────────
function Invoke-Reveal([string]$path) {
    if (-not $path) { return }
    if (Test-Path -LiteralPath $path) {
        # 官方文件格式：explorer /select,"<路徑>"。Start-Process 的單一字串參數會原樣放進命令列。
        Start-Process -FilePath 'explorer.exe' -ArgumentList ('/select,"' + $path + '"')
    } else {
        $dir = [System.IO.Path]::GetDirectoryName($path)
        if ($dir -and (Test-Path -LiteralPath $dir)) {
            Start-Process -FilePath 'explorer.exe' -ArgumentList ('"' + $dir + '"')
        }
    }
}

# 資料夾對話框在獨立的 STA runspace 執行，開著時主迴圈照常輪詢（維持心跳）。
# 以字串傳入，避免 scriptblock 綁定主 runspace。
$PickFolderScript = @'
param($port, $id)
$ProgressPreference = 'SilentlyContinue'
$picked = $null
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    # 看不見的置頂視窗當擁有者，讓對話框出現在瀏覽器前面
    $owner = New-Object System.Windows.Forms.Form
    $owner.TopMost = $true
    $owner.ShowInTaskbar = $false
    $owner.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
    $owner.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
    $wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $owner.Location = New-Object System.Drawing.Point(([int]($wa.X + $wa.Width / 2)), ([int]($wa.Y + $wa.Height / 2)))
    $owner.Size = New-Object System.Drawing.Size(1, 1)
    $owner.Opacity = 0
    $owner.Show()
    $owner.Activate()
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = '選擇下載資料夾'
    $dlg.ShowNewFolderButton = $true
    if ($dlg.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK -and $dlg.SelectedPath) {
        $picked = $dlg.SelectedPath
    }
    $dlg.Dispose()
    $owner.Close()
    $owner.Dispose()
} catch {
    $picked = $null
}
$json = ConvertTo-Json @{ path = $picked } -Compress
$bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
try {
    Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$port/api/host-actions/$id/result" `
        -Headers @{ 'X-Vid-Snatch' = '1' } -ContentType 'application/json; charset=utf-8' `
        -Body $bytes -TimeoutSec 5 | Out-Null
} catch { }
'@

function Start-PickFolder([string]$id) {
    $rs = [runspacefactory]::CreateRunspace()
    $rs.ApartmentState = [System.Threading.ApartmentState]::STA
    $rs.ThreadOptions = [System.Management.Automation.Runspaces.PSThreadOptions]::ReuseThread
    $rs.Open()
    $ps = [powershell]::Create()
    $ps.Runspace = $rs
    [void]$ps.AddScript($PickFolderScript).AddArgument($Port).AddArgument($id)
    $handle = $ps.BeginInvoke()
    [void]$script:Pickers.Add(@{ PS = $ps; Runspace = $rs; Handle = $handle })
}

function Clear-Pickers {
    foreach ($job in @($script:Pickers)) {
        if ($job.Handle.IsCompleted) {
            try { [void]$job.PS.EndInvoke($job.Handle) } catch { }
            $job.PS.Dispose()
            $job.Runspace.Dispose()
            $script:Pickers.Remove($job)
        }
    }
}

function Invoke-Uninstall($deleteDownloads) {
    Write-Host ''
    Write-Host '正在移除 vid-snatch…'
    [void](Stop-VidSnatch)
    # 這個腳本本身就在要刪除的資料夾裡，先離開，避免目前目錄鎖住資料夾
    Set-Location -LiteralPath $env:TEMP
    if ($deleteDownloads -eq $true) {
        $out = "$OutputDir".TrimEnd('\')
        $def = "$DefaultOutputDir".TrimEnd('\')
        if ($out -and ($out -ieq $def)) {
            $deleted = $true
            if (Test-Path -LiteralPath $out) {
                try {
                    [System.IO.Directory]::Delete($out, $true)
                } catch {
                    $deleted = $false
                    Write-Host "無法刪除下載資料夾，請自行刪除：$out"
                }
            }
            if ($deleted) { Write-Host '已刪除下載檔案。' }
        } else {
            Write-Host "下載資料夾不是預設位置，為了安全不會自動刪除，如需要請自行刪除：$OutputDir"
        }
    }
    if (Test-Path -LiteralPath $Root) {
        try {
            [System.IO.Directory]::Delete($Root, $true)
        } catch {
            Write-Host "無法刪除安裝資料夾，請自行刪除：$Root"
        }
    }
    Write-Host ''
    Write-Host '============================================'
    Write-Host '  解除安裝完成！'
    Write-Host '  如需完全移除，可刪除你解壓縮的 vid-snatch 資料夾：'
    if ($env:VS_LAUNCH_DIR) { Write-Host "  $env:VS_LAUNCH_DIR" }
    Write-Host '============================================'
    Wait-AnyKey '按任意鍵關閉...'
    exit 0
}

# 結束碼 10 請啟動器重新取得最新原始碼並以 -Upgrade 執行；只有使用者按「更新」才會走到這裡
function Invoke-Rebuild {
    Write-Host '正在更新…'
    if (-not (Stop-VidSnatch)) {
        Write-Host '無法停止 vid-snatch，請關閉此視窗後重新雙擊 vid-snatch-Windows.bat'
        # 由 vid-snatch.bat 的 `if errorlevel 1 pause` 停住視窗
        exit 1
    }
    exit 10
}

# 等待最多 $ms 毫秒；期間按下 Enter 回傳 $true
function Wait-Enter([int]$ms) {
    $hit = $false
    $useConsole = $true
    $deadline = [DateTime]::UtcNow.AddMilliseconds($ms)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($useConsole) {
            try {
                while ([Console]::KeyAvailable) {
                    $k = [Console]::ReadKey($true)
                    if ($k.Key -eq [ConsoleKey]::Enter) { $hit = $true }
                }
            } catch {
                # 標準輸入被重新導向時沒有主控台可讀
                $useConsole = $false
            }
        }
        if ($hit) { break }
        Start-Sleep -Milliseconds 100
    }
    return $hit
}

function Invoke-HostLoop {
    Write-Host ''
    Write-Host 'vid-snatch 執行中，操作請看瀏覽器視窗。誤關了？按 Enter 重新開啟。關閉此視窗即結束。'

    $fails = 0
    while ($true) {
        $resp = $null
        try {
            $resp = Invoke-ApiGet '/api/host-actions' 3
            $fails = 0
        } catch {
            $resp = $null
            $fails++
        }

        if ($resp) {
            foreach ($a in @($resp.actions)) {
                if (-not $a -or -not $a.id) { continue }
                switch ([string]$a.kind) {
                    'reveal'      { Invoke-Reveal ([string]$a.payload.path) }
                    'pick_folder' { Start-PickFolder ([string]$a.id) }
                    'shutdown'    { exit 0 }
                    'rebuild'     { Invoke-Rebuild }
                    'uninstall'   { Invoke-Uninstall $a.payload.delete_downloads }
                }
            }
        } elseif ($fails -ge 3 -and -not (Test-ServerRunning)) {
            Write-Host 'vid-snatch 已停止。'
            exit 0
        }

        Clear-Pickers
        if (Wait-Enter 1000) { Open-Browser }
    }
}

# ── 主流程 ──────────────────────────────────
Load-Config

# 要在 Ensure-Installed 之前檢查，才不會在伺服器運作中重裝套件
if (Test-ServerRunning) {
    Write-Host 'vid-snatch 已經在執行中，已幫你打開瀏覽器。'
    Open-Browser
    exit 0
}

Ensure-Installed $Commit -Upgrade:$Upgrade
if (-not (Start-Server)) {
    Write-Host '啟動失敗，請把這個視窗的內容截圖給開發者'
    # 由 vid-snatch.bat 的 `if errorlevel 1 pause` 停住視窗
    exit 1
}

# Windows 沒有 trap：直接關閉視窗會砍掉這個程序，伺服器靠 15 秒心跳自行結束。
# Ctrl-C 與正常結束（含 exit）都會執行 finally，停止我們啟動的伺服器。
try {
    Wait-Health
    Open-Browser
    Invoke-HostLoop
} finally {
    [void](Stop-VidSnatch)
}
