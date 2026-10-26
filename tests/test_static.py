from pathlib import Path
import re

HTML = (Path(__file__).parent.parent / "vid_snatch/static/index.html").read_text()

def test_required_ids_present():
    for i in ["urls", "paste", "mode-mp3", "mode-no_vocals", "mode-mp4", "filename", "start", "jobs",
              "settings-toggle", "output-dir", "pick-folder", "shutdown", "rebuild", "uninstall"]:
        assert f'id="{i}"' in HTML, i

def test_no_native_dialogs_and_no_external_scripts():
    assert not re.search(r"\b(alert|confirm|prompt)\(", HTML)
    assert "<script src=" not in HTML

def test_csrf_header_and_sse_present():
    assert "X-Vid-Snatch" in HTML and "EventSource" in HTML and "prefers-color-scheme" in HTML
