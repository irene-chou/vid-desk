#!/bin/bash
# 組出單一下載包：<out_dir>/vid-snatch.zip
# 最外層只有 vid-snatch-Windows.bat、vid-snatch-Mac.command 與 files/
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

PKG="$WORK/vid-snatch"
mkdir -p "$PKG/files/windows"
cp "$WORK/src/vid-snatch-Windows.bat" "$WORK/src/vid-snatch-Mac.command" "$PKG/"
cp "$WORK/src/vid-snatch.ps1" "$WORK/src/Dockerfile" "$WORK/src/pyproject.toml" "$PKG/files/"
cp "$WORK/src/windows/launcher.ps1" "$PKG/files/windows/"
cp -R "$WORK/src/vid_snatch" "$PKG/files/vid_snatch"
chmod +x "$PKG/vid-snatch-Mac.command"

rm -f "$OUT/vid-snatch.zip"
(cd "$WORK" && zip -qr "$OUT/vid-snatch.zip" vid-snatch)
echo "已產生 $OUT/vid-snatch.zip"
