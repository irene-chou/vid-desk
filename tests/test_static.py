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
              "jobs", "jobs-empty", "jobs-done", "done-divider", "clear-done", "stat-queued", "stat-running", "stat-done", "stat-failed",
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
    # 新卡片放最上面；狀態變成完成 / 失敗 / 取消時搬到「已完成」那個 ul
    assert "const list = listFor(job.state);" in HTML and "if (card.parentNode !== list) list.prepend(card);" in HTML
    assert re.search(r"function listFor\(state\)\s*\{\s*return isFinished\(state\) \? doneEl : jobsEl;", HTML)
    for cls in [".job.running", ".job.done", ".job.failed", ".job.queued", ".job.cancelled", ".jt", ".st", ".kv", ".outs", ".o", ".bar", ".pct", ".acts", ".err", ".divider"]:
        assert cls + " {" in HTML or cls + "," in HTML, cls

def test_card_source_link_opens_new_tab_safely():
    assert 'link.target = "_blank";' in HTML and 'link.rel = "noopener";' in HTML
    assert "link.textContent = shortUrl(job.url);" in HTML

def test_card_sections_present():
    # 細節列、輸出膠囊、進度、失敗訊息、各狀態動作鈕
    for fn in ["function buildDetails(job)", "function buildOutputs(job)", "function buildProgress(job)", "function retryButton(job, card)"]:
        assert fn in HTML, fn
    assert 'iconButton("x", "取消"' in HTML and "deleteJson(`/api/jobs/${job.id}`)" in HTML
    assert 'iconButton("folder", "顯示檔案"' in HTML and 'iconButton("eye", "查看詳情"' in HTML and 'iconButton("retry", "重試"' in HTML
    assert 'if (job.state === "queued") {' in HTML and 'if (job.state === "cancelled") {' in HTML
    assert 'if (job.state === "done") {' in HTML and 'if (job.state === "failed") {' in HTML
    assert 'icon(OUTPUT_STATE_ICONS[output.state], output.state === "running" ? "spin" : "")' in HTML

def test_delete_sends_csrf_header():
    assert re.search(r'function deleteJson\(path\)\s*\{\s*return sendJson\("DELETE", path\);', HTML)
    assert re.search(r'function postJson\(path, body\)\s*\{\s*return sendJson\("POST", path, body\);', HTML)
    assert re.search(r'method,\s*headers: \{ "Content-Type": "application/json", "X-Vid-Snatch": "1" \}', HTML)

def test_timer_uses_received_elapsed_not_server_clock():
    # 前端計時以收到 job 時的 elapsed_seconds 為基準，不拿本機時鐘去減伺服器 started_at
    assert not re.search(r"Date\.now\(\)\s*/\s*1000\s*-\s*job\.started_at", HTML)
    assert "timing.set(job.id, timingBase(job, performance.now()))" in HTML
    # 沒有進行中的卡片就停掉計時器
    assert "if (timing.size > 0 && timerId === null) timerId = setInterval(tickTimers, 1000);" in HTML
    assert "else if (timing.size === 0 && timerId !== null) { clearInterval(timerId); timerId = null; }" in HTML

def test_detail_expansion_survives_rerender():
    assert "pre.hidden = !expandedDetails.has(job.id);" in HTML
    assert "if (pre.hidden) expandedDetails.delete(job.id); else expandedDetails.add(job.id);" in HTML

def test_clear_done_hides_in_frontend_only():
    assert "function clearDone()" in HTML and "clearedIds.add(id);" in HTML
    assert "if (clearedIds.has(job.id)) return;" in HTML
    assert not re.search(r'deleteJson\(`/api/jobs/\$\{id\}`\)', HTML)

@pytest.mark.parametrize("script", ["outputs_state.test.mjs", "queue_cards.test.mjs"])
def test_pure_functions_in_node(script):
    node = shutil.which("node")
    if not node:
        pytest.skip("沒有 node")
    # 測試名稱是中文；Windows 預設編碼解不開會在 reader thread 炸掉，明確用 UTF-8
    r = subprocess.run([node, "--test", str(ROOT / "tests" / script)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
