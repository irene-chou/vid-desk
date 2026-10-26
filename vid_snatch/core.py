"""vid-snatch: Download YouTube audio/video and optionally remove vocals."""

import argparse
import re
import shutil
import sys
import uuid
from pathlib import Path

DEFAULT_OUTPUT_DIR = Path("./output")
DEMUCS_MODEL = "htdemucs"
UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

YOUTUBE_PATTERNS = [
    r"(https?://)?(www\.)?youtube\.com/watch\?",
    r"(https?://)?(www\.)?youtube\.com/shorts/",
    r"(https?://)?youtu\.be/",
    r"(https?://)?music\.youtube\.com/watch\?",
]


def validate_url(url: str) -> str:
    for pattern in YOUTUBE_PATTERNS:
        if re.match(pattern, url):
            return url
    raise argparse.ArgumentTypeError(f"Not a valid YouTube URL: {url}")


def fetch_title(url: str) -> str:
    """Fetch the video title from YouTube without downloading."""
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("title", "video")
    except yt_dlp.utils.DownloadError as e:
        print(f"\nFailed to fetch video info: {e}")
        sys.exit(1)


def sanitize_filename(name: str) -> str:
    """Remove characters that are unsafe for filenames."""
    cleaned = UNSAFE_FILENAME_CHARS.sub("_", name).strip(". ")
    # Nothing meaningful left (empty or only replaced chars) -> generic name
    if not cleaned.strip("_"):
        return "video"
    return cleaned


def prompt_filename(default_title: str) -> str:
    """Ask the user for a filename, using the video title as default."""
    safe_default = sanitize_filename(default_title)
    print(f"\n檔名 (預設: {safe_default})")
    user_input = input("輸入自訂檔名，或按 Enter 使用預設: ").strip()
    if user_input:
        return sanitize_filename(user_input)
    return safe_default


def download_audio(
    url: str, output_dir: Path, filename: str, audio_format: str = "mp3",
) -> Path:
    import yt_dlp

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "paths": {"home": str(output_dir)},
        "outtmpl": {"default": f"{filename}.%(ext)s"},
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": "192",
            }
        ],
        "quiet": False,
        "no_warnings": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
            audio_path = output_dir / f"{filename}.{audio_format}"
            return audio_path
    except yt_dlp.utils.DownloadError as e:
        print(f"\nDownload failed: {e}")
        sys.exit(1)


def download_video(url: str, output_dir: Path, filename: str) -> Path:
    import yt_dlp

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "noplaylist": True,
        "paths": {"home": str(output_dir)},
        "outtmpl": {"default": f"{filename}.%(ext)s"},
        "merge_output_format": "mp4",
        "quiet": False,
        "no_warnings": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
            video_path = output_dir / f"{filename}.mp4"
            return video_path
    except yt_dlp.utils.DownloadError as e:
        print(f"\nDownload failed: {e}")
        sys.exit(1)


def remove_vocals(
    audio_path: Path,
    output_dir: Path,
) -> Path:
    import demucs.separate

    print(f"Separating vocals using Demucs ({DEMUCS_MODEL})...")
    print("(First run will download the model, ~80MB)")

    # Demucs can't handle special characters in filenames (full-width chars, etc.)
    # Rename to a safe temp name, process, then rename back
    original_stem = audio_path.stem
    safe_name = uuid.uuid4().hex[:8]
    safe_path = audio_path.parent / f"{safe_name}{audio_path.suffix}"
    audio_path.rename(safe_path)

    demucs_dir = output_dir / "_demucs_temp"
    args = [
        "--two-stems", "vocals",
        "-n", DEMUCS_MODEL,
        "-o", str(demucs_dir),
        "--mp3", "--mp3-bitrate", "192",
        str(safe_path),
    ]

    try:
        demucs.separate.main(args)
    except Exception as e:
        safe_path.rename(audio_path)
        print(f"\nVocal removal failed: {e}")
        print(f"The downloaded audio is still available at: {audio_path}")
        sys.exit(1)

    # Demucs outputs to: _demucs_temp/htdemucs/<safe_name>/no_vocals.mp3
    demucs_out = demucs_dir / DEMUCS_MODEL / safe_name
    no_vocals_src = demucs_out / "no_vocals.mp3"

    no_vocals_dst = output_dir / f"{original_stem}_no_vocals.mp3"
    shutil.move(str(no_vocals_src), str(no_vocals_dst))

    # Clean up
    shutil.rmtree(demucs_dir, ignore_errors=True)
    safe_path.unlink(missing_ok=True)

    return no_vocals_dst
