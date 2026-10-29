import pytest

from vid_desk.outputs import KINDS, VERSIONS, OutputOptions


def test_from_mode_matches_cli_modes():
    assert OutputOptions.from_mode("mp3").to_dict() == {
        "audio": {"versions": ["original"], "format": "mp3", "model": "htdemucs_ft"}, "video": None}
    assert OutputOptions.from_mode("mp4").to_dict() == {"audio": None, "video": {"max_height": None}}
    assert OutputOptions.from_mode("no_vocals").audio.versions == ["instrumental"]
    assert OutputOptions.from_mode("no_vocals", model="htdemucs").audio.model == "htdemucs"
    with pytest.raises(ValueError):
        OutputOptions.from_mode("ogg")


def test_versions_are_deduplicated_and_ordered():
    o = OutputOptions.from_dict({"audio": {"versions": ["vocals", "original", "vocals"]}})
    assert o.audio.versions == ["original", "vocals"]
    assert o.stems == ("vocals",) and o.needs_separation


@pytest.mark.parametrize("bad", [
    {}, {"audio": None, "video": None}, {"audio": {"versions": []}}, {"audio": {"versions": ["karaoke"]}},
    {"audio": {"versions": ["original"], "format": "ogg"}},
    {"audio": {"versions": ["original"], "model": "mdx"}}, {"video": {"max_height": 480}},
])
def test_from_dict_rejects(bad):
    with pytest.raises(ValueError):
        OutputOptions.from_dict(bad)


def test_from_dict_ignores_legacy_bitrate():
    # #18：位元率固定 192k，舊前端送的 bitrate 不驗證也不留在 options 裡
    o = OutputOptions.from_dict({"audio": {"versions": ["original"], "bitrate": 256}})
    assert o.to_dict()["audio"] == {"versions": ["original"], "format": "mp3", "model": "htdemucs_ft"}


def test_target_names_and_steps():
    o = OutputOptions.from_dict({"audio": {"versions": ["original", "instrumental", "vocals"], "format": "flac"}, "video": {"max_height": 1080}})
    assert o.target_names("s") == ["s.flac", "s_no_vocals.flac", "s_vocals.flac", "s.mp4", "s.wav"]
    assert o.steps() == ["取得資訊", "下載", "轉檔", "分離", "下載影片", "合併"]
    assert [x.kind for x in o.outputs()] == list(KINDS)
    only_original = OutputOptions.from_dict({"audio": {"versions": ["original"]}})
    assert only_original.target_names("s") == ["s.mp3"] and not only_original.needs_separation


def test_m4a_stems_keep_m4a():
    o = OutputOptions.from_dict({"audio": {"versions": ["original", "instrumental"], "format": "m4a"}})
    assert o.filename("s", "instrumental") == "s_no_vocals.m4a"
    assert [x.ext for x in o.outputs()] == ["m4a", "m4a"]
    assert o.target_names("s") == ["s.m4a", "s_no_vocals.m4a", "s.wav"]


def test_constants():
    assert VERSIONS == ("original", "instrumental", "vocals")
    assert KINDS == ("original", "instrumental", "vocals", "video")


def test_core_and_fake_backend_provide_every_pipeline_call():
    # 流程呼叫的名稱若改了，真實的 core 與測試用的 FakeBackend 都要跟上
    from tests.test_jobs import FakeBackend
    from vid_desk import core

    for name in ("fetch_title", "download_audio", "convert_audio", "download_video", "separate", "update_ytdlp"):
        assert callable(getattr(core, name)), name
        assert callable(getattr(FakeBackend(), name)), name
