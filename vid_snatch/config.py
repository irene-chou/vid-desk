"""設定檔讀寫：`config` 檔內為單行 `output_dir=<path>`，與 bash/bat 啟動腳本共用。"""

from pathlib import Path

_KEY = "output_dir="


def read_output_dir(config_dir: Path) -> str | None:
    path = Path(config_dir) / "config"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(_KEY):
            return line[len(_KEY):].rstrip()
    return None


def write_output_dir(config_dir: Path, value: str) -> None:
    config_dir = Path(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(f"{_KEY}{value}\n", encoding="utf-8")
