#!/bin/bash
# vid-snatch 一鍵啟動腳本
# 雙擊此檔案即可使用

cd "$(dirname "$0")" || exit 1
xattr -dr com.apple.quarantine "$(dirname "$0")" 2>/dev/null || true

IMAGE_REMOTE="ghcr.io/irene-chou/vid-snatch:latest"
IMAGE_LOCAL="vid-snatch"
CONTAINER="vid-snatch"
DEFAULT_PORT=8080
PORT="$DEFAULT_PORT"
PROJECT_DIR="$(pwd)"
# 下載包配置：原始碼在 files/；repo 配置：原始碼就在這個資料夾
BUILD_DIR="$PROJECT_DIR"
[ -f "$PROJECT_DIR/files/Dockerfile" ] && BUILD_DIR="$PROJECT_DIR/files"

# ── 設定檔 ──────────────────────────────────
CONFIG_DIR="$HOME/.config/vid-snatch"
CONFIG_FILE="$CONFIG_DIR/config"
DEFAULT_OUTPUT_DIR="$HOME/Music/vid-snatch"

load_config() {
    OUTPUT_DIR="$DEFAULT_OUTPUT_DIR"
    if [ -f "$CONFIG_FILE" ]; then
        saved_dir=$(grep '^output_dir=' "$CONFIG_FILE" | cut -d'=' -f2-)
        if [ -n "$saved_dir" ]; then
            # 展開 ~ 為 $HOME
            OUTPUT_DIR="${saved_dir/#\~/$HOME}"
        fi
    fi
}

# ── Docker ──────────────────────────────────
ensure_docker() {
    if ! command -v docker &> /dev/null; then
        echo "============================================"
        echo "  需要先安裝 Docker Desktop"
        echo "  下載：https://docker.com/products/docker-desktop/"
        echo "============================================"
        read -n 1 -p "按任意鍵開啟下載頁面..."
        open "https://www.docker.com/products/docker-desktop/"
        exit 1
    fi

    if ! docker info &> /dev/null 2>&1; then
        echo "正在啟動 Docker Desktop..."
        open -a Docker
        local waited=0 warned=0
        while ! docker info &> /dev/null 2>&1; do
            sleep 2
            waited=$((waited + 2))
            printf "."
            if [ "$waited" -gt 30 ] && [ "$warned" -eq 0 ]; then
                warned=1
                echo ""
                echo "若 Docker Desktop 跳出同意條款視窗，請按 Accept"
            fi
        done
        echo ""
        echo "Docker 已就緒！"
    fi
}

# macOS 沒有 timeout 指令：在限定秒數內執行指令，逾時就砍掉並回傳 124
run_with_timeout() {
    local secs="$1" pid ticks=0
    shift
    "$@" &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$ticks" -ge $((secs * 5)) ]; then
            kill "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
            return 124
        fi
        sleep 0.2
        ticks=$((ticks + 1))
    done
    wait "$pid"
}

want_arch() {
    case "$(uname -m)" in
        arm64) echo "arm64" ;;
        x86_64) echo "amd64" ;;
        *) uname -m ;;
    esac
}

# 只問 registry 遠端 :latest 現在指到哪些 digest（manifest list 與各平台 manifest），不下載映像檔。
# 用 buildx imagetools（Docker Desktop 內建，不須登入），逐行抓 sha256，不依賴輸出格式或 jq。
remote_digests() {
    local out
    out="$(run_with_timeout 15 docker buildx imagetools inspect "$IMAGE_REMOTE" 2>/dev/null)" || return 1
    out="$(printf '%s\n' "$out" | grep -oE 'sha256:[0-9a-f]{64}' | sort -u)"
    [ -n "$out" ] && printf '%s\n' "$out"
}

# 本機映像檔是從哪個 digest 拉下來的（本機自行 build 的沒有 RepoDigests → 空字串）
local_digests() {
    docker image inspect --format '{{range .RepoDigests}}{{.}} {{end}}' "$IMAGE_LOCAL" 2>/dev/null
}

# 0 = 已是最新版；1 = 有新版；2 = 離線或無法比對
image_up_to_date() {
    local remote local_ d
    remote="$(remote_digests)" || return 2
    local_="$(local_digests)" || return 1
    for d in $remote; do
        case " $local_" in *"@$d "*) return 0 ;; esac
    done
    return 1
}

# 下載遠端映像檔並確認架構相符，進度直接顯示在終端機
pull_image() {
    docker pull "$IMAGE_REMOTE" \
        && [ "$(docker image inspect --format '{{.Architecture}}' "$IMAGE_REMOTE" 2>/dev/null)" = "$(want_arch)" ] \
        && docker tag "$IMAGE_REMOTE" "$IMAGE_LOCAL"
}

ensure_image() {
    if ! docker image inspect "$IMAGE_LOCAL" &> /dev/null; then
        echo ""
        echo "正在下載 vid-snatch（約 1 GB，第一次或大改版可能要幾分鐘）…"
        echo ""
        if pull_image; then
            echo ""
            echo "下載完成！"
            return 0
        fi
        echo ""
        echo "下載失敗，改為在本機建置環境（約 3-5 分鐘）…"
        echo ""
        docker build -t "$IMAGE_LOCAL" "$BUILD_DIR"
        echo ""
        echo "建置完成！"
        return 0
    fi

    echo "正在檢查更新…"
    local status=0
    image_up_to_date || status=$?
    case "$status" in
        0)
            echo "已是最新版"
            ;;
        1)
            echo "發現新版本，正在下載…（第一次或大改版可能要幾分鐘）"
            echo ""
            if pull_image; then
                echo ""
                echo "更新完成！"
            else
                echo ""
                echo "下載失敗，先用目前版本啟動"
            fi
            ;;
        *)
            echo "無法檢查更新，先用目前版本啟動"
            ;;
    esac
}

container_running() {
    [ -n "$(docker ps -q -f "name=^${CONTAINER}\$")" ]
}

read_port() {
    local p
    p="$(docker port "$CONTAINER" 8080 2>/dev/null | head -n 1 | sed 's/.*://')"
    echo "${p:-$DEFAULT_PORT}"
}

start_or_attach() {
    if container_running; then
        PORT="$(read_port)"
        return 0
    fi
    local p="$DEFAULT_PORT"
    while lsof -iTCP:"$p" -sTCP:LISTEN &> /dev/null; do
        p=$((p + 1))
    done
    PORT="$p"
    mkdir -p "$OUTPUT_DIR" "$CONFIG_DIR"
    docker run -d --rm --name "$CONTAINER" -p "127.0.0.1:$PORT:8080" \
        -v "$OUTPUT_DIR:/app/output" \
        -v "$CONFIG_DIR:/app/config" \
        -e VS_HOST_OUTPUT_DIR="$OUTPUT_DIR" \
        "$IMAGE_LOCAL" --web > /dev/null
}

wait_health() {
    local i
    for i in $(seq 1 120); do
        if curl -sf "localhost:$PORT/api/health" > /dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
    done
    echo ""
    echo "啟動失敗，請把這個視窗的內容截圖給開發者"
    echo ""
    docker logs "$CONTAINER" 2>&1 | tail -20
    echo ""
    read -n 1 -p "按任意鍵關閉..."
    exit 1
}

open_browser() {
    if [ "$VS_NO_BROWSER" = "1" ]; then
        echo "http://localhost:$PORT"
    else
        open "http://localhost:$PORT"
    fi
}

cleanup() {
    docker stop "$CONTAINER" > /dev/null 2>&1 || true
}

# ── 主機端動作 ──────────────────────────────
post_result() {
    # $1 = action id, $2 = JSON body
    curl -s -m 5 -X POST -H 'X-Vid-Snatch: 1' -H 'Content-Type: application/json' \
        -d "$2" "localhost:$PORT/api/host-actions/$1/result" > /dev/null 2>&1
}

pick_folder() {
    # 在背景執行，避免對話框開著時中斷心跳
    local id="$1" picked body
    (
        if picked=$(osascript -e 'tell application "System Events" to activate' -e 'tell application "System Events" to POSIX path of (choose folder with prompt "選擇下載資料夾")' 2>/dev/null); then
            [ "$picked" != "/" ] && picked="${picked%/}"
        else
            picked=""
        fi
        body=$(osascript -l JavaScript -e 'function run(argv){ return JSON.stringify({path: argv[0] || null}) }' "$picked")
        post_result "$id" "$body"
    ) > /dev/null 2>&1 &
}

do_uninstall() {
    local delete_downloads="$1"
    echo ""
    echo "移除 Docker 映像檔..."
    docker stop "$CONTAINER" > /dev/null 2>&1 || true
    docker rmi "$IMAGE_LOCAL" "$IMAGE_REMOTE" > /dev/null 2>&1 || true
    docker builder prune -f > /dev/null 2>&1 || true
    echo "移除設定檔..."
    rm -rf "$CONFIG_DIR"
    if [ "$delete_downloads" = "1" ]; then
        local out="${OUTPUT_DIR%/}" def="${DEFAULT_OUTPUT_DIR%/}"
        if [ -n "$out" ] && [ "$out" = "$def" ]; then
            rm -rf "$out"
            echo "已刪除下載檔案。"
        else
            echo "下載資料夾不是預設位置，為了安全不會自動刪除，如需要請自行刪除：$OUTPUT_DIR"
        fi
    fi
    echo ""
    echo "============================================"
    echo "  解除安裝完成！"
    echo "  如需完全移除，可手動刪除此專案資料夾："
    echo "  $PROJECT_DIR"
    echo "============================================"
    exit 0
}

do_rebuild() {
    echo "正在更新…"
    load_config
    docker stop "$CONTAINER" > /dev/null 2>&1 || true
    local w
    for w in $(seq 1 20); do
        [ -z "$(docker ps -aq -f "name=^${CONTAINER}\$")" ] && break
        sleep 0.5
    done
    docker rmi "$IMAGE_LOCAL" > /dev/null 2>&1 || true
    ensure_image
    if ! start_or_attach; then
        echo "重新啟動失敗"
        docker logs "$CONTAINER" 2>&1 | tail -20
        read -n 1 -p "按任意鍵關閉..."
        exit 1
    fi
    wait_health
    open_browser
}

host_loop() {
    echo ""
    echo "vid-snatch 執行中，操作請看瀏覽器視窗。誤關了？按 Enter 重新開啟。關閉此視窗即結束。"

    local json parsed id kind path del fails=0
    while true; do
        if json=$(curl -sf -m 3 "localhost:$PORT/api/host-actions" 2>/dev/null); then
            fails=0
            parsed=$(osascript -l JavaScript -e 'function run(argv){ const a = JSON.parse(argv[0]).actions; return a.map(x => [x.id, x.kind, (x.payload && x.payload.path) || "", (x.payload && x.payload.delete_downloads) ? "1" : "0"].join("\x1f")).join("\n") }' "$json" 2>/dev/null)
            if [ -n "$parsed" ]; then
                while IFS=$'\x1f' read -r id kind path del; do
                    [ -z "$id" ] && continue
                    case "$kind" in
                        reveal)      open -R "$path" ;;
                        pick_folder) pick_folder "$id" ;;
                        shutdown)    exit 0 ;;
                        rebuild)     do_rebuild ;;
                        uninstall)   do_uninstall "$del" ;;
                    esac
                done <<< "$parsed"
            fi
        else
            fails=$((fails + 1))
            if [ "$fails" -ge 3 ] && ! container_running; then
                echo "vid-snatch 已停止。"
                exit 0
            fi
        fi

        if [ -t 0 ]; then
            if read -r -t 1 -s; then
                open_browser
            fi
        else
            sleep 1
        fi
    done
}

# 測試以 source 載入時只取函式，不跑主流程（tests/test_mac_command.py）
[ "${BASH_SOURCE[0]}" != "$0" ] && return 0

# ── 主流程 ──────────────────────────────────
load_config
ensure_docker

if container_running; then
    PORT="$(read_port)"
    echo "vid-snatch 已經在執行中，已幫你打開瀏覽器。"
    open_browser
    exit 0
fi

ensure_image
if ! start_or_attach; then
    echo "啟動失敗，請把這個視窗的內容截圖給開發者"
    read -n 1 -p "按任意鍵關閉..."
    exit 1
fi
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
wait_health
open_browser
host_loop
