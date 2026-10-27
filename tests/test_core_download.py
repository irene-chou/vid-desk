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


@pytest.mark.parametrize("func", ["download_audio", "download_video"])
def test_overwrites_only_when_requested(fake_ytdlp, tmp_path, func):
    getattr(core, func)("https://youtu.be/x", tmp_path, "song")
    assert "overwrites" not in FakeYDL.last_opts
    getattr(core, func)("https://youtu.be/x", tmp_path, "song", overwrite=True)
    assert FakeYDL.last_opts["overwrites"] is True


def test_download_audio_format_and_bitrate(fake_ytdlp, tmp_path):
    core.download_audio("https://youtu.be/x", tmp_path, "song")
    assert FakeYDL.last_opts["postprocessors"] == [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    out = core.download_audio("https://youtu.be/x", tmp_path, "song", "m4a", bitrate=320)
    assert out == tmp_path / "song.m4a"
    assert FakeYDL.last_opts["postprocessors"][0]["preferredquality"] == "320"
    # 無損格式不帶位元率
    core.download_audio("https://youtu.be/x", tmp_path, "song", "flac", bitrate=320)
    assert "preferredquality" not in FakeYDL.last_opts["postprocessors"][0]
    core.download_audio("https://youtu.be/x", tmp_path, "song", "wav")
    assert "preferredquality" not in FakeYDL.last_opts["postprocessors"][0]


def test_download_video_max_height(fake_ytdlp, tmp_path):
    core.download_video("https://youtu.be/x", tmp_path, "v")
    assert FakeYDL.last_opts["format"] == "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best/best"
    core.download_video("https://youtu.be/x", tmp_path, "v", max_height=720)
    assert FakeYDL.last_opts["format"] == "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]/best"


def test_convert_audio_builds_ffmpeg_opts(monkeypatch, tmp_path):
    calls = []

    class FakePP:
        def __init__(self, downloader=None): pass
        def run_ffmpeg(self, path, out_path, opts): calls.append((path, out_path, opts))

    ffmpeg = types.ModuleType("yt_dlp.postprocessor.ffmpeg")
    ffmpeg.FFmpegPostProcessor = FakePP
    ffmpeg.ACODECS = {"mp3": ("mp3", "libmp3lame", ()), "m4a": ("m4a", "aac", ("-bsf:a", "aac_adtstoasc")),
                      "wav": ("wav", None, ("-f", "wav")), "flac": ("flac", "flac", ())}
    monkeypatch.setitem(sys.modules, "yt_dlp.postprocessor.ffmpeg", ffmpeg)
    src = tmp_path / "s.wav"
    assert core.convert_audio(src, tmp_path / "s.mp3", "mp3", 320) == tmp_path / "s.mp3"
    core.convert_audio(src, tmp_path / "s.flac", "flac", 320)
    core.convert_audio(src, tmp_path / "s.m4a", "m4a")
    assert [c[2] for c in calls] == [
        ["-vn", "-acodec", "libmp3lame", "-b:a", "320k"],
        ["-vn", "-acodec", "flac"],
        ["-vn", "-acodec", "aac", "-bsf:a", "aac_adtstoasc", "-b:a", "192k"],
    ]
    assert calls[0][:2] == (str(src), str(tmp_path / "s.mp3"))


def test_stem_format():
    assert core.stem_format("mp3") == "mp3" and core.stem_format("flac") == "flac"
    assert core.stem_format("wav") == "wav" and core.stem_format("m4a") == "mp3"


class FakeSeparator:
    samplerate = 44100
    created = []

    def __init__(self, model, callback=None):
        FakeSeparator.created.append(model)
        self.callback = callback

    def separate_audio_file(self, path):
        assert path.exists()
        for i in range(4):
            self.callback({"models": 4, "model_idx_in_bag": i, "segment_offset": 5, "audio_length": 10})
        self.callback({"state": "end"})
        return None, {"drums": 1, "bass": 2, "other": 4, "vocals": 8}


@pytest.fixture
def fake_demucs(monkeypatch):
    FakeSeparator.created = []
    saved = []

    def save_audio(wav, path, samplerate, bitrate=320):
        saved.append((wav, path, bitrate))
        Path(path).write_bytes(b"a")

    api = types.ModuleType("demucs.api")
    api.Separator = FakeSeparator
    api.save_audio = save_audio
    demucs = types.ModuleType("demucs")
    demucs.api = api
    monkeypatch.setitem(sys.modules, "demucs", demucs)
    monkeypatch.setitem(sys.modules, "demucs.api", api)
    return saved


def test_separate_writes_both_stems_in_one_pass(fake_demucs, tmp_path):
    src = tmp_path / "測試 歌曲.wav"
    src.write_bytes(b"wav")
    seen = []
    out = core.separate(src, tmp_path, seen.append, model="htdemucs", stems=("instrumental", "vocals"),
                             audio_format="flac", bitrate=320)
    assert FakeSeparator.created == ["htdemucs"]
    assert out == {"instrumental": tmp_path / "測試 歌曲_no_vocals.flac", "vocals": tmp_path / "測試 歌曲_vocals.flac"}
    assert [(w, b) for w, _, b in fake_demucs] == [(7, 320), (8, 320)]
    assert seen == [12.5, 37.5, 62.5, 87.5]  # 4 個模型的 bag 合成整體進度
    assert src.exists() and src.read_bytes() == b"wav"  # 來源保留給呼叫端處理
    assert not any(p.name.endswith(".wav") and p != src for p in tmp_path.iterdir())


def test_separate_defaults_and_m4a_fallback(fake_demucs, tmp_path):
    src = tmp_path / "s.wav"; src.write_bytes(b"wav")
    out = core.separate(src, tmp_path)
    assert FakeSeparator.created == ["htdemucs_ft"] and list(out) == ["instrumental"]
    assert out["instrumental"] == tmp_path / "s_no_vocals.mp3" and fake_demucs[0][2] == 192
    out = core.separate(src, tmp_path, stems=("vocals",), audio_format="m4a")
    assert out["vocals"] == tmp_path / "s_vocals.mp3"


def test_separate_restores_source_on_failure(fake_demucs, tmp_path, monkeypatch):
    monkeypatch.setattr(FakeSeparator, "separate_audio_file", lambda self, p: (_ for _ in ()).throw(RuntimeError("timed out")))
    src = tmp_path / "s.wav"; src.write_bytes(b"wav")
    with pytest.raises(VidSnatchError) as ei:
        core.separate(src, tmp_path)
    assert ei.value.kind == "network" and src.exists()


def test_separate_rejects_unknown_model_or_stem(fake_demucs, tmp_path):
    src = tmp_path / "s.wav"; src.write_bytes(b"wav")
    with pytest.raises(ValueError):
        core.separate(src, tmp_path, model="mdx")
    with pytest.raises(ValueError):
        core.separate(src, tmp_path, stems=("drums",))
    assert src.exists()


def test_remove_vocals_is_instrumental_only_shortcut(fake_demucs, tmp_path):
    # windows/ci-smoke.ps1 以 remove_vocals(src, work) 呼叫並對回傳值用 .exists()
    src = tmp_path / "s.wav"; src.write_bytes(b"wav")
    out = core.remove_vocals(src, tmp_path)
    assert isinstance(out, Path) and out == tmp_path / "s_no_vocals.mp3" and out.exists()
    assert FakeSeparator.created == ["htdemucs_ft"] and src.exists()
