# vid-desk 穩定啟動器 (Windows)
# 由 vid-desk-Windows.bat 呼叫：把 GitHub 最新 release（推 v* 標籤時由 release.yml 建立）的原始碼放到
# %LOCALAPPDATA%\vid-desk\app\，再執行那一份的 vid-desk.ps1。這個檔案發佈後幾乎不會再更新，請保持精簡。
# 與 vid-desk.ps1 的約定（見該檔開頭）：封存檔根目錄有 vid-desk.ps1，接受 -Commit / -Upgrade，
# 結束碼 10 代表要更新，其他照原樣傳回給 .bat。
# 舊版啟動器查的是 git 標籤 latest 指到的 commit sha；release.yml 發版時仍會移動該標籤，所以舊版也只在發版時更新。
# 注意：此檔需存成 UTF-8 with BOM、CRLF，並相容 Windows PowerShell 5.1。

$ProgressPreference = 'SilentlyContinue'
# 讓 Move-Item 等的失敗都成為例外，才會被 try/catch 接住並改走備援路徑
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

$Repo = 'irene-chou/vid-desk'
$Root = Join-Path $env:LOCALAPPDATA 'vid-desk'
$AppDir = Join-Path $Root 'app'
# launcher.ps1 所在資料夾的上一層即原始碼資料夾（repo 根目錄，或下載包的 files\）
$BundleDir = Split-Path $PSScriptRoot -Parent
# 回傳 JSON，取其中的 tag_name（例如 v0.3.0）；CI 冒煙測試用 VS_UPDATE_API 換成本機假端點
$UpdateApi = $env:VS_UPDATE_API
if (-not $UpdateApi) { $UpdateApi = "https://api.github.com/repos/$Repo/releases/latest" }

# 使用者看到的最外層資料夾（下載包配置為 files\ 的上一層），供主腳本顯示
$LaunchDir = $BundleDir
if ((Split-Path $LaunchDir -Leaf) -eq 'files') { $LaunchDir = Split-Path $LaunchDir -Parent }
$env:VS_LAUNCH_DIR = $LaunchDir

function Remove-IfExists([string]$path) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}

# 最新 release 的標籤名稱（例如 v0.3.0）；只接受能直接放進網址與檔名的字元
function Get-LatestTag {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $UpdateApi -TimeoutSec 10 -UserAgent 'vid-desk' `
        -Headers @{ Accept = 'application/vnd.github+json' }
    $json = [System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
    $tag = "$((ConvertFrom-Json $json).tag_name)".Trim()
    if ($tag -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$') { throw "unexpected tag_name: $tag" }
    return $tag
}

# app\.commit：上次安裝的版本（新版啟動器寫標籤名稱；舊版寫 40 碼 sha，第一次會被視為不同版本而重裝一次）
function Get-AppCommit {
    $file = Join-Path $AppDir '.commit'
    if (-not (Test-Path -LiteralPath $file)) { return '' }
    return ([System.IO.File]::ReadAllText($file)).Trim()
}

# 下載 $tag 的封存檔並換成新的 app\；失敗時清掉暫存並丟出例外，舊的 app\ 保持原樣
function Install-Source([string]$tag) {
    $zip = Join-Path $Root 'app.zip'
    $part = "$zip.part"
    $new = Join-Path $Root 'app.new'
    $old = Join-Path $Root 'app.old'
    try {
        New-Item -ItemType Directory -Force -Path $Root | Out-Null
        Remove-IfExists $part
        Remove-IfExists $zip
        Remove-IfExists $new
        Remove-IfExists $old

        # archive/<ref>.zip 接受標籤名稱或 commit sha（CI 冒煙測試傳的是 sha），不走 API、沒有流量限制
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$Repo/archive/$tag.zip" `
            -OutFile $part -TimeoutSec 300 -UserAgent 'vid-desk'
        Move-Item -LiteralPath $part -Destination $zip
        Expand-Archive -LiteralPath $zip -DestinationPath $new

        # 封存檔內有一層 vid-desk-<版本>\（標籤 v0.3.0 會是 vid-desk-0.3.0），取其內容
        $inner = @(Get-ChildItem -LiteralPath $new -Directory)
        if ($inner.Count -ne 1) { throw 'unexpected archive layout' }
        $src = $inner[0].FullName
        if (-not (Test-Path -LiteralPath (Join-Path $src 'vid-desk.ps1'))) { throw 'vid-desk.ps1 missing' }
        [System.IO.File]::WriteAllText((Join-Path $src '.commit'), $tag)

        # 先把舊版移開再換上新版，換不成就還原，避免留下半刪的 app\
        if (Test-Path -LiteralPath $AppDir) { Move-Item -LiteralPath $AppDir -Destination $old }
        try {
            Move-Item -LiteralPath $src -Destination $AppDir
        } catch {
            if (Test-Path -LiteralPath $old) { Move-Item -LiteralPath $old -Destination $AppDir }
            throw
        }
    } finally {
        foreach ($p in @($part, $zip, $new, $old)) {
            try { Remove-IfExists $p } catch { }
        }
    }
}

# 回傳 @{ Dir = 原始碼資料夾; Commit = 標籤名稱、舊安裝留下的 sha，或 'local' }
function Get-SourceDir {
    if ($env:VS_SOURCE -eq 'local') { return @{ Dir = $BundleDir; Commit = 'local' } }

    Write-Host '正在檢查更新…'
    try {
        $tag = Get-LatestTag
        # app\ 已是這個版本但主腳本不見了（被防毒或手動刪掉）也要重新下載
        if ($tag -ne (Get-AppCommit) -or -not (Test-Path -LiteralPath (Join-Path $AppDir 'vid-desk.ps1'))) {
            Install-Source $tag
        }
        return @{ Dir = $AppDir; Commit = $tag }
    } catch {
        # 離線或下載失敗是正常情況，不印錯誤，改用既有的原始碼
    }

    if (Test-Path -LiteralPath (Join-Path $AppDir 'vid-desk.ps1')) {
        $commit = Get-AppCommit
        if (-not $commit) { $commit = 'local' }
        return @{ Dir = $AppDir; Commit = $commit }
    }
    return @{ Dir = $BundleDir; Commit = 'local' }
}

# 主腳本結束碼：0 正常、1 失敗、10 要求更新（以 -Upgrade 重新取原始碼再執行）
# 連續快速要求更新最多 3 次，避免主腳本出錯時無限重來；
# 上一輪執行超過 60 秒（正常使用後才按更新）就重新計數
$upgrade = $false
$rounds = 0
while ($true) {
    if ($rounds -ge 3) {
        Write-Host '更新沒有完成，請關閉此視窗後重新雙擊 vid-desk-Windows.bat'
        exit 1
    }
    $source = Get-SourceDir
    $psArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $source.Dir 'vid-desk.ps1'),
        '-Commit', $source.Commit)
    if ($upgrade) { $psArgs += '-Upgrade' }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    & powershell.exe @psArgs
    $code = $LASTEXITCODE
    if ($code -ne 10) { exit $code }
    $upgrade = $true
    if ($sw.Elapsed.TotalSeconds -gt 60) { $rounds = 1 } else { $rounds++ }
}
