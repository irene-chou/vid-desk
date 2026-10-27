"""設定檔讀寫。

`config` 檔每行一個 `key=value`，與 bash/bat/ps1 啟動腳本共用同一個檔：啟動腳本只讀
`output_dir=` 那一行（其他行會被略過），所以這裡寫檔時每個 key 各佔一行、`output_dir`
永遠寫在第一行，而且不寫 BOM、不加註解。
"""

from pathlib import Path

from .models import DEMUCS_MODEL, DEMUCS_MODELS

_KEY = "output_dir="

AUDIO_FORMATS = ("mp3", "m4a", "wav", "flac")
BITRATES = (128, 192, 320)
MAX_HEIGHTS = (1080, 720)

# 細項設定的 key 與預設值；video_max_height=None 表示不限（最佳畫質）
DEFAULT_SETTINGS: dict[str, object] = {
    "audio_format": "mp3",
    "audio_bitrate": 192,
    "demucs_model": DEMUCS_MODEL,
    "video_max_height": None,
}
_ORDER = ("output_dir", *DEFAULT_SETTINGS)


def _config_path(config_dir: Path) -> Path:
    return Path(config_dir) / "config"


def read_raw(config_dir: Path) -> dict[str, str]:
    """讀出所有 `key=value`（值為原始字串）；沒有檔案時回傳空 dict。"""
    path = _config_path(config_dir)
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and key.strip() not in values:
            values[key.strip()] = value.rstrip()
    return values


def write_raw(config_dir: Path, values: dict[str, str]) -> None:
    """把 values 合併進既有設定後整檔重寫；output_dir 永遠在第一行。"""
    config_dir = Path(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    merged = {**read_raw(config_dir), **values}
    keys = [k for k in _ORDER if k in merged] + [k for k in merged if k not in _ORDER]
    lines = "".join(f"{k}={merged[k]}\n" for k in keys)
    _config_path(config_dir).write_text(lines, encoding="utf-8")


def read_output_dir(config_dir: Path) -> str | None:
    return read_raw(config_dir).get("output_dir")


def write_output_dir(config_dir: Path, value: str) -> None:
    write_raw(config_dir, {"output_dir": value})


def _parse(key: str, raw: str) -> object:
    """把設定檔裡的字串轉成 API 用的型別；不合法的值一律回預設。"""
    default = DEFAULT_SETTINGS[key]
    raw = raw.strip()
    if key == "audio_format":
        return raw if raw in AUDIO_FORMATS else default
    if key == "audio_bitrate":
        return int(raw) if raw.isdigit() and int(raw) in BITRATES else default
    if key == "demucs_model":
        return raw if raw in DEMUCS_MODELS else default
    if key == "video_max_height":
        return int(raw) if raw.isdigit() and int(raw) in MAX_HEIGHTS else None
    return default


def read_settings(config_dir: Path) -> dict[str, object]:
    """細項設定（不含 output_dir），缺少或不合法的 key 用預設值補齊。"""
    raw = read_raw(config_dir)
    return {k: (_parse(k, raw[k]) if k in raw else v) for k, v in DEFAULT_SETTINGS.items()}


def write_settings(config_dir: Path, settings: dict[str, object]) -> None:
    """只寫入給出的 key；值為 None 的 key（例如不限畫質）寫成空字串。"""
    values = {k: ("" if v is None else str(v)) for k, v in settings.items() if k in DEFAULT_SETTINGS}
    if values:
        write_raw(config_dir, values)
