import sys
import types
from pathlib import Path

import pytest

from vid_snatch import core
from vid_snatch.errors import VidSnatchError


class FakeYDL:
    last_opts = None

    def __init__(self, opts):
        FakeYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def extract_info(self, url, download=False):
        if "fail" in url:
            raise self.DownloadError("ERROR: Private video")
        for hook in self.last_opts.get("progress_hooks", []):
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 200})
        return {"title": "My Song"}

    class DownloadError(Exception):
        pass


@pytest.fixture
def fake_ytdlp(monkeypatch):
    mod = types.ModuleType("yt_dlp")
    mod.YoutubeDL = FakeYDL
    utils = types.ModuleType("yt_dlp.utils")
    utils.DownloadError = FakeYDL.DownloadError
    mod.utils = utils
    monkeypatch.setitem(sys.modules, "yt_dlp", mod)
    monkeypatch.setitem(sys.modules, "yt_dlp.utils", utils)


def test_fetch_title(fake_ytdlp):
    assert core.fetch_title("https://youtu.be/x") == "My Song"


def test_fetch_title_raises_translated(fake_ytdlp):
    with pytest.raises(VidSnatchError) as ei:
        core.fetch_title("https://youtu.be/fail")
    assert ei.value.kind == "private"


def test_download_audio_reports_progress(fake_ytdlp, tmp_path):
    seen = []
    out = core.download_audio("https://youtu.be/x", tmp_path, "song", on_progress=seen.append)
    assert out == tmp_path / "song.mp3"
    assert seen == [25.0]


def test_download_video_raises_translated(fake_ytdlp, tmp_path):
    with pytest.raises(VidSnatchError) as ei:
        core.download_video("https://youtu.be/fail", tmp_path, "v")
    assert ei.value.kind == "private"


def test_postprocessing_reports_indeterminate(fake_ytdlp, tmp_path, monkeypatch):
    def extract(self, url, download=False):
        for hook in self.last_opts["progress_hooks"]:
            hook({"status": "finished"})
        return {}

    monkeypatch.setattr(FakeYDL, "extract_info", extract)
    seen = []
    core.download_audio("https://youtu.be/x", tmp_path, "song", on_progress=seen.append)
    assert seen == [None]


def test_unique_path(tmp_path):
    (tmp_path / "a.mp3").touch()
    (tmp_path / "a (1).mp3").touch()
    assert core.unique_path(tmp_path / "a.mp3") == tmp_path / "a (2).mp3"
    assert core.unique_path(tmp_path / "b.mp3") == tmp_path / "b.mp3"


def test_reload_ytdlp_drops_modules(fake_ytdlp):
    core.reload_ytdlp()
    assert "yt_dlp" not in sys.modules and "yt_dlp.utils" not in sys.modules


def test_update_ytdlp_success_reloads(monkeypatch):
    calls = []
    monkeypatch.setattr(core.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)) or types.SimpleNamespace(returncode=0))
    monkeypatch.setattr(core, "reload_ytdlp", lambda: calls.append("reload"))
    assert core.update_ytdlp(timeout=5) is True
    assert calls[0][0][-4:] == ["install", "-q", "-U", "yt-dlp"]
    assert calls[0][1]["timeout"] == 5
    assert calls[-1] == "reload"


def test_update_ytdlp_failure(monkeypatch):
    monkeypatch.setattr(core.subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(returncode=1))
    monkeypatch.setattr(core, "reload_ytdlp", lambda: pytest.fail("should not reload"))
    assert core.update_ytdlp() is False
