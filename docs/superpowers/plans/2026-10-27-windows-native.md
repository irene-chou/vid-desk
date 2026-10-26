# Windows 原生執行 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Windows 使用者雙擊 `vid-snatch.bat` 即可使用 vid-snatch，不需要 Docker、虛擬化或管理員權限。

**Architecture:** `vid-snatch.bat` 呼叫一個穩定的小啟動器 `windows/launcher.ps1`。啟動器負責從 GitHub `main` 取得最新原始碼（含主腳本），放到 `%LOCALAPPDATA%\vid-snatch\app\`，再執行那一份 `vid-snatch.ps1`。主腳本用 uv 裝好 Python 環境與工具，以隱藏背景行程啟動 Python 伺服器，並沿用既有的 host action 主迴圈與心跳協定；Python 端與網頁不改，只多一個綁定位址的環境變數。

**Tech Stack:** Windows PowerShell 5.1、uv、Python 3.12、ffmpeg（BtbN 建置）、deno、GitHub Actions `windows-latest`。

**Spec:** `docs/superpowers/specs/2026-10-27-windows-native-design.md`（建立在 `docs/superpowers/specs/2026-10-26-web-ui-design.md` 之上）

## Global Constraints

- 所有 `.ps1` 存成 **UTF-8 with BOM**、CRLF（`.gitattributes` 已設 `*.ps1 text eol=crlf`），語法必須相容 **Windows PowerShell 5.1**：不可用 `??`、`?:`、`&&`/`||` 管線鏈、`-Parallel`；網路請求一律 `-UseBasicParsing`；讀 API 回應用既有 `Invoke-ApiGet` 的 UTF-8 手動解碼。
- 不需要、也不可要求管理員權限；不修改系統或使用者 PATH、不寫登錄檔、不寫 Program Files。PATH 只在本行程內前置 `bin\`。
- 安裝根目錄 `$Root = Join-Path $env:LOCALAPPDATA 'vid-snatch'`，結構固定如下（後續任務都依此命名）：
  ```
  app\                     從 GitHub 解出的原始碼（含 vid-snatch.ps1、pyproject.toml、vid_snatch\）
  app\.commit              這份原始碼的 commit SHA
  bin\uv.exe  bin\deno.exe  bin\ffmpeg.exe  bin\ffprobe.exe
  python\                  UV_PYTHON_INSTALL_DIR
  cache\                   UV_CACHE_DIR
  venv\                    uv venv --seed（含 pip，core.update_ytdlp 需要）
  torch\hub\checkpoints\955717e8-8726e21a.th    TORCH_HOME = $Root\torch
  config\config            output_dir=...（格式同 vid_snatch/config.py）
  state\installed-commit   venv 內 vid-snatch 套件對應的 commit
  logs\server.log          伺服器 stdout/stderr
  server.json              {"pid":<int>,"port":<int>}
  ```
- 預設下載資料夾：`Join-Path $env:USERPROFILE 'Music\vid-snatch'`（同現行）。
- Python 3.12；PyTorch 用 PyPI 預設 wheel（Windows 上即 CPU 版），不另指定 index。
- 伺服器只綁 `127.0.0.1`；連接埠從 8080 起找空的，上限 8180（同現行）。
- GitHub repo：`irene-chou/vid-snatch`，分支 `main`。最新 commit 查 `https://api.github.com/repos/irene-chou/vid-snatch/commits/main`（`Accept: application/vnd.github.sha` 回傳純文字 SHA），封存檔 `https://github.com/irene-chou/vid-snatch/archive/<sha>.zip`。
- 工具下載網址（皆為 GitHub releases 的 latest 固定網址）：
  - uv：`https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip`
  - deno：`https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip`
  - ffmpeg：`https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip`（取 `bin\ffmpeg.exe`、`bin\ffprobe.exe`）
  - Demucs 模型：`https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th`
- 所有下載先寫到 `<目標>.part`，完成後才改名，確保中斷後不會留下看似完整的檔案。
- 使用者看到的文字一律繁體中文；失敗時保留視窗（主腳本 `exit 1`，由 `.bat` 的 `if errorlevel 1 pause` 停住）。
- 測試與開發用環境變數（使用者不會設）：`VS_NO_BROWSER=1`（只印網址，既有）、`VS_SOURCE=local`（不查 GitHub，直接用解壓資料夾的原始碼）、`VS_UPDATE_API`（覆寫查最新 commit 的網址，CI 用來模擬離線）。
- Windows on ARM（`PROCESSOR_ARCHITEW6432` 或 `PROCESSOR_ARCHITECTURE` 為 `ARM64`）：顯示「目前不支援 ARM 版 Windows」後 `exit 1`。
- macOS 的 `Dockerfile`、`publish.yml` 不改；`vid-snatch.command` 只在 Task 6 為下載包配置小改。
- 兩種配置都要能跑：**repo 配置**（`vid-snatch.bat` 與 `windows\` 在 repo 根目錄）與**下載包配置**（最外層 `vid-snatch.bat` + `files\`，`files\` 內為 repo 根目錄的內容）。啟動器一律以「`launcher.ps1` 所在資料夾的上一層」作為原始碼資料夾，兩種配置皆成立。

## Review Focus

1. **使用者名稱含中文或空格**（`C:\Users\王 小明\AppData\Local`）：所有路徑都要正確引號、Start-Process 參數不被拆開。→ Task 5 CI 把 `LOCALAPPDATA` 與 `USERPROFILE` 設到含中文與空格的目錄執行完整流程。
2. **首次安裝到一半關掉視窗**：下次雙擊要能接著裝完，不能卡在半殘狀態。→ Task 5 CI 刪掉 `venv\` 與 `state\installed-commit` 後重跑，必須回到可用。
3. **8080 已被別的程式占用**：要改用下一個連接埠，瀏覽器開對網址。→ Task 5 CI 先佔住 8080，確認伺服器在 `server.json` 記錄的埠上回應。
4. **已在執行時又雙擊**：只開瀏覽器後結束，不起第二個伺服器。→ Task 5 CI 在伺服器運作中再跑一次啟動器，確認快速結束且 pid 不變。
5. **GitHub 連不上**：已安裝過就直接啟動。→ Task 5 CI 以 `VS_UPDATE_API=http://127.0.0.1:9/` 重跑，確認 60 秒內健康檢查通過。

---

### Task 1: 伺服器綁定位址可由環境變數決定

**Files:**
- Modify: `vid_snatch/webserver.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: 環境變數 `VS_BIND`。未設時維持 `0.0.0.0`（容器內行為不變）；Windows 主腳本會設成 `127.0.0.1`。

- [ ] **Step 1: 寫失敗的測試** — 在 `tests/test_cli.py` 加兩個測試，沿用 `test_run_web_reads_env_and_defaults_host_output_dir` 的 monkeypatch 方式，另外 monkeypatch `uvicorn.Config.__init__` 或擷取傳給 `uvicorn.Server` 的 config：

```python
def test_run_web_binds_vs_bind(monkeypatch, tmp_path):
    ...  # 設 VS_BIND=127.0.0.1
    assert captured_config.host == "127.0.0.1"

def test_run_web_defaults_to_all_interfaces(monkeypatch, tmp_path):
    ...  # 刪除 VS_BIND
    assert captured_config.host == "0.0.0.0"
```

- [ ] **Step 2: 執行確認失敗** — `.venv/bin/python -m pytest -q -W error tests/test_cli.py`，預期第一個測試 FAIL。
- [ ] **Step 3: 實作** — `run_web` 改用 `os.environ.get("VS_BIND", "0.0.0.0")` 作為 uvicorn host。
- [ ] **Step 4: 執行全部測試** — `.venv/bin/python -m pytest -q -W error`，預期全數 PASS。
- [ ] **Step 5: Commit** — `feat: 伺服器綁定位址可由 VS_BIND 指定`

---

### Task 2: 穩定啟動器 `windows/launcher.ps1` 與 `vid-snatch.bat`

**Files:**
- Create: `windows/launcher.ps1`（UTF-8 BOM、CRLF）
- Modify: `vid-snatch.bat`

**Interfaces:**
- Consumes: 主腳本 `vid-snatch.ps1`（Task 3、4 改寫）接受參數 `-Commit <string>`（SHA 或 `local`）與 `-Upgrade`（switch）。
- Produces: 主腳本結束碼約定：`0` 正常結束、`1` 失敗（bat 會 pause）、`10` 要求「更新」——啟動器收到 10 時以 `-Upgrade` 重新跑一輪完整流程（重新查 GitHub、取新原始碼、再呼叫新的主腳本）。

這個檔案之後幾乎不再改，所以只做四件事，每件都要簡單：

- [ ] **Step 1: 寫 `vid-snatch.bat`** — 保留 `chcp 65001`，改為呼叫啟動器：`%~dp0files\windows\launcher.ps1` 存在就用它（下載包配置），否則用 `%~dp0windows\launcher.ps1`（repo 配置）；以 `powershell -NoProfile -ExecutionPolicy Bypass -File "<路徑>"` 執行，保留 `if errorlevel 1 pause`。
- [ ] **Step 2: 決定原始碼** — 實作 `Get-SourceDir([switch]$Upgrade) -> @{ Dir = <資料夾>; Commit = <sha 或 'local'> }`：
  - `VS_SOURCE=local` → 直接回傳解壓資料夾（`Split-Path $PSScriptRoot -Parent`），Commit=`local`。
  - 否則以 `VS_UPDATE_API`（預設為 Global Constraints 的 commits 網址）查最新 SHA，逾時 10 秒。
    - 查到且等於 `app\.commit` → 回傳 `app\`。
    - 查到但不同 → 下載封存檔到 `$Root\app.zip.part` → 改名 → 解到 `$Root\app.new\`（封存檔內有一層 `vid-snatch-<sha>\`，要取其內容）→ 寫 `.commit` → 刪掉舊 `app\` 並把 `app.new\` 改名為 `app\`。任一步失敗就清掉 `app.new\` 與 zip，改走下一條。
    - 查不到或下載失敗 → `app\vid-snatch.ps1` 存在就用 `app\`，否則用解壓資料夾（Commit=`local`）。
  - 畫面只印一行「正在檢查更新…」；失敗時不印錯誤（離線是正常情況）。
- [ ] **Step 3: 呼叫主腳本並處理結束碼** — 以 `powershell -NoProfile -ExecutionPolicy Bypass -File <Dir>\vid-snatch.ps1 -Commit <Commit> [-Upgrade]` 執行；結束碼 10 → 回到 Step 2 並帶 `-Upgrade`；其他結束碼原樣 `exit`。
- [ ] **Step 4: 本機語法檢查** — 這台 Mac 沒有 pwsh，執行：`brew list powershell >/dev/null 2>&1 || echo "no pwsh"`。若有 pwsh 則 `pwsh -NoProfile -Command "[void][scriptblock]::Create((Get-Content -Raw windows/launcher.ps1))"` 必須無錯誤；若沒有，記在報告中，由 Task 5 的 CI 解析檢查把關。確認檔案開頭為 BOM：`head -c3 windows/launcher.ps1 | xxd` 顯示 `efbbbf`。
- [ ] **Step 5: Commit** — `feat: Windows 穩定啟動器，每次啟動取得 GitHub 最新版`

---

### Task 3: 主腳本——首次安裝與續裝

**Files:**
- Modify: `vid-snatch.ps1`（移除 Docker 相關：`Ensure-Docker`、`Ensure-Image`、`Get-WantArch` 的 docker 用途、`docker` 指令；設定檔改到 `$Root\config`）

**Interfaces:**
- Consumes: Task 2 傳入的 `-Commit`、`-Upgrade`；`$PSScriptRoot` 即原始碼資料夾（含 `pyproject.toml`）。
- Produces: `Ensure-Installed([string]$Commit, [switch]$Upgrade)`，結束後保證 `bin\` 四個 exe、`venv\Scripts\vid-snatch.exe`、模型檔都存在，且本行程環境已設好 `PATH`（前置 `$Root\bin`）、`TORCH_HOME`、`UV_PYTHON_INSTALL_DIR`、`UV_CACHE_DIR`。

- [ ] **Step 1: 架構檢查** — ARM64 依 Global Constraints 拒絕。
- [ ] **Step 2: `Save-Download([string]$Url, [string]$Dest, [string]$Label)`** — 印 `正在下載 <Label>…`，寫 `.part` 再改名；失敗時印「下載失敗，請確認網路連線後重新雙擊 vid-snatch.bat」並 `exit 1`。
- [ ] **Step 3: 工具** — 各自「檔案不存在才下載」：uv（解出 `uv.exe`）、ffmpeg（從 zip 內 `*\bin\` 取 `ffmpeg.exe`、`ffprobe.exe`）、deno。`-Upgrade` 時重新下載 deno（yt-dlp 依賴它解 YouTube 驗證，需跟上新版）。
- [ ] **Step 4: Python 環境** — `venv\Scripts\python.exe` 不存在時：印「正在準備 Python 環境…」，執行 `uv venv --seed --python 3.12 "$Root\venv"`。
- [ ] **Step 5: 套件** — 規則：
  - `state\installed-commit` 不存在 → 印「正在安裝去人聲元件（約 1 GB，約 5–10 分鐘）…」，`uv pip install --python <venv python> "<PSScriptRoot>"`。
  - 存在但與 `$Commit` 不同，或 `$Commit` 為 `local` → `uv pip install --python <venv python> --reinstall-package vid-snatch "<PSScriptRoot>"`（不升級其他依賴）。
  - `-Upgrade` → `uv pip install --python <venv python> --upgrade "<PSScriptRoot>"`。
  - 成功後才寫 `state\installed-commit`；失敗印中文說明並 `exit 1`（下次會因為 marker 不符而重試）。
  - 若安裝失敗原因是某依賴沒有 Windows wheel 而需要編譯，**不要**加裝編譯工具；在報告中標明是哪個套件，交由控制者處理。
- [ ] **Step 6: 模型** — 模型檔不存在時用 `Save-Download` 下載（標籤「去人聲模型（約 80 MB）」）。
- [ ] **Step 7: 語法與 BOM 檢查** — 同 Task 2 Step 4 的方式。
- [ ] **Step 8: Commit** — `feat: Windows 主腳本改用 uv 原生安裝`

---

### Task 4: 主腳本——啟動、主迴圈、更新、解除安裝

**Files:**
- Modify: `vid-snatch.ps1`

**Interfaces:**
- Consumes: Task 1 的 `VS_BIND`；Task 3 的 `Ensure-Installed`；Task 2 的結束碼約定（10 = 更新）。
- Produces: `server.json`（`{"pid":..,"port":..}`）供重複雙擊偵測與 CI 讀取連接埠。

- [ ] **Step 1: `Test-ServerRunning -> bool`** — 讀 `server.json`；pid 的行程存在、且 `http://127.0.0.1:<port>/api/health` 2 秒內回應才算在跑（避免 pid 被別的行程重用）。成立時設 `$script:Port`。
- [ ] **Step 2: `Start-Server -> bool`** — 找空埠（沿用 `Test-PortInUse`）；建立下載與設定資料夾；設本行程 `$env:VS_OUTPUT_DIR`、`VS_HOST_OUTPUT_DIR`（皆為 `$OutputDir`）、`VS_CONFIG_DIR`（`$Root\config`）、`VS_BIND=127.0.0.1`；`Start-Process -WindowStyle Hidden -FilePath "$Root\venv\Scripts\vid-snatch.exe" -ArgumentList '--web','--port',<p> -RedirectStandardOutput <logs\server.log> -RedirectStandardError <logs\server.err.log> -PassThru`；寫 `server.json`。
- [ ] **Step 3: 停止與錯誤輸出** — `Stop-VidSnatch` 改為對 `server.json` 的 pid 呼叫 `Stop-Process -Force`（行程不存在時靜默）並刪掉 `server.json`。`Wait-Health` 失敗時改印 `logs\server.err.log` 最後 20 行（取代 `docker logs`）。主迴圈裡 `Test-ContainerRunning` 換成 `Test-ServerRunning`。
- [ ] **Step 4: 主流程** — 順序：`Load-Config` → 若 `Test-ServerRunning` 則印「vid-snatch 已經在執行中，已幫你打開瀏覽器。」、`Open-Browser`、`exit 0` → `Ensure-Installed` → `Start-Server` → `try { Wait-Health; Open-Browser; Invoke-HostLoop } finally { Stop-VidSnatch }`。重複雙擊檢查要在 `Ensure-Installed` 之前，才不會在伺服器運作中重裝套件。
- [ ] **Step 5: 更新** — `Invoke-Rebuild` 改為：印「正在更新…」→ `Stop-VidSnatch` → `exit 10`（由啟動器重新取原始碼並以 `-Upgrade` 執行）。
- [ ] **Step 6: 解除安裝** — `Invoke-Uninstall` 改為：`Stop-VidSnatch` → `Set-Location $env:TEMP`（避免目前目錄鎖住要刪的資料夾）→ 刪除預設下載資料夾的規則完全沿用現行 → 用 `[System.IO.Directory]::Delete($Root, $true)` 刪除整個 `$Root`（失敗時印路徑請使用者自行刪除）→ 完成訊息提示「如需完全移除，可刪除你解壓縮的 vid-snatch 資料夾」並附解壓資料夾路徑（`$env:VS_LAUNCH_DIR`，由啟動器在呼叫前設定為使用者看到的最外層資料夾：下載包配置為 `files\` 的上一層，repo 配置為 repo 根目錄）。
- [ ] **Step 7: 語法與 BOM 檢查** — 同 Task 2 Step 4。並 `grep -n docker vid-snatch.ps1` 應無結果。
- [ ] **Step 8: Commit** — `feat: Windows 主腳本以背景 Python 行程執行伺服器`

> Task 4 Step 6 需要啟動器設 `VS_LAUNCH_DIR`：在 Task 4 一併修改 `windows/launcher.ps1`，於呼叫主腳本前 `$env:VS_LAUNCH_DIR` 設為上述最外層資料夾（`launcher.ps1` 上一層若名為 `files` 就再往上一層）。

---

### Task 5: GitHub Actions Windows 驗證

**Files:**
- Create: `.github/workflows/windows.yml`
- Create: `windows/ci-smoke.ps1`（CI 專用，UTF-8 BOM）

**Interfaces:**
- Consumes: Task 2–4 的全部行為，`server.json`、`VS_SOURCE`、`VS_UPDATE_API`、`VS_NO_BROWSER`。

觸發：`push` 到 `main`、`pull_request`、`workflow_dispatch`。`runs-on: windows-latest`。

- [ ] **Step 1: 解析檢查工作** — 用 Windows PowerShell 5.1（`shell: powershell`）對 `vid-snatch.ps1`、`windows/launcher.ps1`、`windows/ci-smoke.ps1` 執行 `[System.Management.Automation.Language.Parser]::ParseFile(...)`，有任何錯誤即失敗；並檢查三個檔案前三個位元組為 BOM。
- [ ] **Step 2: pytest 工作** — `actions/setup-python` 3.12，`pip install -e .[dev]`，`pytest -q -W error`。
- [ ] **Step 3: 冒煙測試腳本 `windows/ci-smoke.ps1`** — 依序執行下列情境，每個情境失敗時印出 `$Root\logs\*` 後 `exit 1`。共同設定：`LOCALAPPDATA` 與 `USERPROFILE` 指到 `$env:RUNNER_TEMP\測試 使用者\...`（Review Focus 1）、`VS_NO_BROWSER=1`。啟動器以 `Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"<repo>\windows\launcher.ps1" -PassThru` 在背景執行，標準輸入導向空檔。
  1. **首次安裝**（`VS_SOURCE=local`）：先用 `python -m http.server 8080` 佔住 8080（Review Focus 3）；等到 `server.json` 出現且其 port 的 `/api/health` 回應，最多 25 分鐘；斷言 port ≠ 8080；`GET /` 回應含 `names-row`。
  2. **重複啟動**（Review Focus 4）：再跑一次啟動器，斷言它在 60 秒內結束、結束碼 0，且 `server.json` 的 pid 不變。
  3. **結束**：`POST /api/shutdown`（帶 `X-Vid-Snatch: 1`），斷言第一個啟動器在 30 秒內結束，伺服器 pid 不存在。
  4. **離線再啟動**（Review Focus 5）：拿掉 `VS_SOURCE`，設 `VS_UPDATE_API=http://127.0.0.1:9/`，啟動後 60 秒內健康檢查通過；然後 shutdown。
  5. **中斷續裝**（Review Focus 2）：刪掉 `$Root\venv` 與 `$Root\state\installed-commit`，以 `VS_SOURCE=local` 重跑，25 分鐘內健康檢查通過；shutdown。
- [ ] **Step 4: 冒煙工作** — workflow 加一個 job 執行 `windows/ci-smoke.ps1`（`shell: powershell`，`timeout-minutes: 60`）。
- [ ] **Step 5: 推上 CI 並讀結果** — 這一步需要 push 分支，屬於對外動作：由控制者向使用者取得同意後執行。若 CI 失敗，修到通過；若失敗原因是 Windows 缺預編譯 wheel，停下回報（設計文件第 4 節）。
- [ ] **Step 6: Commit** — `ci: Windows 原生安裝冒煙測試`

---

### Task 6: 分平台下載包

**Files:**
- Create: `.github/workflows/release.yml`
- Create: `scripts/build-packages.sh`
- Modify: `vid-snatch.command`

**Interfaces:**
- Produces: GitHub Release tag `latest` 上的兩個資產 `vid-snatch-Windows.zip`、`vid-snatch-Mac.zip`，下載網址 `https://github.com/irene-chou/vid-snatch/releases/latest/download/vid-snatch-<Windows|Mac>.zip`（Task 7 README 使用）。

- [ ] **Step 1: `scripts/build-packages.sh <out_dir>`** — 用 `git archive HEAD` 取得 repo 內容（套用 `.gitattributes` 的換行設定），組出：
  - `vid-snatch-Windows/vid-snatch.bat` + `vid-snatch-Windows/files/`（`files/` 內容：`vid-snatch.ps1`、`windows/launcher.ps1`、`pyproject.toml`、`vid_snatch/`；不含 `windows/ci-smoke.ps1`、tests、docs、Dockerfile、`vid-snatch.command`）
  - `vid-snatch-Mac/vid-snatch.command` + `vid-snatch-Mac/files/`（`files/` 內容：`Dockerfile`、`pyproject.toml`、`vid_snatch/`）
  - 分別壓成 `<out_dir>/vid-snatch-Windows.zip`、`<out_dir>/vid-snatch-Mac.zip`，zip 內保留最外層資料夾名稱。`vid-snatch.command` 在 zip 內必須保有執行權限（用 `zip` 指令從檔案系統壓縮，事先 `chmod +x`）。
- [ ] **Step 2: 本機驗證** — `bash scripts/build-packages.sh "$TMPDIR/pkg"`，用 `unzip -l` 確認兩個 zip 的最外層只有一個執行檔與 `files/`；`unzip -Z` 確認 `.command` 權限含 `x`；解開 Windows 包後 `head -c3 files/vid-snatch.ps1 | xxd` 為 `efbbbf` 且 `file` 顯示 CRLF。
- [ ] **Step 3: `vid-snatch.command` 支援下載包配置** — `cd "$(dirname "$0")"` 之後：若 `files/Dockerfile` 存在，`docker build` 的 context 改用 `files`；`PROJECT_DIR`（解除安裝訊息顯示的資料夾）維持最外層。repo 配置行為完全不變。用 `bash -n vid-snatch.command` 檢查語法；在解開的 Mac 包裡設 `VS_NO_BROWSER=1` 執行一次，確認能啟動並印出網址（本機有 Docker）。
- [ ] **Step 4: `.github/workflows/release.yml`** — 觸發 `push` 到 `main` 與 `workflow_dispatch`；`permissions: contents: write`；`ubuntu-latest` 執行 Step 1 腳本，再把 tag `latest` 移到目前 commit（`git tag -f latest && git push -f origin latest`），並以 `gh release` 建立（若不存在）或更新 release `latest`，上傳兩個 zip（`--clobber`）。release 不可標為 prerelease，否則 `releases/latest/download` 網址不會指向它。
- [ ] **Step 5: Commit** — `ci: 每次更新產生 Windows 與 Mac 分開的下載包`

---

### Task 7: README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 安裝段落** — 拆成 macOS 與 Windows 兩段，各自第一步是直接下載對應的包（Task 6 的 `releases/latest/download` 網址），不再提 `Code` → `Download ZIP`。macOS：裝 Docker Desktop → 下載 `vid-snatch-Mac.zip` → 解壓縮 → 雙擊 `vid-snatch.command`（Gatekeeper 說明沿用）。Windows：不用先裝任何東西 → 下載 `vid-snatch-Windows.zip` → 解壓縮 → 雙擊 `vid-snatch.bat`（SmartScreen 說明沿用）。註明 `files` 資料夾不用打開。Windows 首次啟動說明「會自動下載約 1–2 GB，約 10–15 分鐘，視窗會顯示目前進度」。
- [ ] **Step 2: 使用段落** — 第 4 步改為「確認或修改每個網址的檔名，按『開始』」（配合多網址檔名清單）；移除「Windows 上，背景服務會在關閉視窗後約 15 秒自動停止」以外與 Docker 有關的 Windows 敘述，該句保留。
- [ ] **Step 3: 常見問題** — 「Docker 跳出同意條款？」標明僅 macOS；新增「Windows 防毒軟體擋下載？」：說明會下載 uv、ffmpeg、deno 三個工具，被擋時允許後重新雙擊；「怎麼移除？」補充 Windows 會一併刪除 `%LOCALAPPDATA%\vid-snatch`。
- [ ] **Step 4: Commit** — `docs: README 說明 Windows 免 Docker 安裝`
