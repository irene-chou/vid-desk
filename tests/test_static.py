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
              "jobs", "jobs-empty", "jobs-done", "done-divider", "clear-done", "version", "update-failed",
              "settings-toggle", "settings", "settings-close", "output-dir", "pick-folder", "shutdown", "uninstall", "ask"]:
        assert f'id="{i}"' in HTML, i

def test_header_shows_version_without_stats():
    # #25：頁首只剩 logo + 名稱 + 版本（左）與右側的 icon 按鈕（#37 之後是主題切換 + 齒輪）；四個狀態統計與 updateStats / jobsById 一併移除
    for needle in ("stat-queued", "stat-running", "stat-done", "stat-failed", 'id="stats"', "updateStats", "jobsById", ".stat {", ".hdr .stat"):
        assert needle not in HTML, needle
    header = re.search(r'<header class="hdr">(.*?)</header>', HTML, re.S).group(1)
    assert re.search(r'<div class="brand">.*<h1>vid-snatch</h1><span class="ver" id="version" hidden></span></div>', header)
    assert header.count("<button") == 2 and 'id="settings-toggle"' in header and 'id="theme-toggle"' in header
    # 版本號：名稱右側等寬小字、--muted 色；載入設定時填入，取不到就維持隱藏
    assert ".brand .ver { font-family: var(--mono); font-size: 0.78rem; font-weight: 400; color: var(--muted); }" in HTML
    assert "showVersion(data.version);" in HTML
    assert re.search(r'function showVersion\(version\)\s*\{[^}]*if \(typeof version !== "string" \|\| !version\) return;\s*ver\.textContent = `v\$\{version\}`;\s*ver\.hidden = false;', HTML, re.S)

def test_settings_is_modal_dialog():
    # #20：設定改成原生 <dialog> modal，開關不推擠版面
    assert '<dialog id="settings" class="settings" aria-label="設定">' in HTML
    assert '<section id="settings"' not in HTML and ".settings { grid-column" not in HTML
    toggle = re.search(r'<button id="settings-toggle"[^>]*>', HTML).group(0)
    assert 'aria-haspopup="dialog"' in toggle and 'aria-controls="settings"' in toggle and 'aria-expanded="false"' in toggle
    close = re.search(r'<button id="settings-close"[^>]*>', HTML).group(0)
    assert 'aria-label="關閉"' in close and 'title="關閉"' in close
    # 齒輪 showModal；關閉鈕、點 backdrop 都走 dialog.close()，Esc 走原生 cancel；關閉後焦點回齒輪並同步 aria-expanded
    assert re.search(r"function openSettings\(\)\s*\{[^}]*dialog\.showModal\(\);", HTML, re.S)
    assert '$("settings-toggle").addEventListener("click", openSettings);' in HTML
    assert '$("settings-close").addEventListener("click", () => $("settings").close());' in HTML
    assert '$("settings").addEventListener("click", onSettingsBackdropClick);' in HTML
    assert '$("settings").addEventListener("close", onSettingsClosed);' in HTML
    assert re.search(r"function onSettingsClosed\(\)\s*\{[^}]*setAttribute\(\"aria-expanded\", \"false\"\);\s*btn\.focus\(\);", HTML, re.S)
    assert re.search(r"function onSettingsBackdropClick\(event\)\s*\{\s*const dialog = \$\(\"settings\"\);\s*if \(event\.target !== dialog\) return;", HTML)
    assert "function toggleSettings" not in HTML
    # 桌面 480px 置中、窄版貼齊 16px 邊距；內容過高時 dialog 內捲、頁面不捲
    assert re.search(r"dialog\.settings \{[^}]*width: min\(480px, calc\(100vw - 32px\)\);[^}]*max-height: calc\(100dvh - 32px\);[^}]*overflow: auto;", HTML)
    assert re.search(r"dialog\.settings\[open\] \{ display: grid; gap: 14px;", HTML)
    assert "body:has(dialog.settings[open]) { overflow: hidden; }" in HTML
    # body 是捲動容器並保留捲軸空間：鎖住捲動時非 overlay 捲軸（Windows）下底層內容不位移
    assert "html { height: 100%; overflow: hidden; }" in HTML
    assert "body { height: 100%; overflow-y: auto; scrollbar-gutter: stable; }" in HTML
    assert "html:has(dialog" not in HTML

def test_advanced_notice_spaced_from_buttons():
    # #20 追加：「進階」底下的狀態訊息與按鈕列要分開（8px，與 .row 的 margin-top 同一個間距）
    assert ".settings details .notice { margin-top: 8px; }" in HTML
    assert re.search(r'<details>\s*<summary>進階.*?</summary>\s*<div class="row">.*?</div>\s*<div id="advanced-notice" class="notice" hidden></div>\s*</details>', HTML, re.S)

def test_settings_advanced_has_no_update_button():
    # #27：設定 → 進階只剩「解除安裝」；showAdvancedNotice 仍給更換資料夾 / 解除安裝用
    for needle in ('id="rebuild"', "更新 vid-snatch", "function rebuild()", '$("rebuild")'):
        assert needle not in HTML, needle
    adv = re.search(r"<details>\s*<summary>進階.*?</details>", HTML, re.S).group(0)
    assert re.findall(r"<button\b[^>]*>", adv) == ['<button id="uninstall" type="button" class="danger">']
    assert "function showAdvancedNotice(text)" in HTML
    assert HTML.count("showAdvancedNotice(") >= 3

def test_update_failed_banner_is_page_level_without_buttons():
    # #31：自動更新下載工具後仍失敗改成頁面層級橫幅（頁首下方、輸入區上方、跨兩欄），不分平台、沒有按鈕
    banner = re.search(r'<div id="update-failed" class="banner" role="status" hidden>(.*?)</div>', HTML).group(1)
    assert banner == '<svg class="ic"><use href="#i-alert"/></svg><span>YouTube 可能改版了，自動修復沒有成功。請稍後關閉並重新開啟 vid-snatch 再試。</span>'
    assert "<button" not in banner
    assert HTML.index("</header>") < HTML.index('id="update-failed"') < HTML.index('<section class="panel" id="input"')
    assert re.search(r"\.banner \{ grid-column: 1 / -1;[^}]*var\(--warn\)", HTML)
    # 純函式在 @@card-fns 區塊（node 測）：只看欄位，不比對中文訊息
    assert re.search(r'function isUpdateFailed\(job\)\s*\{\s*return job\.state === "failed" && job\.error_kind === "update_failed";', HTML)
    assert "function showsUpdateFailedBanner(jobs)" in HTML
    # 每次卡片重畫 / 清除都重算；資料從卡片 dataset 來
    assert '$("update-failed").hidden = !showsUpdateFailedBanner(cardJobs());' in HTML
    assert 'card.dataset.errorKind = job.error_kind || "";' in HTML
    assert "card.dataset.createdAt = String(job.created_at || 0);" in HTML

def test_update_failed_card_has_no_update_button():
    # #31：卡片只剩錯誤訊息 + 原有「重試」；#27 的「更新」鈕、can_upgrade、cardNotice 等整段移除
    for needle in ("can_upgrade", "canUpgrade", "updateButton", "cardNotice", "cardMessage", "failureText",
                   "showsUpdateButton", "hasActiveJobs", 'createTextNode("更新")', "button.txt", "/api/rebuild", "元件"):
        assert needle not in HTML, needle
    failed = re.search(r'if \(job\.state === "failed"\) \{(.*?)\n  \}', HTML, re.S).group(1)
    assert 'document.createTextNode(job.message || "發生錯誤")' in failed
    assert re.findall(r"acts\.append\((\w+)", failed) == ["eye", "retryButton"]
    # 啟動順序還原成三個獨立呼叫
    assert re.search(r"renderOutputs\(\);\s*loadSettings\(\);\s*loadJobs\(\);\s*connectEvents\(\);\s*</script>", HTML)

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

def test_every_summary_has_chevron():
    # #19：每個 <details> 的 summary 都要有自訂箭頭，原生三角形則隱藏，避免兩個箭頭
    summaries = re.findall(r"<summary\b[^>]*>.*?</summary>", HTML, re.S)
    assert len(summaries) >= 2, "至少要有「進階」與「細項」兩個 summary"
    for s in summaries:
        assert "#i-chev" in s, s
    assert re.search(r"\.settings details > summary::-webkit-details-marker \{ display: none; \}", HTML)
    assert re.search(r"\.settings details > summary \{[^}]*list-style: none;", HTML)
    assert re.search(r"\.settings details\[open\] > summary \.chev \{ transform: rotate\(180deg\); \}", HTML)
    # reduced-motion 下箭頭不動畫
    assert re.search(r"prefers-reduced-motion: reduce\) \{[^@]*\.settings details > summary \.chev \{ transition: none; \}", HTML, re.S)

def test_post_responses_do_not_overwrite_newer_sse_state():
    # POST /api/jobs 與重試的回應可能比 SSE 舊；卡片已存在就不要覆蓋
    assert re.search(r"function renderIfNew\(job\)\s*\{\s*if \(!cards\.has\(job\.id\)\) renderJob\(job\);", HTML)
    assert "(data.jobs || []).forEach(renderIfNew)" in HTML
    assert "renderIfNew(await postJson(`/api/jobs/${job.id}/retry`))" in HTML

def test_card_name_falls_back_to_display_name():
    assert "job.filename || job.display_name || job.url" in HTML

def test_color_scheme_declared():
    assert re.search(r":root\s*\{\s*color-scheme: light dark;", HTML)

COLOR_TOKENS = ["--bg", "--panel", "--fg", "--muted", "--line", "--sub", "--accent", "--accent-fg", "--ok", "--bad", "--warn"]

def _tokens(block):
    return dict(re.findall(r"(--[a-z-]+): (#[0-9a-f]{6});", block))

def test_dark_tokens_both_selectors_in_sync():
    # #26：深色 token 寫兩份——系統深色且沒選淺色、明確選深色——兩處的「變數: 值」必須完全相同，
    # 淺色（:root）定義同一組變數名；color-scheme 跟著切
    light = re.search(r":root\s*\{\s*color-scheme: light dark;(.*?)\n  \}", HTML, re.S).group(1)
    media = re.search(r'@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \{\s*color-scheme: dark;(.*?)\n    \}\s*\}', HTML, re.S)
    forced = re.search(r':root\[data-theme="dark"\] \{\s*color-scheme: dark;(.*?)\n  \}', HTML, re.S)
    assert media and forced, "兩個深色選擇器都要在"
    dark_media, dark_forced = _tokens(media.group(1)), _tokens(forced.group(1))
    assert dark_media == dark_forced, "兩份深色 token 不同步"
    assert set(dark_media) == set(_tokens(light)) == set(COLOR_TOKENS)
    assert dark_media != _tokens(light)
    assert dark_media["--bg"] == "#0f1114" and dark_media["--accent"] == "#2dd4bf"
    assert ':root[data-theme="light"] { color-scheme: light; }' in HTML
    assert "light-dark(" not in HTML

def test_theme_toggle_button_in_header():
    # #37：頁首右側、設定齒輪左邊有一顆 .ibtn 主題切換鈕；sprite 有太陽 / 月亮
    header = re.search(r'<header class="hdr">(.*?)</header>', HTML, re.S).group(1)
    btn = re.search(r'<button id="theme-toggle" class="ibtn" type="button" aria-label="([^"]+)" title="([^"]+)">'
                    r'<svg class="ic"><use id="theme-icon" href="#i-moon"/></svg></button>', header)
    assert btn and btn.group(1) == btn.group(2)
    assert header.index('id="theme-toggle"') < header.index('id="settings-toggle"')
    assert '<symbol id="i-sun" viewBox="0 0 24 24">' in HTML and '<symbol id="i-moon" viewBox="0 0 24 24">' in HTML
    # 圖示與 aria-label / title 都是「點了會切到的主題」：淺色時月亮「切換為深色」，深色時太陽「切換為淺色」
    assert re.search(r'const label = next === "dark" \? "切換為深色" : "切換為淺色";\s*const btn = \$\("theme-toggle"\);\s*'
                     r'btn\.setAttribute\("aria-label", label\);\s*btn\.title = label;\s*'
                     r'\$\("theme-icon"\)\.setAttribute\("href", next === "dark" \? "#i-moon" : "#i-sun"\);', HTML)
    # 點擊：切到與實際顯示相反的主題、固定、存 localStorage、更新圖示
    assert re.search(r"function toggleTheme\(\)\s*\{\s*const theme = nextTheme\(effectiveTheme\(\)\);\s*"
                     r"applyTheme\(document\.documentElement, theme\);\s*writeTheme\(\(\) => localStorage, theme\);\s*renderThemeToggle\(\);", HTML)
    assert '$("theme-toggle").addEventListener("click", toggleTheme);' in HTML
    # 跟隨系統時系統切換深淺，圖示即時跟著變
    assert 'const systemDarkQuery = window.matchMedia("(prefers-color-scheme: dark)");' in HTML
    assert 'systemDarkQuery.addEventListener("change", renderThemeToggle);' in HTML
    assert "renderThemeToggle();" in HTML
    # 主題不走後端設定
    assert '"theme"' not in re.search(r"SETTING_KEYS = \{[^}]*\}", HTML).group(0)

def test_no_theme_option_in_settings():
    # #37：設定 modal 裡沒有主題選項了（#26 的三段式已移除）
    settings = re.search(r'<dialog id="settings".*?</dialog>', HTML, re.S).group(0)
    assert "主題" not in settings and 'name="theme"' not in settings and "lbl-theme" not in settings
    assert "renderTheme(" not in HTML and "onThemeChange" not in HTML

def test_theme_applied_in_head_before_first_paint():
    # <head> 裡的 inline script 在樣式表之前就把 data-theme 設好，開頁不閃錯的主題
    head = re.search(r"<head>(.*?)</head>", HTML, re.S).group(1)
    script = re.search(r"<script>(.*?)</script>", head, re.S)
    assert script, "head 裡要有早期套用腳本"
    assert head.index("<script>") < head.index('<link rel="stylesheet"') < head.index("<style>")
    body = script.group(1)
    assert "// @@theme-begin" in body and "// @@theme-end" in body
    assert 'const THEME_KEY = "vid-snatch.theme";' in body
    assert "applyTheme(document.documentElement, readTheme(() => localStorage));" in body
    # 讀寫都包 try，localStorage 不可用時當跟隨系統
    assert re.search(r"function readTheme\(getStorage\)\s*\{\s*try \{ return parseTheme\(getStorage\(\)\.getItem\(THEME_KEY\)\); \} catch \(e\) \{ return \"system\"; \}", body)
    assert re.search(r"function writeTheme\(getStorage, theme\)\s*\{\s*try \{", body)
    assert re.search(r'if \(theme === "system"\) root\.removeAttribute\("data-theme"\); else root\.setAttribute\("data-theme", theme\);', body)
    # #37 的純函式也在同一區塊，node 測試從這裡抽
    assert "function resolveTheme(theme, systemDark)" in body and "function nextTheme(effective)" in body

def test_network_errors_become_chinese_message():
    assert HTML.count('throw new Error("發生錯誤")') >= 2

def test_jobs_payload_uses_outputs_not_mode():
    # #9 之後 POST /api/jobs 只收 outputs；舊的 mode 會 422
    assert 'postJson("/api/jobs", { urls: valid, outputs: outputsPayload(state), filenames, overwrites })' in HTML
    assert not re.search(r"\bmode\b\s*[:=]", HTML)
    assert "/api/exists?${existsQuery(state, filename)}" in HTML

def test_details_saved_to_settings_but_versions_are_not():
    assert 'postJson("/api/settings", { [key]: value })' in HTML
    assert re.search(r'SETTING_KEYS = \{ fmt: "audio_format", mdl: "demucs_model", res: "video_max_height" \}', HTML)
    assert "outputState = applySettings(outputState, data)" in HTML

def test_no_bitrate_option():
    # #18：位元率固定 192k，細項裡沒有位元率列，也不再讀寫 audio_bitrate
    for needle in ("row-bitrate", 'name="br"', "audio_bitrate", "bitrate", "位元率"):
        assert needle not in HTML, needle

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

def test_footer_has_github_and_kofi_links():
    # #43：Ko-fi 從設定視窗搬到主頁面 footer；置中小字 --muted，兩個連結新分頁開啟、hover 才變 accent
    dialog = re.search(r'<dialog id="settings"(.*?)</dialog>', HTML, re.S).group(1)
    assert "ko-fi" not in dialog and 'class="kofi"' not in HTML and ".settings .kofi" not in HTML
    footer = re.search(r'<footer class="ftr">(.*?)</footer>', HTML, re.S).group(1)
    assert HTML.index("<footer") > HTML.index('id="jobs-done"')  # 排在內容之後
    assert re.sub(r"<[^>]+>", " ", footer).split() == ["Made", "by", "Irene", "·", "GitHub", "·", "☕", "請我喝杯咖啡"]
    links = re.findall(r'<a ([^>]*)>([^<]*)</a>', footer)
    assert [(dict(re.findall(r'(\w+)="([^"]*)"', attrs))["href"], text) for attrs, text in links] == [
        ("https://github.com/irene-chou/vid-snatch", "GitHub"),
        ("https://ko-fi.com/zephyrinn", "☕ 請我喝杯咖啡"),
    ]
    for attrs, _ in links:
        a = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        assert a["target"] == "_blank" and "noopener" in a["rel"].split()
    assert HTML.count("ko-fi.com") == 1  # 只在 footer
    assert ".ftr { grid-column: 1 / -1; padding-top: 12px; border-top: 1px solid var(--line); text-align: center; font-size: 0.74rem; color: var(--muted);" in HTML
    assert ".ftr a { color: inherit; text-decoration: none; }" in HTML
    assert ".ftr a:hover { color: var(--accent); text-decoration: underline; }" in HTML
    assert not re.search(r"\.ftr\s*\{[^}]*position:", HTML)  # 不 fixed/sticky

@pytest.mark.parametrize("script", ["outputs_state.test.mjs", "queue_cards.test.mjs", "theme.test.mjs"])
def test_pure_functions_in_node(script):
    node = shutil.which("node")
    if not node:
        pytest.skip("沒有 node")
    # 測試名稱是中文；Windows 預設編碼解不開會在 reader thread 炸掉，明確用 UTF-8
    r = subprocess.run([node, "--test", str(ROOT / "tests" / script)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
