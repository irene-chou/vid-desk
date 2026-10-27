# 控制台介面設計（方向 A）

日期：2026-10-27。互動版面：`docs/design/console-mockup.html`（直接用瀏覽器開，右上可切深淺色，桌面與 390px 手機兩種寬度，checkbox 與分段開關可點）。

## 目的

現有 `vid_snatch/static/index.html` 功能完整但簡陋。這次改版目標是質感與直觀，不拘泥原有排版。同時納入兩個功能需求：輸出選項改為 checkbox 多選（含細項），排隊卡片顯示更多細節。

## 目標 / 非目標

- 目標：單一 HTML 檔、無打包流程、不依賴 CDN 元件庫；離線時版面不壞。
- 目標：深淺色都要檢查對比；所有只有圖示的按鈕都有 `aria-label` 與 `title`。
- 非目標：不改 Docker / Windows 封裝流程；不引入 Alpine、Preact 等框架。

## 資訊架構

輸出只有兩個大選項，去人聲併入音檔：

```
輸出
├─ ☑ 音檔                      摘要：MP3 · 原曲 + 伴奏
│   ├─ 版本（可多選，常駐顯示）  ☑ 原曲   ☑ 伴奏（去人聲）   ☐ 人聲
│   └─ 細項（收合）
│       ├─ 格式      MP3 · M4A · WAV · FLAC（有損格式固定 192k，#18 拿掉位元率選項）
│       └─ 分離模型  快速 htdemucs · 高品質 htdemucs_ft
└─ ☐ 影片                      摘要：MP4 · 最佳畫質
    └─ 畫質上限  最佳 · 1080p · 720p
```

規則：

- 「版本」不收進細項，伴奏是最常用功能。
- 選項卡標題右側顯示摘要文字，細項收合時仍看得到目前設定。
- 分離模型只在勾了伴奏或人聲時有意義，未勾時該列變灰。
- 細項記在設定裡、下次啟動沿用；「版本」每次啟動回到預設「原曲」，避免誤跑一次 3–8 分鐘的分離。
- 「開始」按鈕顯示將產生的檔案數（網址數 × 輸出檔數）。
- 至少勾一個大選項、音檔至少勾一個版本，否則「開始」停用。

## 版面

- 桌面：雙欄 grid（5:6），左欄輸入面板，右欄排隊。手機（容器 ≤ 760px）堆疊，輸入在上。
- 頂部：logo + 名稱；排隊 / 處理中 / 完成 / 失敗四個計數（圖示 + 數字，窄版隱藏）；右側設定圖示鈕。
- 設定：齒輪開啟置中 modal（原生 `<dialog>` + `showModal()`，與 `ask()` 共用樣式與 backdrop），開關不推擠版面。桌面 480px 置中，≤ 390px 貼齊左右 16px 邊距；內容過高時 dialog 內捲、頁面不捲。關閉：右上關閉鈕、Esc、點 backdrop，關閉後焦點回齒輪。內容：下載資料夾 / 更換資料夾 / 結束；「進階」收合：更新、解除安裝，狀態訊息與按鈕列間距 8px。從設定內觸發 `ask()` 時疊在設定上層，關閉後回到設定。
- 左欄由上到下：網址（textarea，右上貼上鈕）、輸出（兩張選項卡）、檔名（每個網址一列，上方小字為網址）、開始。
- 右欄：「進行中與排隊」區；「已完成」分隔線（右側清除鈕）；卡片依新到舊。

## 排隊卡片

一個網址一張卡片，左邊 3px 狀態色條（進行中 accent、完成 ok、失敗 bad、排隊 line）。內容：

1. 標題列：檔名（粗體）＋右側狀態（等寬字）：排隊 `#n`、進行中 `2/3 · 分離`、完成 `0:41`（耗時）、失敗 `1/3 · 下載`。
2. 細節列（圖示 + 等寬小字）：來源網址（可點，開新分頁）、YouTube 原標題、完成後顯示已存檔名與大小。
3. 輸出列：每個輸出檔一顆膠囊，含類型圖示、檔名尾綴、自己的狀態圖示（時鐘等待 / 轉圈處理中 / 勾完成 / 叉失敗）。
4. 進行中：進度條 + 百分比 + `已耗時 / 預估總時`。
5. 動作列（右對齊圖示鈕）：排隊中「取消」；完成「顯示檔案」；失敗「查看詳情」「重試」；已取消「重試」。
6. 失敗訊息：警示圖示 + 一句中文說明。

實作細節（#11 定案）：

- 膠囊文字：音檔 `原曲.mp3`（`ext` 以 `output.ext` 為準，與 `format` 相同；#18 之後不顯示位元率），影片 `.mp4 · 1080p`（最佳畫質只有 `.mp4`）。膠囊狀態圖示只在工作執行中、完成或失敗時顯示；排隊中與已取消的卡片不顯示（全是時鐘沒有資訊）。
- 細節列的「已存檔名與大小」每個完成的輸出一列（失敗工作裡已完成的輸出也列）。
- 耗時：收到 job 時記下 `elapsed_seconds` / `eta_seconds` 與本機時刻，之後前端每秒加上本機經過的時間；不拿本機時鐘去減伺服器的 `started_at`（避免時鐘差）。預估總時 = 收到時的已耗時 + `eta_seconds`，下一則 SSE 前不會往下掉；已耗時超過預估就顯示相同數字。頁面上沒有進行中的卡片時計時器停掉。
- 分組：`#jobs`（進行中與排隊）與 `#jobs-done`（已完成）兩個 `ul`；工作變成 `done` / `failed` / `cancelled` 時卡片搬到已完成區最上面。「清除已完成」只在前端隱藏（記住 id，SSE 重連重播時不畫回來），後端不刪。
- 已取消（`cancelled`）：卡片併入「已完成」區，狀態文字「已取消」、圖示 x、色條與排隊相同（`--line`），動作列只有「重試」（重試會建立新工作）；頂部計數不算已取消。
- 「查看詳情」展開狀態以 id 記住，SSE 重畫卡片後維持展開。

## 視覺 token

- 字體：IBM Plex Sans（UI）、IBM Plex Mono（網址、檔名、數字、狀態）、中文 Noto Sans TC；皆由 Google Fonts 載入，離線退回 `-apple-system, "PingFang TC", "Microsoft JhengHei"` 與 `ui-monospace, Menlo, Consolas`。
- 淺色：bg #f5f6f8、panel #ffffff、fg #16181d、muted #6b7280、line #e2e4e9、sub #eef0f3、accent #0f766e（字 #ffffff）、ok #15803d、bad #b91c1c、warn #b45309。
- 深色：bg #0f1114、panel #171a1f、fg #e6e8ec、muted #8b919c、line #262a31、sub #1f232a、accent #2dd4bf（字 #06201c）、ok #4ade80、bad #f87171、warn #fbbf24。
- 圓角：面板 12px、選項卡 10px、按鈕 8px、膠囊 999px。圖示鈕 34px，小型 28px。
- 圖示：Lucide，24 格 2px 線，內嵌一個 `<svg><symbol>` sprite（mockup 內已含全部 symbol，可直接複製）。
- 動畫：轉圈 1s linear；`prefers-reduced-motion` 時停止。

## 圖示對照

音檔 music、影片 film、原曲 disc、伴奏 mic-off、人聲 mic、細項 sliders、快速 zap、高品質 gem、貼上 clipboard-paste、開始 play、排隊 clock、處理中 loader-circle、完成 circle-check、失敗 circle-x、來源 link、原標題 type、已存檔案 file、顯示檔案 folder、重試 refresh-cw、查看詳情 eye、取消 x、清除已完成 trash、設定 settings、錯誤 triangle-alert。

保留文字的地方：選項名稱、段落標題、錯誤訊息、「開始」。

## 後端需要配合的改動（#9，已完成）

- 工作模型從單一 `mode` 改為「一個網址、多個輸出」，每個輸出有自己的狀態與結果路徑。
- 工作事件多回傳：原標題、各輸出狀態、開始時間 / 耗時、預估剩餘、結果檔大小。
- 細項（格式、模型、畫質）存進設定檔並能讀回。
- 音檔 M4A/WAV/FLAC、影片畫質上限、demucs 模型切換、人聲輸出。

定案的 API 如下，#10（輸入面板）與 #11（排隊卡片）以此為準。所有 `POST` / `DELETE` 都要帶 `X-Vid-Snatch: 1`，錯誤回應一律 `{"message": "<中文>"}`（語意錯誤 400；型別或列舉不符由 FastAPI 回 422）。

## 後端 API（#9 定案，#11 補取消）

### 列舉

| 名稱 | 值 | 說明 |
|---|---|---|
| version / kind | `original` `instrumental` `vocals` `video` | 前三個是音檔版本（原曲 / 伴奏 / 人聲），`video` 只出現在輸出列 |
| format | `mp3` `m4a` `wav` `flac` | 音檔格式，預設 `mp3`；有損格式固定 192 kbps（#18 拿掉 `bitrate` 參數，收到會忽略） |
| model | `htdemucs` `htdemucs_ft` | 分離模型（快速 / 高品質），預設 `htdemucs_ft`，兩個都已預載 |
| max_height | `null` `1080` `720` | 影片畫質上限，`null` = 最佳 |
| job.state | `queued` `running` `done` `failed` `cancelled` | 工作狀態；`cancelled` 只會由 `DELETE /api/jobs/{id}` 產生 |
| output.state | `queued` `running` `done` `failed` | 單一輸出的狀態 |

### `POST /api/jobs`

```json
{
  "urls": ["https://youtu.be/…", "…"],
  "outputs": {
    "audio": { "versions": ["original", "instrumental"], "format": "mp3", "model": "htdemucs_ft" },
    "video": { "max_height": 1080 }
  },
  "filenames": ["自訂檔名", null],
  "overwrites": [false, true]
}
```

- `outputs` 整批共用。`audio` / `video` 任一可為 `null` 或省略，但不能兩個都沒有（400「至少要選一種輸出」）。`audio.versions` 至少一個（400「音檔至少要勾一個版本」）；重複會去掉，順序一律整理成 原曲 → 伴奏 → 人聲。`format` / `model` / `max_height` 省略時用上表預設（不是設定檔的值；前端要自己把 `GET /api/settings` 讀到的細項填進來）。`audio.bitrate` 已移除：舊分頁送來時忽略，不回 422。
- `filenames` / `overwrites` 與 `urls` 等長（可省略；單一網址也可用舊的 `filename` / `overwrite`）。空字串檔名視為「用原標題」。
- 回應 `{"jobs": [job, …]}`，job 結構見下。
- 檔名規則：原曲 `<name>.<format>`、伴奏 `<name>_no_vocals.<ext>`、人聲 `<name>_vocals.<ext>`、影片 `<name>.mp4`。分離結果的 `ext` 與 `format` 相同；demucs 只能直接寫 mp3 / wav / flac，`m4a` 時後端先寫暫存 wav 再用 ffmpeg 轉成 `.m4a`（192k），暫存檔處理完即刪除。
- 執行順序：取得資訊 → 下載音訊一次（需分離時下載 wav，否則直接下載目標格式）→ 轉檔（原曲）→ 分離（一次 demucs 同時產出伴奏與人聲）→ 下載影片 → 合併。過程中的 `<name>.wav` 會刪掉，除非原曲格式就是 wav。

### `GET /api/exists`

Query：`filename`（必填）、`versions`（逗號分隔，例如 `original,instrumental`；不勾音檔就留空）、`format`（預設 `mp3`）、`video`（`true` / `false`，預設 `false`）。`versions` 與 `video` 不能都沒有（400）。

```json
{ "exists": true, "suggestion": "song (1)", "files": ["song (1).mp3", "song (1)_no_vocals.mp3"] }
```

- `exists`：以 `filename` 為主體時，任一會寫入的檔（含過程中的 `<name>.wav`）已存在。
- `suggestion`：建議改用的檔名主體（不存在衝突時等於清理後的 `filename`）。
- `files`：採用 `suggestion` 時會產生的檔名（含副檔名），依輸出順序。

### job（`POST /api/jobs` 回應、`GET /api/jobs` 的 `jobs[]`、`/api/events` 每則 `event: job` 的 data）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | string | 8 碼 |
| `url` | string | 清理後的來源網址 |
| `filename` | string \| null | 使用者自訂的檔名主體；null 表示用原標題 |
| `overwrite` | bool | 允許覆蓋既有檔 |
| `options` | object | 送進來的 `outputs`，補齊預設後的樣子：`{"audio": {"versions","format","model"} \| null, "video": {"max_height"} \| null}`，膠囊摘要（`MP3`、`1080p`）由此組出 |
| `outputs` | Output[] | 每個輸出檔一筆，順序固定 原曲 → 伴奏 → 人聲 → 影片 |
| `steps` | string[] | 這個工作的步驟名稱，依 `options` 動態組成，例如 `["取得資訊","下載","轉檔","分離","下載影片","合併"]`（只有影片時是 `["取得資訊","下載","合併"]`） |
| `state` | `queued` `running` `done` `failed` `cancelled` | 工作狀態 |
| `step` | int | 目前（或失敗時停住、完成時最後）的步驟，1-based；排隊中為 0 |
| `step_total` | int | `steps.length` |
| `step_name` | string | `steps[step-1]`；排隊中為空字串。卡片狀態文字即 `` `${step}/${step_total} · ${step_name}` `` |
| `percent` | number \| null | 目前步驟的百分比 0–100；null 表示不定進度。完成時 100 |
| `message` | string | 失敗時的中文說明 |
| `detail` | string | 失敗時的原始錯誤（「查看詳情」） |
| `error_kind` | string \| null | `private` `age` `unavailable` `live` `extractor_outdated` `network` `unknown` |
| `result_path` | string \| null | 第一個完成輸出的完整路徑（「顯示檔案」用；向下相容） |
| `title` | string \| null | YouTube 原標題，第 1 步結束後才有（即使使用者自訂檔名也會取） |
| `display_name` | string \| null | 實際採用的檔名主體（已處理重名後綴），第 1 步結束後才有 |
| `queue_position` | int \| null | 排隊中的順位，1 = 下一個；非排隊狀態為 null。前面的工作開跑時，後面每張卡都會收到一則更新 |
| `created_at` | number | 建立時間，Unix 秒 |
| `started_at` | number \| null | 開始執行時間（Unix 秒） |
| `finished_at` | number \| null | 完成、失敗或取消時間（Unix 秒） |
| `elapsed_seconds` | number \| null | 序列化當下的耗時（`(finished_at ?? now) - started_at`）；進行中請用前端計時器以 `started_at` 每秒更新，不要等 SSE |
| `eta_seconds` | number \| null | 目前步驟預估剩餘秒數，由該步已耗時與 `percent` 推算（分離時來自 demucs callback）；沒有進度或不在執行中為 null。「預估總時」= 已耗時 + `eta_seconds` |

Output：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `kind` | `original` `instrumental` `vocals` `video` | 類型（決定圖示） |
| `ext` | string | 實際副檔名（`mp3` `m4a` `wav` `flac` `mp4`） |
| `state` | `queued` `running` `done` `failed` | 原曲在「下載 / 轉檔」時 running；伴奏與人聲在「分離」時同時 running；影片在「下載影片 / 合併」時 running。工作失敗時所有未完成的輸出都變 `failed` |
| `filename` | string \| null | 檔名（含副檔名），第 1 步結束後就有 |
| `result_path` | string \| null | 完成後的完整路徑 |
| `size_bytes` | int \| null | 完成後的檔案大小 |

SSE：`GET /api/events` 連上先重播所有既有工作，之後任一欄位（含任一輸出狀態、佇列順位）變動就推一整個 job。

其他端點不變：`GET /api/info?url=`、`POST /api/jobs/{id}/retry`（沿用原工作的 `options`；已取消的工作也能重試，會建立新工作）、`POST /api/jobs/{id}/reveal`（用 `result_path`）。

### `DELETE /api/jobs/{id}`（#11 新增）

取消排隊中的工作。需帶 `X-Vid-Snatch: 1`（與 `POST` 相同，防 CSRF）。

- 只對 `state == "queued"` 生效：工作 `state` 改為 `cancelled`、`finished_at` 設為當下、`queue_position` 變 `null`，從佇列移除（worker 取到已取消的工作會直接跳過）；後面排隊中的工作 `queue_position` 往前補，每張都會收到一則 SSE 更新。回應 200 + 取消後的 job dict；同一則 job 也會經 `/api/events` 推送。
- 其他狀態（執行中、完成、失敗、已取消）回 409 `{"message": "只能取消排隊中的工作"}`；找不到回 404 `{"message": "找不到這個工作"}`。
- `outputs[].state` 維持 `queued`（輸出沒有 `cancelled` 狀態）；`started_at` / `elapsed_seconds` 為 `null`。

### `GET /api/settings` / `POST /api/settings`

```json
{ "output_dir": "/Users/me/Music/vid-snatch", "audio_format": "mp3", "demucs_model": "htdemucs_ft", "video_max_height": null }
```

- `GET` 回傳上述四個欄位；`output_dir` 是目前執行中的資料夾，細項來自設定檔，缺少或不合法的 key 用預設值（`mp3` / `htdemucs_ft` / `null`）補齊。舊設定檔殘留的 `audio_bitrate=` 行安靜略過，下次寫回時丟掉；`POST` 收到 `audio_bitrate` 也忽略不報 422（#18）。
- `POST` 可只送要改的欄位；沒送的維持原值。`video_max_height` 送 `null` 表示不限畫質。回應 = 更新後的四個欄位 + `restart_required`（只有送了 `output_dir` 才是 `true`）。`output_dir` 空白回 400。
- 「版本」（原曲 / 伴奏 / 人聲）不存設定，每次載入回到預設「原曲」。
- 設定檔 `config` 每行 `key=value`，`output_dir` 永遠在第一行；bash / bat / ps1 啟動腳本只讀那一行，其餘行會被略過。
