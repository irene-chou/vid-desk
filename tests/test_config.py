from vid_snatch.config import read_output_dir, write_output_dir


def test_roundtrip(tmp_path):
    assert read_output_dir(tmp_path) is None
    write_output_dir(tmp_path, "/Users/me/Music/vid-snatch")
    assert read_output_dir(tmp_path) == "/Users/me/Music/vid-snatch"
    assert (tmp_path / "config").read_text(encoding="utf-8") == "output_dir=/Users/me/Music/vid-snatch\n"


def test_reads_existing_bash_format(tmp_path):
    (tmp_path / "config").write_text("output_dir=~/Music/x\n", encoding="utf-8")
    assert read_output_dir(tmp_path) == "~/Music/x"
