from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parent.parent
HTML = (ROOT / "vid_snatch/static/index.html").read_text(encoding="utf-8")

def test_required_ids_present():
    for i in ["urls", "paste", "out-audio", "out-video", "v-original", "v-instrumental", "v-vocals",
              "audio-adv", "audio-summary", "video-summary", "names", "names-row", "start", "start-count",
              "jobs", "jobs-empty", "stat-queued", "stat-running", "stat-done", "stat-failed",
              "settings-toggle", "output-dir", "pick-folder", "shutdown", "rebuild", "uninstall", "ask"]:
        assert f'id="{i}"' in HTML, i

def test_no_native_dialogs_and_no_external_scripts():
    assert not re.search(r"\b(alert|confirm|prompt)\(", HTML)
    assert "<script src=" not in HTML

def test_fonts_from_google_with_system_fallback():
    assert re.search(r'<link rel="stylesheet" href="https://fonts\.googleapis\.com/css2\?[^"]*IBM\+Plex\+Sans', HTML)
    assert "IBM+Plex+Mono" in HTML and "Noto+Sans+TC" in HTML
    assert re.search(r'--sans: "IBM Plex Sans", "Noto Sans TC", .*"PingFang TC", "Microsoft JhengHei"', HTML)
    assert re.search(r'--mono: "IBM Plex Mono", ui-monospace, Menlo, Consolas', HTML)

def test_csrf_header_and_sse_present():
    assert "X-Vid-Snatch" in HTML and "EventSource" in HTML and "prefers-color-scheme" in HTML

def test_reduced_motion_respected():
    assert "prefers-reduced-motion: reduce" in HTML

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

def test_jobs_payload_uses_outputs_not_mode():
    # #9 之後 POST /api/jobs 只收 outputs；舊的 mode 會 422
    assert 'postJson("/api/jobs", { urls: valid, outputs: outputsPayload(state), filenames, overwrites })' in HTML
    assert not re.search(r"\bmode\b\s*[:=]", HTML)
    assert "/api/exists?${existsQuery(state, filename)}" in HTML

def test_details_saved_to_settings_but_versions_are_not():
    assert 'postJson("/api/settings", { [key]: value })' in HTML
    assert re.search(r'SETTING_KEYS = \{ fmt: "audio_format", br: "audio_bitrate", mdl: "demucs_model", res: "video_max_height" \}', HTML)
    assert "outputState = applySettings(outputState, data)" in HTML

def test_icon_only_buttons_have_aria_label_and_title():
    buttons = re.findall(r"<button\b[^>]*class=\"ibtn[^\"]*\"[^>]*>", HTML)
    assert buttons, "靜態 HTML 裡至少要有一顆圖示鈕"
    for b in buttons:
        assert "aria-label=" in b and "title=" in b, b
    # 動態建立的圖示鈕走同一個 helper
    assert re.search(r'btn\.setAttribute\("aria-label", label\);\s*btn\.title = label;', HTML)

def test_sprite_has_all_icons_from_spec():
    for sym in ["dl", "gear", "paste", "check", "folder", "retry", "x", "xc", "checkc", "link", "music", "film", "mic",
                "mic-off", "clock", "play", "loader", "chev", "sliders", "trash", "disc", "title", "file", "list",
                "info", "zap", "gem", "alert", "eye"]:
        assert f'<symbol id="i-{sym}"' in HTML, sym

def test_queue_dom_contract_for_cards():
    # #11 會接在這些約定上
    assert 'card.className = `job ${job.state}`' in HTML
    assert "card.dataset.id = job.id" in HTML and "card.dataset.state = job.state" in HTML
    assert "jobsEl.prepend(card)" in HTML
    for cls in [".job.running", ".job.done", ".job.failed", ".job.queued", ".jt", ".st", ".kv", ".outs", ".o", ".bar", ".pct", ".acts", ".err", ".divider"]:
        assert cls + " {" in HTML or cls + "," in HTML, cls

def test_outputs_state_machine_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("沒有 node")
    # 測試名稱是中文；Windows 預設編碼解不開會在 reader thread 炸掉，明確用 UTF-8
    r = subprocess.run([node, "--test", str(ROOT / "tests/outputs_state.test.mjs")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
