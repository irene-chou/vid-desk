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

def test_post_responses_do_not_overwrite_newer_sse_state():
    # POST /api/jobs 與重試的回應可能比 SSE 舊；卡片已存在就不要覆蓋
    assert re.search(r"function renderIfNew\(job\)\s*\{\s*if \(!cards\.has\(job\.id\)\) renderJob\(job\);", HTML)
    assert "(data.jobs || []).forEach(renderIfNew)" in HTML
    assert "renderIfNew(await postJson(`/api/jobs/${job.id}/retry`))" in HTML

def test_card_name_falls_back_to_display_name():
    assert "job.filename || job.display_name || job.url" in HTML

def test_color_scheme_declared():
    assert re.search(r":root\s*\{\s*color-scheme: light dark;", HTML)

def test_network_errors_become_chinese_message():
    assert HTML.count('throw new Error("發生錯誤")') >= 2
