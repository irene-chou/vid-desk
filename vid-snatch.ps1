# vid-snatch 一鍵啟動腳本 (Windows)
# 請雙擊 vid-snatch.bat，它會呼叫這個檔案。
# 注意：此檔需存成 UTF-8 with BOM，Windows PowerShell 5.1 才能正確讀取中文。

$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
Set-Location -LiteralPath $PSScriptRoot

$IMAGE_REMOTE = 'ghcr.io/irene-chou/vid-snatch:latest'
$IMAGE_LOCAL = 'vid-snatch'
$CONTAINER = 'vid-snatch'
$NameFilter = 'name=^' + $CONTAINER + '$'
$DEFAULT_PORT = 8080
$MAX_PORT = 8180
$Port = $DEFAULT_PORT
$ProjectDir = $PSScriptRoot
$Pickers = New-Object System.Collections.ArrayList

# ── 設定檔 ──────────────────────────────────
$ConfigDir = Join-Path $env:USERPROFILE '.config\vid-snatch'
$ConfigFile = Join-Path $ConfigDir 'config'
$DefaultOutputDir = Join-Path $env:USERPROFILE 'Music\vid-snatch'
$OutputDir = $DefaultOutputDir

function Get-CleanPath([string]$p) {
    $p = $p.Trim()
    # 去掉結尾的 \ 或 /（保留 C:\ 這種磁碟根目錄），避免 docker 參數的引號被跳脫
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

# ── Docker ──────────────────────────────────
function Ensure-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host '============================================'
        Write-Host '  需要先安裝 Docker Desktop'
        Write-Host '  下載：https://docker.com/products/docker-desktop/'
        Write-Host '============================================'
        Wait-AnyKey '按任意鍵開啟下載頁面...'
        Start-Process 'https://www.docker.com/products/docker-desktop/'
        exit 1
    }

    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '正在啟動 Docker Desktop...'
        $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
        try {
            if (Test-Path -LiteralPath $exe) { Start-Process -FilePath $exe }
            else { Start-Process 'Docker Desktop' }
        } catch { }
        $waited = 0
        $warned = $false
        do {
            Start-Sleep -Seconds 2
            $waited += 2
            Write-Host -NoNewline '.'
            if ($waited -gt 30 -and -not $warned) {
                $warned = $true
                Write-Host ''
                Write-Host '若 Docker Desktop 跳出同意條款視窗，請按 Accept'
            }
            docker info *> $null
        } while ($LASTEXITCODE -ne 0)
        Write-Host ''
        Write-Host 'Docker 已就緒！'
    }
}

function Get-WantArch {
    # 32 位元 PowerShell 跑在 64 位元 Windows 上時，真正的架構在 PROCESSOR_ARCHITEW6432
    $a = $env:PROCESSOR_ARCHITEW6432
    if (-not $a) { $a = $env:PROCESSOR_ARCHITECTURE }
    switch ($a) {
        'AMD64' { return 'amd64' }
        'ARM64' { return 'arm64' }
        default { return "$a".ToLower() }
    }
}

function Ensure-Image {
    Write-Host '正在檢查更新…'
    $want = Get-WantArch
    $pulled = $false
    docker pull $IMAGE_REMOTE *> $null
    if ($LASTEXITCODE -eq 0) {
        $arch = docker image inspect --format '{{.Architecture}}' $IMAGE_REMOTE 2>$null
        if ($LASTEXITCODE -eq 0 -and "$arch".Trim() -eq $want) { $pulled = $true }
    }

    if ($pulled) {
        docker tag $IMAGE_REMOTE $IMAGE_LOCAL *> $null
    } else {
        docker image inspect $IMAGE_LOCAL *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host ''
            Write-Host '首次使用，正在建置環境（約 3-5 分鐘）…'
            Write-Host ''
            docker build -t $IMAGE_LOCAL .
            Write-Host ''
            Write-Host '建置完成！'
        }
    }
}

function Test-ContainerRunning {
    $id = docker ps -q -f $NameFilter 2>$null
    return [bool]("$id".Trim())
}

function Read-Port {
    $lines = @(docker port $CONTAINER 8080 2>$null)
    if ($lines.Count -gt 0) {
        $first = "$($lines[0])".Trim()
        $p = $first.Substring($first.LastIndexOf(':') + 1)
        $n = 0
        if ([int]::TryParse($p, [ref]$n)) { return $n }
    }
    return $DEFAULT_PORT
}

function Test-PortInUse([int]$p) {
    return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Start-Container {
    if (Test-ContainerRunning) {
        $script:Port = Read-Port
        return $true
    }
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
        [void][System.IO.Directory]::CreateDirectory($ConfigDir)
    } catch {
        Write-Host "無法建立資料夾：$OutputDir"
        return $false
    }
    docker run -d --rm --name $CONTAINER -p "127.0.0.1:${p}:8080" `
        -v "${OutputDir}:/app/output" `
        -v "${ConfigDir}:/app/config" `
        -e "VS_HOST_OUTPUT_DIR=$OutputDir" `
        $IMAGE_LOCAL --web | Out-Null
    return ($LASTEXITCODE -eq 0)
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
    docker logs --tail 20 $CONTAINER
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

function Stop-VidSnatch {
    docker stop $CONTAINER *> $null
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
    Write-Host '移除 Docker 映像檔...'
    Stop-VidSnatch
    docker rmi $IMAGE_LOCAL $IMAGE_REMOTE *> $null
    docker builder prune -f *> $null
    Write-Host '移除設定檔...'
    if (Test-Path -LiteralPath $ConfigDir) {
        try {
            [System.IO.Directory]::Delete($ConfigDir, $true)
        } catch {
            Write-Host "無法刪除設定資料夾，請自行刪除：$ConfigDir"
        }
    }
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
    Write-Host ''
    Write-Host '============================================'
    Write-Host '  解除安裝完成！'
    Write-Host '  如需完全移除，可手動刪除此專案資料夾：'
    Write-Host "  $ProjectDir"
    Write-Host '============================================'
    Wait-AnyKey '按任意鍵關閉...'
    exit 0
}

function Invoke-Rebuild {
    Write-Host '正在更新…'
    Load-Config
    Stop-VidSnatch
    for ($w = 0; $w -lt 20; $w++) {
        $left = docker ps -aq -f $NameFilter 2>$null
        if (-not "$left".Trim()) { break }
        Start-Sleep -Milliseconds 500
    }
    docker rmi $IMAGE_LOCAL *> $null
    Ensure-Image
    if (-not (Start-Container)) {
        Write-Host '重新啟動失敗'
        docker logs --tail 20 $CONTAINER
        # 由 vid-snatch.bat 的 `if errorlevel 1 pause` 停住視窗
        exit 1
    }
    Wait-Health
    Open-Browser
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
        } elseif ($fails -ge 3 -and -not (Test-ContainerRunning)) {
            Write-Host 'vid-snatch 已停止。'
            exit 0
        }

        Clear-Pickers
        if (Wait-Enter 1000) { Open-Browser }
    }
}

# ── 主流程 ──────────────────────────────────
Load-Config
Ensure-Docker

if (Test-ContainerRunning) {
    $Port = Read-Port
    Write-Host 'vid-snatch 已經在執行中，已幫你打開瀏覽器。'
    Open-Browser
    exit 0
}

Ensure-Image
if (-not (Start-Container)) {
    Write-Host '啟動失敗，請把這個視窗的內容截圖給開發者'
    # 由 vid-snatch.bat 的 `if errorlevel 1 pause` 停住視窗
    exit 1
}

# Windows 沒有 trap：直接關閉視窗會砍掉這個程序，容器靠 15 秒心跳自行結束。
# Ctrl-C 與正常結束（含 exit）都會執行 finally，停止我們啟動的容器。
try {
    Wait-Health
    Open-Browser
    Invoke-HostLoop
} finally {
    Stop-VidSnatch
}
