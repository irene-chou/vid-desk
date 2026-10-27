# vid-snatch

貼上 YouTube 網址，下載成 MP3 或 MP4，也可以去除人聲。在瀏覽器裡操作，不用打指令。

![vid-snatch 網頁介面](docs/images/web.png)

先[下載 vid-snatch.zip](https://github.com/irene-chou/vid-snatch/releases/latest/download/vid-snatch.zip)並解壓縮，再依你的電腦看下面對應的說明。解壓後會看到兩個啟動檔和一個 `files` 資料夾，`files` 不用打開，但要和啟動檔放在一起。

- [Windows](#windows)
- [Mac](#mac)

## Windows

### 安裝

不用先裝任何東西。直接雙擊 `vid-snatch-Windows.bat`。

- 出現 SmartScreen 藍色視窗時，按「其他資訊」，再按「仍要執行」。
- 如果出現「請先把 vid-snatch.zip 解壓縮」，代表你是在壓縮檔裡直接雙擊的。請先解壓縮，再雙擊解壓後資料夾裡的 `vid-snatch-Windows.bat`。

第一次啟動會自動下載約 1–2 GB，約 10–15 分鐘，視窗會顯示目前進度。中途關掉視窗也沒關係，下次雙擊會接著裝。

需要 64 位元的 Windows 10 或 11。ARM 版 Windows 目前不支援。

### 使用

1. 雙擊 `vid-snatch-Windows.bat`。會跳出一個黑色視窗，瀏覽器也會自動打開 vid-snatch。
2. 貼上 YouTube 網址，可以按「貼上」，一行放一個網址。
3. 選格式：「音檔 MP3」、「去人聲 MP3」或「影片 MP4」。
4. 等每個網址的標題讀完，確認或修改檔名，按「開始」。
5. 完成後，按「顯示檔案」就能在檔案總管裡找到下載好的檔案。

黑色視窗要一直開著。關掉它，vid-snatch 約 15 秒後就會結束。也可以在網頁的「⚙ 設定」裡按「結束 vid-snatch」。

### 常見問題

**防毒軟體擋下載？**
第一次啟動會下載 uv、Python、ffmpeg、deno 和去人聲模型。被防毒軟體擋下時，請允許它們，再重新雙擊 `vid-snatch-Windows.bat`。

**第一次為什麼很慢？**
第一次要下載環境，約 10–15 分鐘，之後幾秒就能打開。

**去人聲要多久？**
一首歌約 3–8 分鐘。

**檔案存在哪裡？**
「音樂」資料夾裡的 `vid-snatch`。音樂資料夾搬到 OneDrive 或其他位置也會跟著。

**怎麼改儲存位置？**
按「⚙ 設定」→「更換資料夾」。下次啟動才會生效。

**怎麼更新？**
每次啟動都會自動檢查更新。想立刻更新，按「⚙ 設定」→「進階」→「更新 vid-snatch」。

**怎麼移除？**
按「⚙ 設定」→「進階」→「解除安裝」，再選要不要一併刪除下載檔案。vid-snatch 安裝的所有東西都在 `%LOCALAPPDATA%\vid-snatch`，會一併刪除。選刪除下載檔案時，只有預設的資料夾會被刪；改過儲存位置的話，請自己刪除。最後再刪掉你解壓縮的 vid-snatch 資料夾即可。

**不小心關掉瀏覽器分頁？**
回到黑色視窗按 Enter，瀏覽器會重新打開。

**下載失敗，顯示「YouTube 改版」？**
vid-snatch 會自動更新下載工具再試一次，不用處理。

## Mac

### 安裝

1. 安裝 [Docker Desktop](https://www.docker.com/products/docker-desktop/)。第一次開啟時若要你同意條款，按 Accept。
2. 雙擊 `vid-snatch-Mac.command`。

第一次雙擊時 macOS 會擋下來：

- 在 Finder 裡對 `vid-snatch-Mac.command` 按右鍵，選「打開」，再按一次「打開」。之後直接雙擊就行。
- 如果沒有「打開」可以按（macOS 15 以後），請到「系統設定」→「隱私權與安全性」，往下找到 vid-snatch-Mac.command 的提示，按「仍要打開」。

第一次啟動要下載環境，約 3-5 分鐘，請耐心等候。

### 使用

1. 雙擊 `vid-snatch-Mac.command`。會跳出一個終端機視窗，瀏覽器也會自動打開 vid-snatch。
2. 貼上 YouTube 網址，可以按「貼上」，一行放一個網址。
3. 選格式：「音檔 MP3」、「去人聲 MP3」或「影片 MP4」。
4. 等每個網址的標題讀完，確認或修改檔名，按「開始」。
5. 完成後，按「顯示檔案」就能在 Finder 裡找到下載好的檔案。

終端機視窗要一直開著。關掉它，vid-snatch 就會結束。也可以在網頁的「⚙ 設定」裡按「結束 vid-snatch」。

### 常見問題

**Docker 跳出同意條款？**
按 Accept。按完後啟動會自動繼續。

**第一次為什麼很慢？**
第一次要下載環境，約 3-5 分鐘，之後就快了。

**去人聲要多久？**
一首歌約 3–8 分鐘。

**檔案存在哪裡？**
預設在 `~/Music/vid-snatch`。

**怎麼改儲存位置？**
按「⚙ 設定」→「更換資料夾」。下次啟動才會生效。

**怎麼更新？**
每次啟動都會自動檢查更新。想立刻更新，按「⚙ 設定」→「進階」→「更新 vid-snatch」。

**怎麼移除？**
按「⚙ 設定」→「進階」→「解除安裝」，再選要不要一併刪除下載檔案。會刪除 vid-snatch 的 Docker 映像檔和設定檔。選刪除下載檔案時，只有預設的資料夾會被刪；改過儲存位置的話，請自己刪除。最後再刪掉你解壓縮的 vid-snatch 資料夾即可。不再需要 Docker 的話，可以另外移除 Docker Desktop。

**不小心關掉瀏覽器分頁？**
回到終端機視窗按 Enter，瀏覽器會重新打開。

**下載失敗，顯示「YouTube 改版」？**
vid-snatch 會自動更新下載工具再試一次，不用處理。

## 進階（工程師）

### Docker 指令列

```bash
# 建置映像檔（只需一次）
docker build -t vid-snatch .

# 下載音檔（MP3）
docker run --rm -it -v ~/Music/vid-snatch:/app/output vid-snatch "URL"

# 下載音檔並去除人聲
docker run --rm -it -v ~/Music/vid-snatch:/app/output vid-snatch "URL" --no-vocals

# 下載影片（MP4）
docker run --rm -it -v ~/Music/vid-snatch:/app/output vid-snatch "URL" --video
```

| 參數 | 說明 |
|------|------|
| `-o, --output` | 輸出資料夾（預設 `./output`） |
| `--video` | 下載影片（MP4），不是音檔 |
| `--no-vocals` | 用 Demucs 去除人聲 |
| `--web` | 啟動網頁介面（啟動腳本使用） |

Demucs 模型已內建在映像檔裡。設定檔在 `~/.config/vid-snatch/config`。

### 本機開發

需要 Python 3.10 以上。

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/pytest -q
```

### Windows 原生執行

Windows 不使用 Docker。`vid-snatch-Windows.bat` 呼叫 `windows/launcher.ps1`，每次啟動從 GitHub `latest` 標籤取得最新原始碼，再執行其中的 `vid-snatch.ps1`。後者用 uv 在 `%LOCALAPPDATA%\vid-snatch` 裡安裝 Python、套件、ffmpeg、deno 與去人聲模型。

- `launcher.ps1` 發出後就無法再更新，修改前請先讀 `vid-snatch.ps1` 開頭的約定。
- 開發時設 `VS_SOURCE=local`，會直接使用本機的原始碼，不從 GitHub 下載。
- `.github/workflows/windows.yml` 在 Windows 上跑 `windows/ci-smoke.ps1`，涵蓋首次安裝、更新、離線、修復與解除安裝。

### 下載包

推送到 `main` 時，GitHub Actions 會用 `scripts/build-package.sh` 產生 `vid-snatch.zip`，發佈到 `latest` Release。

### 預建映像檔

推送到 `main` 時，GitHub Actions 會發佈 amd64 與 arm64 映像檔：

```bash
docker pull ghcr.io/irene-chou/vid-snatch:latest
```
