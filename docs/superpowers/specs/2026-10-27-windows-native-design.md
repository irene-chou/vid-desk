# Windows 版改為原生執行（不使用 Docker）設計文件

日期：2026-10-27
前置文件：`docs/superpowers/specs/2026-10-26-web-ui-design.md`（網頁介面設計，本文件只描述與它不同的部分）

## 1. 為什麼要改

驗收時發現：Windows 上的 Docker Desktop 對非工程使用者太難裝。它要求到 BIOS 開啟虛擬化（Intel VT-x / AMD-V）、安裝 WSL2，部分公司電腦還鎖住這些設定。這不是 README 寫清楚就能解決的門檻。

macOS 上 Docker Desktop 不需要這些步驟，維持現狀。

## 2. 目標、非目標、反目標

**目標**
- Windows 使用者只需：下載 ZIP、解壓縮、雙擊 `vid-snatch.bat`。不需要管理員權限、不需要虛擬化、不需要事先安裝任何東西（Python、Docker、ffmpeg 都不用）。
- 網頁介面、使用流程、按鈕、錯誤訊息與 macOS 版完全相同。
- 現有功能全部保留：MP3、去人聲 MP3、MP4、顯示檔案、更換資料夾、結束、更新、解除安裝、yt-dlp 自動更新。
- 每次啟動自動檢查更新，取得的程式版本與 macOS 從 GHCR 拉到的映像檔一致（都是 GitHub `main` 最新版）。
- 離線或 GitHub 連不上時，已安裝過的使用者仍可啟動。

**非目標**
- macOS 仍用 Docker（使用者決定），只為 3.8 的下載包配置做小改。
- 不做 Windows 安裝程式（.msi / .exe installer），也不做程式碼簽章。
- 不支援 Windows on ARM（PyTorch / Demucs 在該平台支援不完整）。遇到時顯示清楚的中文訊息後結束。
- 不支援 GPU 加速。

**反目標（技術上能動但算失敗）**
- 需要使用者開 PowerShell 打指令、改執行原則、或按「以系統管理員身分執行」。
- 安裝過程寫入使用者看不到、解除安裝刪不乾淨的位置（例如修改系統 PATH、寫入 Program Files、登錄檔）。
- 第一次啟動畫面長時間沒有任何進度文字，讓使用者以為當掉。

## 3. 已決定的做法

### 3.1 執行方式

- 用 **uv**（Astral 的 Python 管理工具，單一 exe、免安裝、免管理員）建立獨立的 Python 3.12 環境，安裝 vid-snatch 套件及其依賴。
- 所有檔案集中放在 **`%LOCALAPPDATA%\vid-snatch\`**，包含 uv、Python、套件環境、ffmpeg、deno、Demucs 模型、設定檔。不修改 PATH、不寫登錄檔。解除安裝時刪掉這個資料夾即為乾淨移除。
- 下載的影音預設仍存到 `音樂\vid-snatch`（與目前一致）。

### 3.2 外部工具

- **ffmpeg / ffprobe**：yt-dlp 轉檔與 Demucs 都需要。下載 Windows 靜態建置版放進 `%LOCALAPPDATA%\vid-snatch\`，由啟動腳本把所在目錄加到「該行程」的 PATH。
- **deno**：Docker 映像檔裡裝了 deno，供 yt-dlp 解 YouTube 的 JS 驗證。Windows 版同樣下載 `deno.exe` 放進同一資料夾。
- **Demucs htdemucs_ft 模型**：安裝時就下載（與 Docker 版預載同樣 4 個檔案 `f7e0c4bc-ba3fe64a.th`、`d12395a8-e57c48e6.th`、`92cfc3b6-ef3bcb9c.th`、`04573f0d-f3cf25b2.th`，共約 320 MB），放在資料夾內並以 `TORCH_HOME` 指過去，第一次去人聲不必再等。
- PyTorch 用 CPU 版。

### 3.3 架構：沿用「宿主端動作」協定

保留網頁設計文件裡的架構：Python 伺服器只負責網頁與下載，「顯示檔案、選資料夾、結束、更新、解除安裝」仍以 host action 交給 PowerShell 啟動腳本處理，心跳機制也保留。

理由：`web.py`、`hostactions.py`、前端完全不用改，macOS 與 Windows 走同一套協定；PowerShell 腳本裡已寫好的 `Invoke-Reveal`、`Start-PickFolder`、主迴圈可以沿用，只把「啟動 / 停止 Docker 容器」換成「啟動 / 停止 Python 行程」。

具體改變：
- `vid-snatch.bat` 改為 3.4 所述的小啟動器；`vid-snatch.ps1` 中與 Docker 有關的部分（檢查 Docker、拉映像檔、`docker run` / `stop` / `rmi`）全部換掉。
- Python 伺服器以隱藏視窗的背景行程啟動，由環境變數提供 `VS_OUTPUT_DIR`、`VS_CONFIG_DIR`、`VS_HOST_OUTPUT_DIR`（原生執行時三者都是真實的 Windows 路徑）。
- 伺服器只綁 `127.0.0.1`（目前程式在容器內綁 `0.0.0.0`，原生執行時必須改，否則同網路的人可以連進來）。
- 關掉終端機視窗後，背景 Python 行程靠既有心跳機制約 15 秒內自行結束，與目前 Windows Docker 版行為相同。
- 「更新 vid-snatch」：停止 Python 行程 → 重新安裝最新版套件並更新 yt-dlp → 重新啟動並開瀏覽器。
- 「解除安裝」：停止 Python 行程 → 刪除 `%LOCALAPPDATA%\vid-snatch\` →（若使用者選擇）刪除預設下載資料夾，規則與現行相同：只刪預設的 `音樂\vid-snatch`。
- 重複雙擊：已有伺服器在跑時只開瀏覽器後結束（沿用現行規則）。

### 3.4 程式來源與更新

- 更新範圍包含 **PowerShell 腳本本身**，不只 Python 套件，否則腳本出 bug 永遠修不到已解壓的使用者（我的決定）。
- 結構分兩層：
  - 使用者解壓縮資料夾裡的 `vid-snatch.bat` 只是穩定的小啟動器，幾乎不再修改。
  - 它每次啟動嘗試下載 GitHub `main` 的封存檔，解到 `%LOCALAPPDATA%\vid-snatch\app\`，然後執行**那一份**的 `vid-snatch.ps1`。套件也從同一份原始碼安裝，腳本與程式碼版本永遠一致。這與 macOS 從 GHCR 拉 `latest` 對等。
- 判斷「已是最新」：比對 `main` 最新 commit 與上次安裝的 commit，相同就跳過下載與重裝。
- 取得失敗時：若 `app\` 已有安裝就直接用；若從未安裝，改用解壓縮資料夾裡的 `vid-snatch.ps1` 與原始碼；兩者都不行才顯示錯誤。
- 依賴版本不鎖定，與目前 Dockerfile 一樣在安裝時解析最新相容版本（我的決定，不改動 macOS 建置）。
  - 平常啟動、程式碼有新 commit 時：重裝 vid-snatch 套件，但已安裝且仍滿足需求的依賴不升級，所以不會每次重下 PyTorch。
  - 按「更新 vid-snatch」時：連同所有依賴一起升級到最新，可能需要重新下載大型依賴，畫面要顯示進度。
- 已是最新版時，雙擊到瀏覽器打開應在 30 秒內。
- 前提：GitHub repo 為公開（目前是），無認證即可下載封存檔與查詢最新 commit。

### 3.4.1 舊版不處理

目前沒有 Windows 使用者在用舊的 Docker 版（使用者確認），因此不做設定檔搬移、不偵測舊容器、不清 Docker 映像檔。

### 3.5 首次安裝的畫面

- 終端機視窗依序顯示中文步驟與大概時間，例如「正在下載 Python 環境…」「正在安裝去人聲元件（約 1 GB，約 5–10 分鐘）…」「正在下載 ffmpeg…」。
- 任一步失敗：顯示中文說明（多半是網路問題，請檢查網路後重新雙擊），保留視窗等使用者按鍵後才關閉。下次雙擊能從失敗處續裝，不會留下半殘環境導致永遠起不來。

### 3.6 驗證

- 這台開發機是 Mac，無法實際執行 Windows 腳本。因此新增 **GitHub Actions `windows-latest` 工作**：在乾淨的 Windows runner 上執行完整首次安裝流程，確認伺服器啟動且 `/api/health` 回應正常，再跑一次 pytest。CI 不實際打 YouTube 下載。
- 使用者另在實體 Windows 電腦做人工驗收：首次安裝、三種格式下載、顯示檔案、選資料夾、更新、解除安裝、關閉視窗後背景行程結束。

### 3.7 文件

- README 的安裝段落分成 macOS（裝 Docker Desktop）與 Windows（不用裝任何東西）兩條路徑。
- Windows 常見問題改寫：首次下載約 1–2 GB、資料放在哪、SmartScreen 處理方式（沿用）。

### 3.8 下載包：一個包，最外層兩個執行檔

使用者要求：執行檔要好找、Windows 和 Mac 分得清楚，但只要一個下載包。

- 不再請使用者按 GitHub 的 `Code` → `Download ZIP`（解出來是整個 repo，執行檔混在 Dockerfile、tests、docs 之間）。
- 改由 GitHub Actions 在每次 `main` 更新時產生一個 `vid-snatch.zip`，放在 GitHub Release（固定的 `latest/download` 網址），README 直接連過去。
- 解開後最外層只有三樣東西：
  - `vid-snatch-Windows.bat`
  - `vid-snatch-Mac.command`
  - `files` 資料夾（其餘所有檔案，使用者不用打開）
- 執行檔在 repo 裡也改成這兩個名字，README 與畫面訊息一致。
- 兩個執行檔都要能同時在「下載包」與「直接 clone repo」兩種配置下運作。
- macOS 的啟動檔因此需要小改：在下載包配置下，從 `files` 建置映像檔。其餘行為不變。
- 檔名維持英文，避免舊版 Windows 解壓縮工具把中文檔名變亂碼。

## 4. 留給實作者決定

- uv、ffmpeg、deno 的下載來源與版本固定方式（需穩定、可長期使用的官方或廣泛使用的發布網址）。
- 「從 GitHub 安裝最新版」的具體機制（例如 uv 直接安裝 GitHub 封存檔網址，或下載 ZIP 後安裝），以及如何判斷「已是最新」以避免每次重裝。
- 續裝的判斷方式（例如每一步完成後寫標記檔）。
- `run_web` 綁定位址如何區分容器與原生（例如環境變數），只要原生一定是 `127.0.0.1`、容器內行為不變即可。
- Windows 上 `sphn` 等依賴若沒有預編譯套件時的處理方式；若確定無法在不裝編譯工具的情況下安裝，請回報，這會改變整個方案。

## 5. 風險

- **首次下載量大**（PyTorch 為主，約 1–2 GB）。已在畫面與 README 說明，無法避免。
- **防毒軟體** 可能攔截下載的 exe（uv、ffmpeg、deno）。README 加一條說明；不另做處理。
- **依賴在 Windows 上缺預編譯套件**：見第 4 節最後一點，CI 會最先暴露。
