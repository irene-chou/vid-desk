import sys

import pytest

from vid_snatch.cli import build_parser, main


def test_web_flag_makes_url_optional():
    args = build_parser().parse_args(["--web"])
    assert args.web is True and args.url is None and args.port == 8080


def test_cli_still_requires_url_without_web(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["vid-snatch"])
    with pytest.raises(SystemExit):
        main()


def test_video_and_no_vocals_are_exclusive():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["https://youtu.be/a", "--video", "--no-vocals"])


@pytest.mark.parametrize("flags,mode,expected", [
    ([], "mp3", ["song.mp3"]),
    (["--video"], "mp4", ["song.mp4"]),
    (["--no-vocals"], "no_vocals", ["song_no_vocals.mp3"]),
])
def test_run_three_modes_use_shared_pipeline(monkeypatch, tmp_path, capsys, flags, mode, expected):
    from tests.test_jobs import FakeBackend
    from vid_snatch import cli

    backend = FakeBackend()
    for name in ("fetch_title", "download_audio", "convert_audio", "download_video", "separate"):
        monkeypatch.setattr(cli.core, name, getattr(backend, name))
    monkeypatch.setattr("builtins.input", lambda prompt="": "song")
    args = build_parser().parse_args(["https://youtu.be/a", "-o", str(tmp_path), *flags])
    assert cli.mode_of(args) == mode
    cli.run(args)
    assert sorted(p.name for p in tmp_path.iterdir()) == expected
    out = capsys.readouterr().out
    assert "saved:" in out and "50%" in out


def test_run_avoids_overwriting_existing_outputs(monkeypatch, tmp_path):
    from tests.test_jobs import FakeBackend
    from vid_snatch import cli

    backend = FakeBackend()
    for name in ("fetch_title", "download_audio", "convert_audio", "download_video", "separate"):
        monkeypatch.setattr(cli.core, name, getattr(backend, name))
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    (tmp_path / "Same Title_no_vocals.mp3").write_bytes(b"old")
    cli.run(build_parser().parse_args(["https://youtu.be/a", "-o", str(tmp_path), "--no-vocals"]))
    assert (tmp_path / "Same Title (1)_no_vocals.mp3").exists()
    assert (tmp_path / "Same Title_no_vocals.mp3").read_bytes() == b"old"


def test_run_web_reads_env_and_defaults_host_output_dir(monkeypatch, tmp_path):
    import uvicorn

    from vid_snatch import webserver

    out = tmp_path / "out"
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("VS_OUTPUT_DIR", str(out))
    monkeypatch.setenv("VS_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("VS_HOST_OUTPUT_DIR", raising=False)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, *a, **k: None)
    monkeypatch.setattr(webserver.core, "update_ytdlp", lambda timeout=30: True)

    captured = {}

    def fake_create_app(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(webserver, "create_app", fake_create_app)
    webserver.run_web(8089)

    assert captured["host_output_dir"] == str(out)
    assert str(captured["output_dir"]) == str(out)
    assert str(captured["config_dir"]) == str(cfg)
    assert out.is_dir()


def _capture_server_host(monkeypatch, tmp_path):
    import uvicorn

    from vid_snatch import webserver

    captured = {}
    orig_init = uvicorn.Server.__init__

    def spy_init(self, config):
        captured["host"] = config.host
        orig_init(self, config)

    monkeypatch.setenv("VS_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("VS_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(uvicorn.Server, "__init__", spy_init)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, *a, **k: None)
    monkeypatch.setattr(webserver.core, "update_ytdlp", lambda timeout=30: True)
    monkeypatch.setattr(webserver, "create_app", lambda **kwargs: object())
    webserver.run_web(8089)
    return captured["host"]


def test_run_web_binds_vs_bind(monkeypatch, tmp_path):
    monkeypatch.setenv("VS_BIND", "127.0.0.1")
    assert _capture_server_host(monkeypatch, tmp_path) == "127.0.0.1"


def test_run_web_defaults_to_all_interfaces(monkeypatch, tmp_path):
    monkeypatch.delenv("VS_BIND", raising=False)
    assert _capture_server_host(monkeypatch, tmp_path) == "0.0.0.0"
