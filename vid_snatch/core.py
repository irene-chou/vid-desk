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
from vid_snatch.models import DEMUCS_MODEL, DEMUCS_MODELS

# 百分比 0-100；None 表示不定進度
ProgressCallback = Callable[[float | None], None]

DEFAULT_OUTPUT_DIR = Path("./output")
# 位元率只對有損格式有意義；wav / flac 不帶 -b:a
LOSSY_FORMATS = ("mp3", "m4a")
# demucs 的 save_audio 只會寫 mp3 / wav / flac；其他格式的分離結果退回 mp3
STEM_FORMATS = ("mp3", "wav", "flac")
# 分離結果的檔名尾綴
STEM_SUFFIXES = {"instrumental": "_no_vocals", "vocals": "_vocals"}
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


def _bitrate_opts(audio_format: str, bitrate: int) -> list[str]:
    return ["-b:a", f"{bitrate}k"] if audio_format in LOSSY_FORMATS else []


def download_audio(
    url: str, output_dir: Path, filename: str, audio_format: str = "mp3",
    on_progress: ProgressCallback | None = None, *, overwrite: bool = False, bitrate: int = 192,
) -> Path:
    postprocessor = {"key": "FFmpegExtractAudio", "preferredcodec": audio_format}
    if audio_format in LOSSY_FORMATS:
        postprocessor["preferredquality"] = str(bitrate)
    _run_download(url, {
        **_overwrite_opts(overwrite),
        "format": "bestaudio/best",
        "paths": {"home": str(output_dir)},
        "outtmpl": {"default": f"{filename}.%(ext)s"},
        "postprocessors": [postprocessor],
    }, on_progress)
    return output_dir / f"{filename}.{audio_format}"


def convert_audio(src: Path, dst: Path, audio_format: str, bitrate: int = 192) -> Path:
    """用 yt-dlp 自己找到的 ffmpeg 把 src 轉成 audio_format（下載一次、多種輸出時用）。"""
    from yt_dlp.postprocessor.ffmpeg import ACODECS, FFmpegPostProcessor

    _, codec, more_opts = ACODECS[audio_format]
    codec_opts = ["-acodec", codec] if codec else []
    opts = ["-vn", *codec_opts, *more_opts, *_bitrate_opts(audio_format, bitrate)]
    try:
        FFmpegPostProcessor().run_ffmpeg(str(src), str(dst), opts)
    except Exception as e:
        raise translate(e) from e
    return dst


def _video_format(max_height: int | None) -> str:
    h = f"[height<={max_height}]" if max_height else ""
    return f"bestvideo{h}[ext=mp4]+bestaudio[ext=m4a]/best{h}[ext=mp4]/best{h}/best"


def download_video(
    url: str, output_dir: Path, filename: str,
    on_progress: ProgressCallback | None = None, *, overwrite: bool = False, max_height: int | None = None,
) -> Path:
    _run_download(url, {
        **_overwrite_opts(overwrite),
        "format": _video_format(max_height),
        "paths": {"home": str(output_dir)},
        "outtmpl": {"default": f"{filename}.%(ext)s"},
        "merge_output_format": "mp4",
    }, on_progress)
    return output_dir / f"{filename}.mp4"


def stem_format(audio_format: str) -> str:
    """分離結果的實際格式：demucs 只能寫 mp3 / wav / flac，m4a 退回 mp3。"""
    return audio_format if audio_format in STEM_FORMATS else "mp3"


def separate(
    audio_path: Path,
    output_dir: Path,
    on_progress: ProgressCallback | None = None,
    *,
    model: str = DEMUCS_MODEL,
    stems: tuple[str, ...] = ("instrumental",),
    audio_format: str = "mp3",
    bitrate: int = 192,
) -> dict[str, Path]:
    """跑一次 demucs，同時寫出要求的 stems（instrumental / vocals），回傳 {stem: 路徑}。

    來源檔保留不刪，呼叫端決定是否還要用它當原曲輸出。
    """
    from demucs.api import Separator, save_audio

    if model not in DEMUCS_MODELS:
        raise ValueError(f"未知的分離模型：{model}")
    if not stems or any(s not in STEM_SUFFIXES for s in stems):
        raise ValueError(f"未知的分離輸出：{stems}")
    fmt = stem_format(audio_format)

    def callback(d: dict) -> None:
        # htdemucs_ft 是 4 個模型的 bag：每個模型都從 0 跑到 audio_length，要合成整體進度
        if on_progress is None or not d.get("audio_length") or "segment_offset" not in d:
            return
        models = d.get("models") or 1
        done = d.get("model_idx_in_bag", 0) + d["segment_offset"] / d["audio_length"]
        on_progress(min(100.0, done / models * 100))

    # Demucs can't handle special characters in filenames (full-width chars, etc.)
    # Rename to a safe temp name, process, then rename back
    original_stem = audio_path.stem
    safe_path = audio_path.parent / f"{uuid.uuid4().hex[:8]}{audio_path.suffix}"
    audio_path.rename(safe_path)

    targets = {s: output_dir / f"{original_stem}{STEM_SUFFIXES[s]}.{fmt}" for s in stems}
    try:
        separator = Separator(model=model, callback=callback)
        _, sources = separator.separate_audio_file(safe_path)
        if "instrumental" in targets:
            no_vocals = sources["drums"] + sources["bass"] + sources["other"]
            save_audio(no_vocals, str(targets["instrumental"]), samplerate=separator.samplerate, bitrate=bitrate)
        if "vocals" in targets:
            save_audio(sources["vocals"], str(targets["vocals"]), samplerate=separator.samplerate, bitrate=bitrate)
    except Exception as e:
        raise translate(e) from e
    finally:
        safe_path.rename(audio_path)
    return targets


def remove_vocals(
    audio_path: Path,
    output_dir: Path,
    on_progress: ProgressCallback | None = None,
    *,
    model: str = DEMUCS_MODEL,
    audio_format: str = "mp3",
    bitrate: int = 192,
) -> Path:
    """只要伴奏時的簡化介面（windows/ci-smoke.ps1 等舊呼叫端用）：回傳 _no_vocals 檔路徑。"""
    return separate(audio_path, output_dir, on_progress, model=model, stems=("instrumental",),
                    audio_format=audio_format, bitrate=bitrate)["instrumental"]
