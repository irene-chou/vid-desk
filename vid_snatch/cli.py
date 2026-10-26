"""vid-snatch command line interface."""

import argparse
import shutil
import sys
from pathlib import Path

from vid_snatch.core import (
    DEFAULT_OUTPUT_DIR,
    download_audio,
    download_video,
    fetch_title,
    remove_vocals,
    sanitize_filename,
    unique_path,
    validate_url,
)
from vid_snatch.errors import VidSnatchError


def check_dependencies() -> bool:
    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg not found.")
        print("Install via: brew install ffmpeg")
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vid-snatch",
        description="Download YouTube audio/video, optionally remove vocals.",
    )
    parser.add_argument("url", nargs="?", type=validate_url, help="YouTube video URL")
    parser.add_argument("--web", action="store_true", help="Start the web UI server")
    parser.add_argument("--port", type=int, default=8080, help="Web UI port (default: 8080)")
    parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--video", action="store_true",
        help="Download video (MP4) instead of audio",
    )
    mode.add_argument(
        "--no-vocals", action="store_true",
        help="Remove vocals and keep instrumental only (Demucs)",
    )

    return parser


def prompt_filename(default_title: str) -> str:
    """Ask the user for a filename, using the video title as default."""
    safe_default = sanitize_filename(default_title)
    print(f"\n檔名 (預設: {safe_default})")
    user_input = input("輸入自訂檔名，或按 Enter 使用預設: ").strip()
    if user_input:
        return sanitize_filename(user_input)
    return safe_default


def print_progress(percent: float | None) -> None:
    print("\r...   " if percent is None else f"\r{percent:.0f}%   ", end="", flush=True)


def run(args) -> None:
    args.output.mkdir(parents=True, exist_ok=True)

    print("正在取得影片資訊...")
    title = fetch_title(args.url)
    filename = prompt_filename(title)
    ext = "mp4" if args.video else "mp3"
    # 避免覆蓋既有檔案：已存在時改用 "name (1)"
    filename = unique_path(args.output / f"{filename}.{ext}").stem

    if args.video:
        print(f"\nDownloading video from: {args.url}")
        video_path = download_video(args.url, args.output, filename, on_progress=print_progress)
        print(f"\nDone! Video saved: {video_path}")
    elif args.no_vocals:
        print(f"\nDownloading audio from: {args.url}")
        audio_path = download_audio(
            args.url, args.output, filename, audio_format="wav", on_progress=print_progress,
        )
        print(f"\nDownloaded: {audio_path}")
        print("Separating vocals (first run downloads the model, ~80MB)...")
        result_path = remove_vocals(audio_path, args.output, on_progress=print_progress)
        print(f"\nInstrumental saved: {result_path}")
    else:
        print(f"\nDownloading audio from: {args.url}")
        audio_path = download_audio(args.url, args.output, filename, on_progress=print_progress)
        print(f"\nDone! Audio saved: {audio_path}")


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.web:
        from vid_snatch.webserver import run_web

        return run_web(args.port)
    if args.url is None:
        parser.error("需要 YouTube 網址")

    if not check_dependencies():
        sys.exit(1)

    try:
        run(args)
    except VidSnatchError as e:
        print(f"\n{e.message}")
        if e.detail:
            print(e.detail)
        sys.exit(1)


if __name__ == "__main__":
    main()
