#!/bin/bash
# 組出單一下載包：<out_dir>/vid-desk.zip
# 最外層只有 vid-desk-Windows.bat、vid-desk-Mac.command 與 files/
set -euo pipefail

[ $# -eq 1 ] || { echo "用法：$0 <out_dir>" >&2; exit 1; }
cd "$(dirname "$0")/.."
REPO="$(pwd)"
mkdir -p "$1"
OUT="$(cd "$1" && pwd)"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# git archive 會套用 .gitattributes 的換行設定（.bat/.ps1 為 CRLF）
mkdir "$WORK/src"
git -C "$REPO" archive HEAD | tar -x -C "$WORK/src"

PKG="$WORK/vid-desk"
mkdir -p "$PKG/files/windows"
cp "$WORK/src/vid-desk-Windows.bat" "$WORK/src/vid-desk-Mac.command" "$PKG/"
cp "$WORK/src/vid-desk.ps1" "$WORK/src/Dockerfile" "$WORK/src/pyproject.toml" "$PKG/files/"
cp "$WORK/src/windows/launcher.ps1" "$PKG/files/windows/"
cp -R "$WORK/src/vid_desk" "$PKG/files/vid_desk"
chmod +x "$PKG/vid-desk-Mac.command"

rm -f "$OUT/vid-desk.zip"
(cd "$WORK" && zip -qr "$OUT/vid-desk.zip" vid-desk)
echo "已產生 $OUT/vid-desk.zip"
