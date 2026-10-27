"""一個網址、多個輸出：輸出選項的驗證、步驤規劃與實際執行順序。

流程固定為：取得資訊 → 音訊只下載一次（需要分離時下載 wav，否則直接下載目標格式）→
轉檔（原曲）→ 分離（一次 demucs 同時得到伴奏與人聲）→ 影片。網頁佇列（jobs.py）與
CLI（cli.py）都走同一個 `execute`，只是回報進度的方式不同。
"""
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from . import core
from .config import AUDIO_FORMATS, BITRATES, MAX_HEIGHTS
from .models import DEMUCS_MODEL, DEMUCS_MODELS

VERSIONS = ("original", "instrumental", "vocals")
KINDS = (*VERSIONS, "video")
OUTPUT_STATES = ("queued", "running", "done", "failed")

# CLI 三個舊模式對應的輸出
MODES = {
    "mp3": {"audio": {"versions": ["original"]}},
    "mp4": {"video": {}},
    "no_vocals": {"audio": {"versions": ["instrumental"]}},
}


class Backend(Protocol):
    def fetch_title(self, url: str) -> str: ...
    def download_audio(self, url, output_dir, filename, audio_format="mp3", on_progress=None, *,
                       overwrite=False, bitrate=192) -> Path: ...
    def convert_audio(self, src, dst, audio_format, bitrate=192) -> Path: ...
    def download_video(self, url, output_dir, filename, on_progress=None, *,
                       overwrite=False, max_height=None) -> Path: ...
    def separate(self, audio_path, output_dir, on_progress=None, *,
                      model=DEMUCS_MODEL, stems=("instrumental",), audio_format="mp3", bitrate=192) -> dict[str, Path]: ...
    def update_ytdlp(self, timeout=30) -> bool: ...


@dataclass
class AudioOptions:
    versions: list[str]
    format: str = "mp3"
    bitrate: int = 192
    model: str = DEMUCS_MODEL


@dataclass
class VideoOptions:
    max_height: int | None = None


@dataclass
class OutputOptions:
    audio: AudioOptions | None = None
    video: VideoOptions | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "OutputOptions":
        """驗證 API / 設定給的 dict，錯誤以 ValueError（中文訊息）回報。"""
        data = data or {}
        audio = video = None
        if data.get("audio") is not None:
            a = data["audio"]
            versions = list(dict.fromkeys(a.get("versions") or []))  # 去重、保留順序
            if not versions:
                raise ValueError("音檔至少要勾一個版本")
            if any(v not in VERSIONS for v in versions):
                raise ValueError("未知的音檔版本")
            fmt = a.get("format", "mp3")
            if fmt not in AUDIO_FORMATS:
                raise ValueError("未知的音檔格式")
            bitrate = a.get("bitrate", 192)
            if bitrate not in BITRATES:
                raise ValueError("未知的位元率")
            model = a.get("model", DEMUCS_MODEL)
            if model not in DEMUCS_MODELS:
                raise ValueError("未知的分離模型")
            audio = AudioOptions([v for v in VERSIONS if v in versions], fmt, bitrate, model)
        if data.get("video") is not None:
            h = (data["video"] or {}).get("max_height")
            if h is not None and h not in MAX_HEIGHTS:
                raise ValueError("未知的畫質上限")
            video = VideoOptions(h)
        if audio is None and video is None:
            raise ValueError("至少要選一種輸出")
        return cls(audio, video)

    @classmethod
    def from_mode(cls, mode: str, **settings) -> "OutputOptions":
        """CLI 舊模式（mp3 / mp4 / no_vocals）轉成輸出選項；settings 可帶 format / bitrate / model / max_height。"""
        if mode not in MODES:
            raise ValueError(f"未知模式：{mode}")
        data = {k: dict(v) for k, v in MODES[mode].items()}
        if "audio" in data:
            data["audio"].update({k: settings[k] for k in ("format", "bitrate", "model") if k in settings})
        if "video" in data and "max_height" in settings:
            data["video"]["max_height"] = settings["max_height"]
        return cls.from_dict(data)

    def to_dict(self) -> dict:
        return {"audio": asdict(self.audio) if self.audio else None,
                "video": asdict(self.video) if self.video else None}

    # ---- 規劃 ----
    @property
    def needs_separation(self) -> bool:
        return bool(self.audio) and any(v != "original" for v in self.audio.versions)

    @property
    def stems(self) -> tuple[str, ...]:
        return tuple(v for v in (self.audio.versions if self.audio else []) if v != "original")

    def ext(self, kind: str) -> str:
        if kind == "video":
            return "mp4"
        return self.audio.format

    def filename(self, name: str, kind: str) -> str:
        suffix = core.STEM_SUFFIXES.get(kind, "")
        return f"{name}{suffix}.{self.ext(kind)}"

    def outputs(self) -> list["Output"]:
        kinds = list(self.audio.versions) if self.audio else []
        if self.video:
            kinds.append("video")
        return [Output(k, self.ext(k)) for k in kinds]

    def steps(self) -> list[str]:
        steps = ["取得資訊"]
        if self.audio:
            steps += ["下載", "轉檔"]
            if self.needs_separation:
                steps.append("分離")
        if self.video:
            steps += ["下載影片" if self.audio else "下載", "合併"]
        return steps

    def target_names(self, name: str) -> list[str]:
        """會寫入（並可能刪除）的檔名；需要分離時過程中會產生並刪除 <name>.wav。"""
        names = [self.filename(name, o.kind) for o in self.outputs()]
        if self.needs_separation:
            names.append(f"{name}.wav")
        return list(dict.fromkeys(names))


@dataclass
class Output:
    kind: str                       # original / instrumental / vocals / video
    ext: str                        # 實際寫出的副檔名
    state: str = "queued"           # queued / running / done / failed
    filename: str | None = None     # 檔名（含副檔名），確定檔名後填入
    result_path: str | None = None  # 完成後的完整路徑
    size_bytes: int | None = None   # 完成後的檔案大小

    def to_dict(self) -> dict:
        return asdict(self)


def unique_base(output_dir: Path, name: str, options: OutputOptions) -> str:
    """避免覆蓋既有檔案：任一會寫入的檔已存在時改用 "name (1)"、"name (2)"…"""
    candidate, n = name, 0
    while any((Path(output_dir) / t).exists() for t in options.target_names(candidate)):
        n += 1
        candidate = f"{name} ({n})"
    return candidate


@dataclass
class Hooks:
    """execute 的進度回呼；都可省略。"""
    on_step: Callable[[int], None] = field(default=lambda i: None)              # 進到第 i 步（1-based）
    on_progress: Callable[[float | None], None] = field(default=lambda p: None)  # 目前步驟百分比
    on_output: Callable[[str, str, Path | None], None] = field(default=lambda k, s, p: None)  # 輸出狀態變化


def execute(options: OutputOptions, url: str, output_dir: Path, name: str, backend: Backend = core,
            *, overwrite: bool = False, hooks: Hooks | None = None) -> dict[str, Path]:
    """依選項產出所有檔案，回傳 {kind: 路徑}。「取得資訊」（第 1 步）由呼叫端先做完。"""
    hooks = hooks or Hooks()
    output_dir = Path(output_dir)
    results: dict[str, Path] = {}
    step = [1]

    def next_step() -> None:
        step[0] += 1
        hooks.on_step(step[0])

    class DownloadHook:
        """yt-dlp 的 finished 可能每個檔案各來一次（影片 + 音訊），只推進一次到後處理步驟。"""
        advanced = False

        def __call__(self, p: float | None) -> None:
            if p is not None:
                hooks.on_progress(p)
            elif not self.advanced:
                self.advanced = True
                next_step()

        def ensure_advanced(self) -> None:
            self(None)

    def done(kind: str, path: Path) -> None:
        results[kind] = path
        hooks.on_output(kind, "done", path)

    audio = options.audio
    if audio:
        download_format = "wav" if options.needs_separation else audio.format
        next_step()  # 下載
        if "original" in audio.versions:
            hooks.on_output("original", "running", None)
        hook = DownloadHook()
        src = backend.download_audio(url, output_dir, name, download_format, hook,
                                     overwrite=overwrite, bitrate=audio.bitrate)
        hook.ensure_advanced()  # 轉檔
        keep_src = False
        try:
            if "original" in audio.versions:
                if download_format == audio.format:
                    keep_src = True
                    done("original", src)
                else:
                    dst = output_dir / options.filename(name, "original")
                    done("original", backend.convert_audio(src, dst, audio.format, audio.bitrate))
            if options.needs_separation:
                next_step()  # 分離
                for stem in options.stems:
                    hooks.on_output(stem, "running", None)
                stems = backend.separate(src, output_dir, hooks.on_progress, model=audio.model,
                                              stems=options.stems, audio_format=audio.format, bitrate=audio.bitrate)
                for stem in options.stems:
                    done(stem, stems[stem])
        finally:
            if not keep_src:
                Path(src).unlink(missing_ok=True)

    if options.video:
        next_step()  # 下載影片
        hooks.on_output("video", "running", None)
        hook = DownloadHook()
        path = backend.download_video(url, output_dir, name, hook, overwrite=overwrite,
                                      max_height=options.video.max_height)
        hook.ensure_advanced()  # 合併
        done("video", path)

    return results
