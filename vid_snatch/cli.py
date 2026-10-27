"""vid-snatch command line interface."""

import argparse
import shutil
import sys
from pathlib import Path

from vid_snatch import core, outputs
from vid_snatch.core import DEFAULT_OUTPUT_DIR, sanitize_filename, validate_url
from vid_snatch.errors import VidSnatchError
from vid_snatch.outputs import Hooks, OutputOptions


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


def mode_of(args) -> str:
    return "mp4" if args.video else "no_vocals" if args.no_vocals else "mp3"


RESULT_LABELS = {"original": "Audio", "instrumental": "Instrumental", "vocals": "Vocals", "video": "Video"}


def run(args) -> None:
    args.output.mkdir(parents=True, exist_ok=True)
    options = OutputOptions.from_mode(mode_of(args))
    steps = options.steps()

    print("正在取得影片資訊...")
    title = core.fetch_title(args.url)
    # 避免覆蓋既有檔案：已存在時改用 "name (1)"
    filename = outputs.unique_base(args.output, prompt_filename(title), options)

    def on_step(i: int) -> None:
        name = steps[i - 1]
        print(f"\n[{i}/{len(steps)}] {name}", end="", flush=True)
        if name == "分離":
            print(" (first run downloads the model, ~320MB)", end="", flush=True)
        print()

    print(f"\nDownloading from: {args.url}")
    results = outputs.execute(options, args.url, args.output, filename, core,
                              hooks=Hooks(on_step=on_step, on_progress=print_progress))
    print()
    for kind, path in results.items():
        print(f"Done! {RESULT_LABELS[kind]} saved: {path}")


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
