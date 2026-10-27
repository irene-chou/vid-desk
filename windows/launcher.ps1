# vid-snatch 穩定啟動器 (Windows)
# 由 vid-snatch-Windows.bat 呼叫：把 GitHub latest 標籤（release.yml 每次 main 更新時移動）的原始碼放到 %LOCALAPPDATA%\vid-snatch\app\，
# 再執行那一份的 vid-snatch.ps1。這個檔案發佈後幾乎不會再更新，請保持精簡。
# 與 vid-snatch.ps1 的約定（見該檔開頭）：封存檔根目錄有 vid-snatch.ps1，接受 -Commit / -Upgrade，
# 結束碼 10 代表要更新，其他照原樣傳回給 .bat。
# 注意：此檔需存成 UTF-8 with BOM、CRLF，並相容 Windows PowerShell 5.1。

$ProgressPreference = 'SilentlyContinue'
# 讓 Move-Item 等的失敗都成為例外，才會被 try/catch 接住並改走備援路徑
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

$Repo = 'irene-chou/vid-snatch'
$Root = Join-Path $env:LOCALAPPDATA 'vid-snatch'
$AppDir = Join-Path $Root 'app'
# launcher.ps1 所在資料夾的上一層即原始碼資料夾（repo 根目錄，或下載包的 files\）
$BundleDir = Split-Path $PSScriptRoot -Parent
$UpdateApi = $env:VS_UPDATE_API
if (-not $UpdateApi) { $UpdateApi = "https://api.github.com/repos/$Repo/commits/latest" }

# 使用者看到的最外層資料夾（下載包配置為 files\ 的上一層），供主腳本顯示
$LaunchDir = $BundleDir
if ((Split-Path $LaunchDir -Leaf) -eq 'files') { $LaunchDir = Split-Path $LaunchDir -Parent }
$env:VS_LAUNCH_DIR = $LaunchDir

function Remove-IfExists([string]$path) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}

function Get-LatestCommit {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $UpdateApi -TimeoutSec 10 -UserAgent 'vid-snatch' `
        -Headers @{ Accept = 'application/vnd.github.sha' }
    $sha = ([System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())).Trim()
    if ($sha -notmatch '^[0-9a-f]{40}$') { throw "unexpected response: $sha" }
    return $sha
}

function Get-AppCommit {
    $file = Join-Path $AppDir '.commit'
    if (-not (Test-Path -LiteralPath $file)) { return '' }
    return ([System.IO.File]::ReadAllText($file)).Trim()
}

# 下載 $sha 的封存檔並換成新的 app\；失敗時清掉暫存並丟出例外，舊的 app\ 保持原樣
function Install-Source([string]$sha) {
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

        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$Repo/archive/$sha.zip" `
            -OutFile $part -TimeoutSec 300 -UserAgent 'vid-snatch'
        Move-Item -LiteralPath $part -Destination $zip
        Expand-Archive -LiteralPath $zip -DestinationPath $new

        # 封存檔內有一層 vid-snatch-<sha>\，取其內容
        $inner = @(Get-ChildItem -LiteralPath $new -Directory)
        if ($inner.Count -ne 1) { throw 'unexpected archive layout' }
        $src = $inner[0].FullName
        if (-not (Test-Path -LiteralPath (Join-Path $src 'vid-snatch.ps1'))) { throw 'vid-snatch.ps1 missing' }
        [System.IO.File]::WriteAllText((Join-Path $src '.commit'), $sha)

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

# 回傳 @{ Dir = 原始碼資料夾; Commit = sha 或 'local' }
function Get-SourceDir {
    if ($env:VS_SOURCE -eq 'local') { return @{ Dir = $BundleDir; Commit = 'local' } }

    Write-Host '正在檢查更新…'
    try {
        $sha = Get-LatestCommit
        # app\ 已是這個版本但主腳本不見了（被防毒或手動刪掉）也要重新下載
        if ($sha -ne (Get-AppCommit) -or -not (Test-Path -LiteralPath (Join-Path $AppDir 'vid-snatch.ps1'))) {
            Install-Source $sha
        }
        return @{ Dir = $AppDir; Commit = $sha }
    } catch {
        # 離線或下載失敗是正常情況，不印錯誤，改用既有的原始碼
    }

    if (Test-Path -LiteralPath (Join-Path $AppDir 'vid-snatch.ps1')) {
        $commit = Get-AppCommit
        if (-not $commit) { $commit = 'local' }
        return @{ Dir = $AppDir; Commit = $commit }
    }
    return @{ Dir = $BundleDir; Commit = 'local' }
}

# 主腳本結束碼：0 正常、1 失敗、10 要求更新（以 -Upgrade 重新取原始碼再執行）
# 連續要求更新最多 3 次，避免主腳本出錯時無限重來
$upgrade = $false
$rounds = 0
while ($true) {
    if ($rounds -ge 3) {
        Write-Host '更新沒有完成，請關閉此視窗後重新雙擊 vid-snatch-Windows.bat'
        exit 1
    }
    $source = Get-SourceDir
    $psArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $source.Dir 'vid-snatch.ps1'),
        '-Commit', $source.Commit)
    if ($upgrade) { $psArgs += '-Upgrade' }
    & powershell.exe @psArgs
    $code = $LASTEXITCODE
    if ($code -ne 10) { exit $code }
    $upgrade = $true
    $rounds++
}
