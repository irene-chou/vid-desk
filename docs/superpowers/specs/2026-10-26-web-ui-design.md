# vid-snatch 網頁介面設計

日期：2026-10-26
狀態：已確認

## 1. 意圖與動機

vid-snatch 目前的操作方式是雙擊 `vid-snatch.command` / `vid-snatch.bat`，在終端機選單裡按數字、貼網址、再回答檔名。對非工程背景的使用者而言，終端機本身就是門檻：黑底白字、yt-dlp 與 Demucs 的原始 log、英文錯誤訊息、出錯時視窗直接消失。

這份設計把操作介面搬到瀏覽器：使用者仍然雙擊同一個檔案，但接下來看到的是一個乾淨的網頁，貼網址、按按鈕、看進度條、完成後打開資料夾。終端機視窗退居幕後。

同時把前次討論中「投入小、感受明顯」的幾項優化一併納入（第 7 節），因為它們大多本來就該在網頁版裡一起做。

## 2. 目標、非目標、反目標

**目標**
- 非工程使用者從雙擊到拿到檔案，中間不需要看懂任何終端機文字。
- 三種結果（MP3、去人聲 MP3、MP4）一眼可選，檔名預填影片標題，可改。
- 處理過程有可讀的進度（步驟名稱 + 百分比），不露出原始 log。
- 出錯時給一句中文人話，並告訴使用者可以做什麼。
- 既有 CLI 用法（`docker run ... vid-snatch "URL" --no-vocals`）保持可用。

**非目標（這次不做）**
- 不做 PyInstaller / 原生 `.app` 打包，仍以 Docker 為執行環境。
- 不做多人共用的伺服器部署，僅 localhost 單機使用。
- 不做使用者帳號、歷史紀錄持久化（關閉後清空即可）。
- 不做播放清單整批下載（但支援一次貼多個單一影片網址）。

**反目標（做到了也算失敗）**
- 使用者需要打開瀏覽器網址列自己輸入 localhost。
- 網頁開了但終端機視窗還在閃 log，讓人以為壞了。
- 原本 CLI 模式被破壞。
- Windows 上出錯視窗秒關。

## 3. 限制

- 執行環境是 Docker 容器（`python:3.12-slim` + ffmpeg + CPU 版 torch + demucs + yt-dlp）。
- 容器內碰不到宿主機：不能 `open` 資料夾、不能跳原生資料夾選擇視窗。
- 輸出路徑靠 volume 掛載（`-v "$OUTPUT_DIR:/app/output"`），容器啟動後不能改。
- 使用者機器上只能假設有 Docker Desktop，不假設有 Python、Node。
- 前端不能有 build step（不想在 Docker build 裡多裝 Node）。
- 儲存庫 `irene-chou/vid-snatch` 是公開的，GHCR 可匿名 pull。

## 4. 整體架構

```
使用者雙擊 vid-snatch.command
        │
        ▼
啟動腳本（宿主機 bash / bat）
  1. 檢查 Docker、必要時啟動 Docker Desktop
  2. 取得映像檔（優先 pull GHCR，失敗則本地 build）
  3. docker run -d -p <port>:8080 -v 輸出資料夾 -v 設定資料夾 vid-snatch --web
  4. 等 /api/health 回 200，開瀏覽器
  5. 進入「宿主機助手迴圈」：輪詢 /api/host-actions，代容器執行宿主端動作
  6. 視窗被關 / Ctrl-C / 收到 shutdown → docker stop
        │
        ▼
容器內 FastAPI（vid_snatch.py --web）
  - 提供靜態單頁 HTML
  - /api/info      取影片標題（預填檔名）
  - /api/jobs      建立工作（可一次多筆）
  - /api/events    SSE 推送進度
  - /api/settings  讀 / 寫設定檔（輸出路徑）
  - /api/host-actions  給啟動腳本領取的宿主端動作佇列
  - /api/shutdown  結束
        │
        ▼
瀏覽器單頁（vanilla HTML/CSS/JS，無框架、無 build）
```

### 4.1 為什麼需要「宿主機助手迴圈」

容器做不到的三件事都在宿主機：在 Finder / 檔案總管裡顯示剛完成的檔案、跳原生資料夾選擇視窗、關掉自己。與其把這些功能砍掉，不如讓啟動腳本在開完瀏覽器後不要結束，改成每 1 秒 `GET /api/host-actions`，拿到動作就執行：

| 動作 | 宿主機做的事 |
|---|---|
| `reveal` `{path}` | macOS `open -R`，Windows `explorer /select,` |
| `pick_folder` | macOS `osascript -e 'choose folder'`，Windows PowerShell `FolderBrowserDialog`；結果 `POST /api/host-actions/{id}/result` |
| `shutdown` | `docker stop`，結束腳本 |
| `rebuild` | `docker stop` → pull（失敗則 build）→ 重新 run → 等 health → 重開瀏覽器 |
| `uninstall` `{delete_downloads}` | `docker stop` → `rmi` → 刪設定檔 →（可選）刪輸出資料夾 → 印完成訊息後結束 |

這是我的決定（builder 可以換成其他 IPC 方式，但要維持「使用者不需要碰終端機」）。

因為 `rebuild` 要能重跑整段啟動流程，啟動腳本要把「pull → run → 等 health → 開瀏覽器 → 助手迴圈」寫成可重入的函式。

### 4.2 心跳與容器壽命（我的決定）

助手迴圈每秒的輪詢同時就是心跳。容器端若連續 15 秒沒收到任何 `/api/host-actions` 請求，就自行結束（進行中的工作一起中止，因為啟動腳本已經不在了，沒人能收尾）。這樣 Windows 關掉 cmd 視窗（不會跑任何清理）也能在 15 秒內收掉容器；macOS 另外加 `trap EXIT` 做立即 `docker stop`。

### 4.3 重複啟動與 Port

- 啟動腳本先 `docker ps --filter name=vid-snatch`。若已有在跑的容器，不再開第二個，直接讀它的 port、開瀏覽器、進入助手迴圈（接管）。這避免使用者重複雙擊時開出兩個容器寫同一個資料夾。
- 沒有在跑的容器時，預設 port 8080；被其他程式占用（macOS `lsof -i`，Windows `netstat`）就往上找空的，並把實際 port 用在 `-p` 與開啟的網址上。

### 4.4 誤關瀏覽器分頁

終端機視窗保留一行：「vid-snatch 執行中，操作請看瀏覽器視窗。誤關了？按 Enter 重新開啟。關閉此視窗即結束。」助手迴圈以 1 秒逾時讀 stdin，讀到 Enter 就再 `open` 一次網址。

## 5. 網頁介面

單一頁面，中文介面，手機寬度也能用（雖然主要在桌機），不需要暗色模式切換但要跟隨系統。

### 5.1 主畫面

```
┌────────────────────────────────────────────┐
│  vid-snatch                      ⚙ 設定     │
├────────────────────────────────────────────┤
│  貼上 YouTube 網址（一行一個）               │
│  ┌──────────────────────────────┐ [貼上]    │
│  │                              │           │
│  └──────────────────────────────┘           │
│                                              │
│  要什麼？                                    │
│  (●) 音檔 MP3   ( ) 去人聲 MP3   ( ) 影片 MP4 │
│                                              │
│  檔名  [ 影片標題會自動填入       ]  (單筆時) │
│                                              │
│              [  開始  ]                      │
├────────────────────────────────────────────┤
│  進行中 / 已完成                             │
│  ▶ 某首歌.mp3     步驟 2/3 分離人聲  ▓▓▓░ 65% │
│  ✓ 另一首.mp3     完成   [顯示檔案]          │
│  ✗ 第三個         這是私人影片，無法下載       │
└────────────────────────────────────────────┘
```

行為細節：
- **貼上按鈕**：用 `navigator.clipboard.readText()`（localhost 是 secure context，可用）。失敗就靜默忽略，使用者照樣可以手動貼。
- **網址驗證在前端先做一次**：逐行判斷是否為 YouTube 網址（`watch?v=`、`shorts/`、`youtu.be/`、`music.youtube.com`、`live/`），不是就標紅，不送出。同時剝掉 `&list=`、`&t=`、`?si=` 等參數。
- **檔名預填**：單筆網址時，使用者貼完 ~500ms 後呼叫 `/api/info` 拿標題填入檔名欄；多筆時隱藏檔名欄，一律用標題。
- **檔案已存在**：送出前由後端檢查目標檔名是否存在，是則前端跳「已有同名檔案，要覆蓋還是另存為 xxx (1)？」。
- **開始後**表單不清空但鎖住，工作卡片出現在下方；可以再貼新網址排隊。
- **去人聲**在按鈕旁有小字「約 1–3 分鐘」。

### 5.2 工作卡片的狀態

| 狀態 | 顯示 |
|---|---|
| 排隊中 | 灰色，「等待中」 |
| 取得資訊 | 步驟 1/3 |
| 下載中 | 步驟 2/3（去人聲為 2/4），百分比來自 yt-dlp progress hook |
| 轉檔 / 分離人聲 | 步驟 3/3（或 3/4、4/4），Demucs 進度來自其 tqdm 輸出解析；解析不到就顯示不定進度條 |
| 完成 | 綠勾，檔名，「顯示檔案」按鈕 → host action `reveal` |
| 失敗 | 紅叉，一句中文訊息，「重試」按鈕；若是 yt-dlp 過期類錯誤，自動更新後重試一次再報錯 |

### 5.3 設定頁（抽屜或獨立區塊）

- 顯示目前輸出資料夾。
- 「選擇資料夾」按鈕 → host action `pick_folder` → 回填 → 寫入設定檔 → 顯示「下次啟動生效」。
- 「結束 vid-snatch」按鈕 → host action `shutdown`。
- 「進階」折疊區：顯示版本、「更新程式」（host action `rebuild`，頁面顯示「更新中，瀏覽器會自動重新開啟」）、「解除安裝」（網頁先問「是否一併刪除已下載的檔案？」，再送 host action `uninstall` 帶參數）。

### 5.4 錯誤訊息中文對照

後端攔 yt-dlp / Demucs 例外，依訊息 pattern 對應：

| 原始訊息片段 | 顯示 |
|---|---|
| `Private video` | 這是私人影片，無法下載 |
| `Sign in to confirm your age` | 這部影片有年齡限制，無法下載 |
| `Video unavailable` | 影片不存在或已被移除 |
| `This live event` | 直播尚未結束，請結束後再試 |
| `Unable to extract` / `HTTP Error 403` | YouTube 改版，正在自動更新下載工具…（更新後重試） |
| 網路類 (`getaddrinfo`, `timed out`) | 無法連線，請檢查網路 |
| 其他 | 發生未知錯誤，點「查看詳情」可展開原始訊息 |

## 6. 後端

### 6.1 程式結構

```
vid_snatch/
  __init__.py
  cli.py          原本的 main()，--web 時轉交 web.py
  core.py         fetch_title / download_audio / download_video / remove_vocals
                  改成接受 progress callback，不再 print、不再 sys.exit
  errors.py       例外 → 中文訊息對照
  web.py          FastAPI app、job queue、SSE、host-actions
  static/index.html   單頁前端（CSS/JS 內嵌）
```

- `core.py` 的函式回傳結果或丟出自訂例外，由 `cli.py` 決定印什麼、由 `web.py` 決定推什麼事件。
- Job queue 一次只跑一個工作（CPU 版 Demucs 同時跑兩個會更慢），其餘排隊。
- 用 `asyncio` + 單一 worker thread（yt-dlp 與 Demucs 都是同步阻塞）。
- SSE 事件格式：`{job_id, state, step, step_total, percent, message, result_path}`。頁面重新整理時，`GET /api/jobs` 回傳現況，再接 SSE。

### 6.2 設定檔

- 宿主機 `~/.config/vid-snatch/` 掛到容器 `/app/config`。
- 內容維持現在的 `output_dir=...` 一行格式，啟動腳本和容器都讀得懂。
- 容器寫入後，下次啟動腳本讀到新路徑就掛新資料夾。

### 6.3 yt-dlp 自動更新

- 容器啟動後背景執行 `pip install -U yt-dlp`，30 秒逾時，失敗不影響使用。
- 下載失敗且錯誤屬於「YouTube 改版」類別時，同步更新一次再重試；仍失敗才回報。
- 因為 `--rm`，更新不會留到下次，每次啟動都要再抓一次（約 3MB，可接受）。

### 6.4 Dockerfile 變更

- 新增 `fastapi`、`uvicorn[standard]`（或 `sse-starlette`）依賴。
- build 時預先下載 Demucs 模型，避免第一次去人聲時卡在下載 80MB。因為要做 multi-arch（見 6.5），arm64 層可能在 QEMU 下 build，所以用 `curl` 直接抓 checkpoint 到 torch hub 快取路徑（`/root/.cache/torch/hub/checkpoints/`），不要在 build 時 import torch 跑 `get_model`。
- `ENTRYPOINT` 不變，`--web` 由 argparse 處理。

### 6.5 預建映像檔

- 新增 GitHub Actions workflow：push 到 `main` 時用 buildx 做 **linux/amd64 + linux/arm64** multi-arch 映像檔，推到 `ghcr.io/irene-chou/vid-snatch:latest`，另外以 commit SHA 打 tag。只推 amd64 的話 Apple Silicon 會透過模擬跑 Demucs，慢數倍。
- 啟動腳本 pull 後檢查映像檔架構與本機一致（`docker image inspect --format '{{.Architecture}}'`），不一致視同 pull 失敗。
- GHCR 套件第一次推上去預設是 private，作者已同意在第一次 CI 推送後到 GitHub Packages 手動改成 public。改之前啟動腳本會 pull 失敗並 fallback 到本地 build，功能不受影響。
- CI 不得把任何 secret 烤進映像檔（build 只用 repo 內容，不傳 build-arg secret）。
- 啟動腳本流程改為：`docker pull ghcr.io/irene-chou/vid-snatch:latest`，成功就 tag 成本地 `vid-snatch`；pull 失敗（離線、GHCR 掛了）且本地沒有映像檔時才 `docker build`。
- 每次啟動都嘗試 pull，等同自動更新；pull 時終端機顯示「正在檢查更新…」。

## 7. 一併納入的宿主端優化

這些是前次討論提到、與網頁版同一批做的項目：

1. **Gatekeeper / SmartScreen**：README 加右鍵開啟的步驟截圖；`.command` 第一次執行時對自己與專案資料夾執行 `xattr -dr com.apple.quarantine`（失敗忽略）。
2. **Docker Desktop 首次啟動**：等待迴圈每 2 秒印一個點；超過 30 秒印「若 Docker Desktop 跳出同意條款視窗，請按 Accept」。
3. **Windows `.bat` 任何錯誤路徑結尾都 `pause`**，不讓視窗秒關。
4. **終端機視窗內容**：開完瀏覽器後只顯示「vid-snatch 執行中，操作請看瀏覽器視窗。關閉此視窗即結束。」，不再印 log。macOS 用 `trap EXIT` 做 `docker stop`。
5. **README 改寫**：以非工程使用者為讀者，步驟化、有截圖；CLI 用法移到最後的「進階」段。

## 8. 留給 builder 決定的事

- FastAPI 之外若想用更輕的框架（如 Starlette 直接用）可以，但要保留 SSE。
- SSE 與輪詢的實作細節、重連策略。
- Demucs 進度解析方式（攔 tqdm、改用 `demucs.api` 的 callback 都可）。
- 前端 CSS 風格，只要乾淨、中文字體正常、跟隨系統深淺色即可。
- 單元測試範圍：至少 `errors.py` 的對照、網址清洗、檔名 sanitize 要有測試；下載本身不必在 CI 真的打 YouTube。
- Windows 助手迴圈用 PowerShell 還是純 bat 實作。
- yt-dlp 熱更新後是重載模組還是改用 subprocess 呼叫。
- 容器路徑 `/app/output/x.mp3` 對應宿主路徑的轉換放在哪一端。
- localhost API 的基本 CSRF 防護方式（例如自訂 header）。
- 套件化後 `static/index.html` 的 package-data 設定。

## 9. 驗收

Windows 與 macOS 都有機器可實測，兩個平台都是驗證交付，不接受「照設計寫但未測」。

- macOS 乾淨機器（僅裝 Docker Desktop）：雙擊 `.command` → 瀏覽器自動打開 → 貼網址 → 按開始 → 看到進度 → 完成 → 按「顯示檔案」Finder 選中該檔。全程不需看終端機。
- Windows 同上，用 `.bat`。
- 貼三個網址、選去人聲，三個依序完成。
- 貼私人影片網址，看到中文錯誤訊息。
- `docker run --rm -it -v ... vid-snatch "URL" --no-vocals` 仍可用，輸出與現在一致。
- 關閉終端機視窗後，`docker ps` 看不到容器。
