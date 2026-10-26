#!/bin/bash
# vid-snatch 一鍵啟動腳本
# 雙擊此檔案即可使用

cd "$(dirname "$0")"

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

save_config() {
    mkdir -p "$CONFIG_DIR"
    echo "output_dir=$1" > "$CONFIG_FILE"
}

load_config

# ── 檢查 Docker ─────────────────────────────
if ! command -v docker &> /dev/null; then
    echo "============================================"
    echo "  需要先安裝 Docker Desktop"
    echo "  下載：https://docker.com/products/docker-desktop/"
    echo "============================================"
    read -n 1 -p "按任意鍵開啟下載頁面..."
    open "https://www.docker.com/products/docker-desktop/"
    exit 1
fi

# 檢查 Docker 是否正在執行
if ! docker info &> /dev/null 2>&1; then
    echo "正在啟動 Docker Desktop..."
    open -a Docker
    while ! docker info &> /dev/null 2>&1; do
        sleep 2
    done
    echo "Docker 已就緒！"
fi

# 首次 build
if ! docker image inspect vid-snatch &> /dev/null 2>&1; then
    echo ""
    echo "首次使用，正在建置環境（約 3-5 分鐘）..."
    echo ""
    docker build -t vid-snatch .
    echo ""
    echo "建置完成！"
fi

# ── 主迴圈 ───────────────────────────────────
while true; do
    echo ""
    echo "============================================"
    echo "  vid-snatch"
    echo "============================================"
    echo ""
    echo "  1) 下載音檔 (MP3)"
    echo "  2) 下載去人聲音檔 (MP3)"
    echo "  3) 下載影片 (MP4)"
    echo "  4) 設定"
    echo "  5) 重新建置 (更新程式後使用)"
    echo "  6) 解除安裝"
    echo "  q) 離開"
    echo ""
    read -p "請選擇 [1/2/3/4/5/6/q]: " choice

    case "$choice" in
        1|2|3)
            echo ""
            read -p "請貼上 YouTube 網址: " url

            if [ -z "$url" ]; then
                echo "網址不能為空！"
                continue
            fi

            # 確保輸出資料夾存在
            mkdir -p "$OUTPUT_DIR"

            # 組裝指令
            cmd=()
            case "$choice" in
                2) cmd+=("--no-vocals") ;;
                3) cmd+=("--video") ;;
            esac

            echo ""
            echo "處理中..."
            [ "$choice" = "2" ] && echo "(去人聲需要 3-8 分鐘，首次會先下載約 320MB 模型，請耐心等候)"
            echo ""

            docker run --rm -it \
                -v "$OUTPUT_DIR:/app/output" \
                -v vid-snatch-models:/root/.cache/torch \
                vid-snatch "$url" "${cmd[@]}"

            echo ""
            echo "============================================"
            echo "  完成！檔案已存到："
            echo "  $OUTPUT_DIR"
            echo "============================================"

            # 開啟資料夾
            open "$OUTPUT_DIR" 2>/dev/null
            ;;
        4)
            echo ""
            echo "============================================"
            echo "  設定"
            echo "============================================"
            echo ""
            echo "  目前儲存路徑: $OUTPUT_DIR"
            echo ""
            read -p "輸入新路徑（按 Enter 保持不變）: " new_dir

            if [ -n "$new_dir" ]; then
                # 展開 ~ 為 $HOME
                new_dir="${new_dir/#\~/$HOME}"
                mkdir -p "$new_dir" 2>/dev/null

                if [ -d "$new_dir" ]; then
                    save_config "$new_dir"
                    OUTPUT_DIR="$new_dir"
                    echo ""
                    echo "  ✓ 路徑已更新為: $OUTPUT_DIR"
                else
                    echo ""
                    echo "  ✗ 無法建立資料夾: $new_dir"
                fi
            else
                echo "  路徑未變更。"
            fi
            ;;
        5)
            echo ""
            read -p "確定要重新建置嗎？這會需要 3-5 分鐘 [y/N]: " confirm
            if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
                echo "已取消。"
                continue
            fi
            echo ""
            echo "移除舊版本..."
            docker rmi vid-snatch 2>/dev/null
            docker builder prune -f 2>/dev/null
            echo "重新建置中（約 3-5 分鐘）..."
            docker build -t vid-snatch .
            echo ""
            echo "建置完成！舊的暫存檔已清除。"
            ;;
        6)
            echo ""
            echo "============================================"
            echo "  解除安裝 vid-snatch"
            echo "============================================"
            echo ""
            read -p "確定要解除安裝嗎？(y/N): " confirm
            if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
                echo "已取消。"
                continue
            fi

            echo ""
            echo "移除 Docker 映像檔..."
            docker rmi vid-snatch 2>/dev/null
            docker builder prune -f 2>/dev/null

            echo "移除設定檔..."
            rm -rf "$CONFIG_DIR"

            read -p "是否也刪除您先前下載的音檔與影片？($OUTPUT_DIR) (y/N): " del_output
            if [ "$del_output" = "y" ] || [ "$del_output" = "Y" ]; then
                rm -rf "$OUTPUT_DIR"
                echo "已刪除下載檔案。"
            fi

            echo ""
            echo "============================================"
            echo "  解除安裝完成！"
            echo "  如需完全移除，可手動刪除此專案資料夾："
            echo "  $(pwd)"
            echo "============================================"
            exit 0
            ;;
        q|Q)
            echo "Bye!"
            exit 0
            ;;
        *)
            echo "無效選擇，請輸入 1、2、3、4、5、6 或 q"
            ;;
    esac
done
