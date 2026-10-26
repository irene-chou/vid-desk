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
    prompt_filename,
    remove_vocals,
    validate_url,
)


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
    parser.add_argument("url", type=validate_url, help="YouTube video URL")
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


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not check_dependencies():
        sys.exit(1)

    args.output.mkdir(parents=True, exist_ok=True)

    # Fetch video title and let user choose filename
    print(f"正在取得影片資訊...")
    title = fetch_title(args.url)
    filename = prompt_filename(title)

    if args.video:
        print(f"\nDownloading video from: {args.url}")
        video_path = download_video(args.url, args.output, filename)
        print(f"Done! Video saved: {video_path}")
    elif args.no_vocals:
        print(f"\nDownloading audio from: {args.url}")
        audio_path = download_audio(
            args.url, args.output, filename, audio_format="wav",
        )
        print(f"Downloaded: {audio_path}")
        result_path = remove_vocals(audio_path, args.output)
        print(f"Instrumental saved: {result_path}")
    else:
        print(f"\nDownloading audio from: {args.url}")
        audio_path = download_audio(args.url, args.output, filename)
        print(f"Done! Audio saved: {audio_path}")


if __name__ == "__main__":
    main()
