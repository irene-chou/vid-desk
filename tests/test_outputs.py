import pytest

from vid_snatch.outputs import KINDS, VERSIONS, OutputOptions


def test_from_mode_matches_cli_modes():
    assert OutputOptions.from_mode("mp3").to_dict() == {
        "audio": {"versions": ["original"], "format": "mp3", "bitrate": 192, "model": "htdemucs_ft"}, "video": None}
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
    {"audio": {"versions": ["original"], "format": "ogg"}}, {"audio": {"versions": ["original"], "bitrate": 256}},
    {"audio": {"versions": ["original"], "model": "mdx"}}, {"video": {"max_height": 480}},
])
def test_from_dict_rejects(bad):
    with pytest.raises(ValueError):
        OutputOptions.from_dict(bad)


def test_target_names_and_steps():
    o = OutputOptions.from_dict({"audio": {"versions": ["original", "instrumental", "vocals"], "format": "flac"}, "video": {"max_height": 1080}})
    assert o.target_names("s") == ["s.flac", "s_no_vocals.flac", "s_vocals.flac", "s.mp4", "s.wav"]
    assert o.steps() == ["取得資訊", "下載", "轉檔", "分離", "下載影片", "合併"]
    assert [x.kind for x in o.outputs()] == list(KINDS)
    only_original = OutputOptions.from_dict({"audio": {"versions": ["original"]}})
    assert only_original.target_names("s") == ["s.mp3"] and not only_original.needs_separation


def test_m4a_stems_use_mp3():
    o = OutputOptions.from_dict({"audio": {"versions": ["instrumental"], "format": "m4a"}})
    assert o.filename("s", "instrumental") == "s_no_vocals.mp3"
    assert o.target_names("s") == ["s_no_vocals.mp3", "s.wav"]


def test_constants():
    assert VERSIONS == ("original", "instrumental", "vocals")
    assert KINDS == ("original", "instrumental", "vocals", "video")
