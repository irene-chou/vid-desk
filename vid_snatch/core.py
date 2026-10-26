"""vid-snatch: Download YouTube audio/video and optionally remove vocals."""

import argparse
import re
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from vid_snatch.errors import VidSnatchError, translate

# 百分比 0-100；None 表示不定進度
ProgressCallback = Callable[[float | None], None]

DEFAULT_OUTPUT_DIR = Path("./output")
DEMUCS_MODEL = "htdemucs"
UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

YOUTUBE_PATTERNS = [
    r"(https?://)?(www\.)?youtube\.com/watch\?",
    r"(https?://)?(www\.)?youtube\.com/shorts/",
    r"(https?://)?(www\.)?youtube\.com/live/",
    r"(https?://)?youtu\.be/",
    r"(https?://)?music\.youtube\.com/watch\?",
]


STRIPPED_QUERY_PARAMS = {"list", "index", "t", "si", "pp", "start_radio", "feature"}


def clean_url(raw: str) -> str | None:
    """Normalize a pasted YouTube video URL, or return None if it isn't one."""
    url = raw.strip()
    if not url:
        return None
    if not re.match(r"https?://", url):
        url = "https://" + url
    if not any(re.match(pattern, url) for pattern in YOUTUBE_PATTERNS):
        return None
    parts = urlsplit(url)
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if k not in STRIPPED_QUERY_PARAMS]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def validate_url(url: str) -> str:
    cleaned = clean_url(url)
    if cleaned is None:
        raise argparse.ArgumentTypeError(f"Not a valid YouTube URL: {url}")
    return cleaned


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
    except Exception as e:
        raise translate(e) from e


def sanitize_filename(name: str) -> str:
    """Remove characters that are unsafe for filenames."""
    cleaned = UNSAFE_FILENAME_CHARS.sub("_", name).strip(". ")
    # Nothing meaningful left (empty or only replaced chars) -> generic name
    if not cleaned.strip("_"):
        return "video"
    return cleaned


def unique_path(path: Path) -> Path:
    """Return path, or 'name (N).ext' if it already exists."""
    if not path.exists():
        return path
    n = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def reload_ytdlp() -> None:
    """Forget loaded yt_dlp modules so the next import picks up a new version."""
    for name in [m for m in sys.modules if m == "yt_dlp" or m.startswith("yt_dlp.")]:
        del sys.modules[name]


def update_ytdlp(timeout: float = 30) -> bool:
    """Upgrade yt-dlp via pip. Returns True on success."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-U", "yt-dlp"],
            timeout=timeout,
            capture_output=True,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    if result.returncode != 0:
        return False
    reload_ytdlp()
    return True


def _make_hook(on_progress: ProgressCallback | None):
    def hook(d: dict) -> None:
        if on_progress is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                on_progress(d.get("downloaded_bytes", 0) / total * 100)
        elif d.get("status") == "finished":
            on_progress(None)

    return hook


def _run_download(url: str, ydl_opts: dict, on_progress: ProgressCallback | None) -> None:
    import yt_dlp

    ydl_opts = {
        **ydl_opts,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_make_hook(on_progress)],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
    except Exception as e:
        raise translate(e) from e


def _overwrite_opts(overwrite: bool) -> dict:
    return {"overwrites": True} if overwrite else {}


def download_audio(
    url: str, output_dir: Path, filename: str, audio_format: str = "mp3",
    on_progress: ProgressCallback | None = None, *, overwrite: bool = False,
) -> Path:
    _run_download(url, {
        **_overwrite_opts(overwrite),
        "format": "bestaudio/best",
        "paths": {"home": str(output_dir)},
        "outtmpl": {"default": f"{filename}.%(ext)s"},
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": "192",
            }
        ],
    }, on_progress)
    return output_dir / f"{filename}.{audio_format}"


def download_video(
    url: str, output_dir: Path, filename: str,
    on_progress: ProgressCallback | None = None, *, overwrite: bool = False,
) -> Path:
    _run_download(url, {
        **_overwrite_opts(overwrite),
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "paths": {"home": str(output_dir)},
        "outtmpl": {"default": f"{filename}.%(ext)s"},
        "merge_output_format": "mp4",
    }, on_progress)
    return output_dir / f"{filename}.mp4"


def remove_vocals(
    audio_path: Path,
    output_dir: Path,
    on_progress: ProgressCallback | None = None,
) -> Path:
    from demucs.api import Separator, save_audio

    def callback(d: dict) -> None:
        if on_progress is None:
            return
        if "segment_offset" in d and d.get("audio_length"):
            on_progress(d["segment_offset"] / d["audio_length"] * 100)
        else:
            on_progress(None)

    # Demucs can't handle special characters in filenames (full-width chars, etc.)
    # Rename to a safe temp name, process, then rename back
    original_stem = audio_path.stem
    safe_path = audio_path.parent / f"{uuid.uuid4().hex[:8]}{audio_path.suffix}"
    audio_path.rename(safe_path)

    no_vocals_dst = output_dir / f"{original_stem}_no_vocals.mp3"
    try:
        separator = Separator(model=DEMUCS_MODEL, callback=callback)
        _, stems = separator.separate_audio_file(safe_path)
        no_vocals = stems["drums"] + stems["bass"] + stems["other"]
        save_audio(no_vocals, str(no_vocals_dst), samplerate=separator.samplerate, bitrate=192)
    except Exception as e:
        safe_path.rename(audio_path)
        raise translate(e) from e

    safe_path.unlink(missing_ok=True)
    return no_vocals_dst
