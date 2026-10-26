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
