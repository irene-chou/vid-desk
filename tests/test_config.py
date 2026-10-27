import shutil
import subprocess
import sys

import pytest

from vid_snatch import config
from vid_snatch.config import read_output_dir, read_settings, write_output_dir, write_settings


def test_roundtrip(tmp_path):
    assert read_output_dir(tmp_path) is None
    write_output_dir(tmp_path, "/Users/me/Music/vid-snatch")
    assert read_output_dir(tmp_path) == "/Users/me/Music/vid-snatch"
    assert (tmp_path / "config").read_text(encoding="utf-8") == "output_dir=/Users/me/Music/vid-snatch\n"


def test_reads_existing_bash_format(tmp_path):
    (tmp_path / "config").write_text("output_dir=~/Music/x\n", encoding="utf-8")
    assert read_output_dir(tmp_path) == "~/Music/x"


def test_settings_defaults_when_missing(tmp_path):
    assert read_settings(tmp_path) == {"audio_format": "mp3", "audio_bitrate": 192, "demucs_model": "htdemucs_ft", "video_max_height": None}
    assert read_settings(tmp_path) == config.DEFAULT_SETTINGS


def test_settings_roundtrip_keeps_output_dir_first(tmp_path):
    write_settings(tmp_path, {"audio_bitrate": 320, "video_max_height": 720})
    write_output_dir(tmp_path, "/new")
    write_settings(tmp_path, {"audio_format": "flac", "video_max_height": None, "ignored": "x"})
    text = (tmp_path / "config").read_text(encoding="utf-8")
    assert text.splitlines()[0] == "output_dir=/new"
    assert text == "output_dir=/new\naudio_format=flac\naudio_bitrate=320\nvideo_max_height=\n"
    assert read_output_dir(tmp_path) == "/new"
    assert read_settings(tmp_path) == {"audio_format": "flac", "audio_bitrate": 320, "demucs_model": "htdemucs_ft", "video_max_height": None}


def test_invalid_values_fall_back_to_defaults(tmp_path):
    (tmp_path / "config").write_text(
        "output_dir=/x\naudio_format=ogg\naudio_bitrate=abc\ndemucs_model=mdx\nvideo_max_height=480\n", encoding="utf-8")
    assert read_settings(tmp_path) == config.DEFAULT_SETTINGS
    assert read_output_dir(tmp_path) == "/x"


def test_value_may_contain_equals_sign(tmp_path):
    write_output_dir(tmp_path, "/a=b/c")
    assert read_output_dir(tmp_path) == "/a=b/c"


# ---- 與啟動腳本的相容性：bash / bat / ps1 只讀 `output_dir=` 那一行 ----

MULTI = {"output_dir": "/Users/me/Music/vid-snatch", "audio_format": "flac", "audio_bitrate": 320,
         "demucs_model": "htdemucs", "video_max_height": None}


def _write_multi(tmp_path):
    write_output_dir(tmp_path, MULTI["output_dir"])
    write_settings(tmp_path, {k: v for k, v in MULTI.items() if k != "output_dir"})
    return tmp_path / "config"


def test_launcher_style_parsers_read_output_dir(tmp_path):
    path = _write_multi(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    # vid-snatch.ps1 Load-Config：第一行以 output_dir= 開頭者，Substring(11)
    ps1 = next(line[11:].strip() for line in lines if line.startswith("output_dir="))
    assert ps1 == MULTI["output_dir"]
    # 檔案沒有 BOM，PowerShell 5.1 的 -Encoding UTF8 與 bash grep 才不會把第一行讀壞
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "\r" not in path.read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="需要 bash/grep/cut")
def test_mac_command_grep_reads_output_dir(tmp_path):
    path = _write_multi(tmp_path)
    # 與 vid-snatch-Mac.command load_config 相同的管線
    out = subprocess.run(["bash", "-c", f"grep '^output_dir=' \"{path}\" | cut -d'=' -f2-"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == MULTI["output_dir"]
