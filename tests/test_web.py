import pytest
from fastapi.testclient import TestClient
from vid_snatch.web import create_app
from vid_snatch.jobs import JobQueue
from vid_snatch.hostactions import HostActionQueue
from tests.test_jobs import FakeBackend, run_until_idle

H = {"X-Vid-Snatch": "1"}
MP3 = {"audio": {"versions": ["original"]}}
ALL = {"audio": {"versions": ["original", "instrumental", "vocals"], "format": "mp3", "model": "htdemucs"},
       "video": {"max_height": 1080}}

@pytest.fixture
def env(tmp_path):
    out = tmp_path / "out"; out.mkdir(); cfg = tmp_path / "cfg"
    q = JobQueue(out, backend=FakeBackend()); q.start()
    h = HostActionQueue(started_at=0.0)
    shutdown = []
    app = create_app(out, cfg, "/Users/me/Music/vid-snatch", q, h, on_shutdown=lambda: shutdown.append(1))
    yield TestClient(app, base_url="http://localhost"), q, h, cfg, shutdown
    q.stop()

def test_health(env):
    c, *_ = env
    assert c.get("/api/health").json()["ok"] is True

def test_index_is_not_cached(env):
    c, *_ = env
    assert c.get("/").headers["cache-control"] == "no-store"

def test_post_without_header_is_403(env):
    c, *_ = env
    assert c.post("/api/jobs", json={"urls": ["https://youtu.be/a"], "outputs": MP3}).status_code == 403

def test_info_invalid_url(env):
    c, *_ = env
    r = c.get("/api/info", params={"url": "https://vimeo.com/1"})
    assert r.status_code == 400 and r.json()["message"] == "這不是 YouTube 影片網址"

def test_create_jobs_and_list_reflects_progress(env):
    c, q, *_ = env
    r = c.post("/api/jobs", json={"urls": ["https://youtu.be/a", " https://youtu.be/b?si=1 "], "outputs": MP3, "filename": "ignored"}, headers=H)
    assert r.status_code == 200 and len(r.json()["jobs"]) == 2
    run_until_idle(q)
    jobs = c.get("/api/jobs").json()["jobs"]
    assert all(j["state"] == "done" and j["step"] == j["step_total"] for j in jobs)
    assert jobs[1]["url"] == "https://youtu.be/b"

def test_create_jobs_with_per_url_filenames(env):
    c, q, *_ = env
    r = c.post("/api/jobs", json={"urls": ["https://youtu.be/a", "https://youtu.be/b", "https://youtu.be/c"], "outputs": MP3,
                                  "filenames": ["first", "", "third"], "overwrites": [False, False, True]}, headers=H)
    jobs = r.json()["jobs"]
    assert [j["filename"] for j in jobs] == ["first", None, "third"]
    assert [q.get(j["id"]).overwrite for j in jobs] == [False, False, True]

def test_create_jobs_rejects_mismatched_filenames(env):
    c, q, *_ = env
    r = c.post("/api/jobs", json={"urls": ["https://youtu.be/a", "https://youtu.be/b"], "outputs": MP3, "filenames": ["x"]}, headers=H)
    assert r.status_code == 400 and q.list() == []

def test_create_jobs_rejects_any_invalid_url(env):
    c, q, *_ = env
    r = c.post("/api/jobs", json={"urls": ["https://youtu.be/a", "nope"], "outputs": MP3}, headers=H)
    assert r.status_code == 400 and q.list() == []

def test_reveal_pushes_host_path(env):
    c, q, h, *_ = env
    job = c.post("/api/jobs", json={"urls": ["https://youtu.be/a"], "outputs": MP3, "filename": "song"}, headers=H).json()["jobs"][0]
    run_until_idle(q)
    assert c.post(f"/api/jobs/{job['id']}/reveal", headers=H).status_code == 200
    assert h.poll()[0]["payload"] == {"path": "/Users/me/Music/vid-snatch/song.mp3"}

def test_pick_folder_cancelled_keeps_setting(env):
    import threading
    c, q, h, cfg, _ = env
    def answer():
        for _ in range(50):
            acts = h.poll()
            if acts: h.set_result(acts[0]["id"], {"path": None}); return
            threading.Event().wait(0.05)
    threading.Thread(target=answer).start()
    r = c.post("/api/settings/pick-folder", headers=H).json()
    assert r == {"output_dir": "/Users/me/Music/vid-snatch", "changed": False}
    assert not (cfg / "config").exists()

def test_settings_write(env):
    c, q, h, cfg, _ = env
    r = c.post("/api/settings", json={"output_dir": "/new/dir"}, headers=H).json()
    assert r["restart_required"] is True and (cfg / "config").read_text(encoding="utf-8") == "output_dir=/new/dir\n"
    assert r["output_dir"] == "/new/dir" and r["audio_format"] == "mp3"

def test_settings_defaults(env):
    c, *_ = env
    assert c.get("/api/settings").json() == {"output_dir": "/Users/me/Music/vid-snatch", "audio_format": "mp3",
                                             "demucs_model": "htdemucs_ft", "video_max_height": None}

def test_settings_details_partial_update_without_restart(env):
    c, q, h, cfg, _ = env
    r = c.post("/api/settings", json={"audio_format": "flac", "video_max_height": 720}, headers=H).json()
    assert r == {"output_dir": "/Users/me/Music/vid-snatch", "audio_format": "flac",
                 "demucs_model": "htdemucs_ft", "video_max_height": 720, "restart_required": False}
    r = c.post("/api/settings", json={"demucs_model": "htdemucs", "video_max_height": None}, headers=H).json()
    assert r["audio_format"] == "flac" and r["demucs_model"] == "htdemucs" and r["video_max_height"] is None
    assert c.get("/api/settings").json()["video_max_height"] is None
    assert "output_dir=" not in (cfg / "config").read_text(encoding="utf-8")
    assert c.post("/api/settings", json={"demucs_model": "mdx"}, headers=H).status_code == 422
    assert c.post("/api/settings", json={"output_dir": "  "}, headers=H).status_code == 400

def test_settings_ignore_legacy_audio_bitrate(env):
    # #18：舊的快取前端可能還會送 audio_bitrate；忽略而不是 422，回應與設定檔裡都不再有它
    c, q, h, cfg, _ = env
    cfg.mkdir(exist_ok=True)
    (cfg / "config").write_text("output_dir=/x\naudio_bitrate=320\n", encoding="utf-8")
    assert "audio_bitrate" not in c.get("/api/settings").json()
    r = c.post("/api/settings", json={"audio_bitrate": 128, "audio_format": "m4a"}, headers=H)
    assert r.status_code == 200 and "audio_bitrate" not in r.json() and r.json()["audio_format"] == "m4a"
    assert (cfg / "config").read_text(encoding="utf-8") == "output_dir=/x\naudio_format=m4a\n"
    (cfg / "config").unlink()

def test_create_jobs_with_full_outputs(env):
    c, q, *_ = env
    r = c.post("/api/jobs", json={"urls": ["https://youtu.be/a"], "outputs": ALL, "filename": "song"}, headers=H)
    assert r.status_code == 200
    job = r.json()["jobs"][0]
    assert job["options"] == ALL
    assert [o["kind"] for o in job["outputs"]] == ["original", "instrumental", "vocals", "video"]
    assert [o["ext"] for o in job["outputs"]] == ["mp3", "mp3", "mp3", "mp4"]
    assert job["steps"] == ["取得資訊", "下載", "轉檔", "分離", "下載影片", "合併"]
    assert job["state"] == "queued" and job["queue_position"] == 1
    run_until_idle(q)
    done = c.get("/api/jobs").json()["jobs"][0]
    assert done["title"] == "Same Title" and done["display_name"] == "song"
    assert all(o["state"] == "done" and o["size_bytes"] > 0 for o in done["outputs"])
    assert done["outputs"][1]["filename"] == "song_no_vocals.mp3" and done["outputs"][3]["filename"] == "song.mp4"
    assert done["elapsed_seconds"] >= 0 and done["finished_at"] >= done["started_at"]

@pytest.mark.parametrize("outputs,status", [
    ({}, 400), ({"audio": {"versions": []}}, 400), ({"audio": {"versions": ["karaoke"]}}, 422),
    ({"audio": {"versions": ["original"], "model": "mdx"}}, 422), ({"video": {"max_height": 480}}, 422),
])
def test_create_jobs_rejects_bad_outputs(env, outputs, status):
    c, q, *_ = env
    r = c.post("/api/jobs", json={"urls": ["https://youtu.be/a"], "outputs": outputs}, headers=H)
    assert r.status_code == status and q.list() == []

def test_create_jobs_ignores_legacy_bitrate(env):
    # #18：舊分頁還會送 outputs.audio.bitrate；忽略而不是 422，job.options.audio 也不含 bitrate
    c, q, *_ = env
    outputs = {"audio": {"versions": ["original"], "bitrate": 320}}
    r = c.post("/api/jobs", json={"urls": ["https://youtu.be/a"], "outputs": outputs}, headers=H)
    assert r.status_code == 200
    assert r.json()["jobs"][0]["options"]["audio"] == {"versions": ["original"], "format": "mp3", "model": "htdemucs_ft"}

def test_create_jobs_rejects_legacy_mode(env):
    c, q, *_ = env
    assert c.post("/api/jobs", json={"urls": ["https://youtu.be/a"], "mode": "mp3"}, headers=H).status_code == 422

def test_exists_with_outputs(env, tmp_path):
    c, q, *_ = env
    (q.output_dir / "song_vocals.mp3").touch()
    r = c.get("/api/exists", params={"filename": "song", "versions": "original,vocals"}).json()
    assert r == {"exists": True, "suggestion": "song (1)", "files": ["song (1).mp3", "song (1)_vocals.mp3"]}
    r = c.get("/api/exists", params={"filename": "song", "versions": "original", "format": "flac", "video": "true"}).json()
    assert r == {"exists": False, "suggestion": "song", "files": ["song.flac", "song.mp4"]}
    r = c.get("/api/exists", params={"filename": "song", "versions": "original,instrumental,vocals", "format": "m4a"}).json()
    assert r["files"] == ["song.m4a", "song_no_vocals.m4a", "song_vocals.m4a"]  # 分離結果不再退回 mp3
    r = c.get("/api/exists", params={"filename": "song", "video": "true"}).json()
    assert r["files"] == ["song.mp4"]
    assert c.get("/api/exists", params={"filename": "song"}).status_code == 400

def test_reveal_uses_first_done_output(env):
    c, q, h, *_ = env
    job = c.post("/api/jobs", json={"urls": ["https://youtu.be/a"], "outputs": {"audio": {"versions": ["instrumental"]}, "video": {}}, "filename": "song"}, headers=H).json()["jobs"][0]
    run_until_idle(q)
    assert c.post(f"/api/jobs/{job['id']}/reveal", headers=H).status_code == 200
    assert h.poll()[0]["payload"] == {"path": "/Users/me/Music/vid-snatch/song_no_vocals.mp3"}

def test_shutdown_calls_hook(env):
    c, q, h, cfg, shutdown = env
    c.post("/api/shutdown", headers=H)
    assert shutdown == [1] and h.poll()[0]["kind"] == "shutdown"

def test_events_replays_existing_jobs(env):
    c, q, *_ = env
    c.post("/api/jobs", json={"urls": ["https://youtu.be/a"], "outputs": MP3, "filename": "s"}, headers=H)
    run_until_idle(q)
    body = ""
    with c.stream("GET", "/api/events") as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                body = line; break
    assert '"state": "done"' in body or '"state":"done"' in body


@pytest.mark.parametrize("method", ["get", "post"])
def test_foreign_host_is_403(env, method):
    c, *_ = env
    r = getattr(c, method)("/api/health", headers={**H, "Host": "evil.com"})
    assert r.status_code == 403 and r.json() == {"message": "forbidden"}

@pytest.mark.parametrize("host", ["localhost:8089", "127.0.0.1:8089", "localhost", "127.0.0.1"])
def test_local_host_allowed(env, host):
    c, *_ = env
    assert c.get("/api/health", headers={"Host": host}).status_code == 200


# ---- DELETE /api/jobs/{id}（取消） ----

def test_cancel_requires_csrf_header(env):
    c, *_ = env
    assert c.delete("/api/jobs/abc").status_code == 403

def test_cancel_queued_job(env):
    c, q, *_ = env
    q.stop()  # 不讓 worker 跑，工作留在排隊
    jobs = c.post("/api/jobs", json={"urls": ["https://youtu.be/a", "https://youtu.be/b"], "outputs": MP3}, headers=H).json()["jobs"]
    r = c.delete(f"/api/jobs/{jobs[0]['id']}", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "cancelled" and body["queue_position"] is None and body["finished_at"] is not None
    listed = {j["id"]: j for j in c.get("/api/jobs").json()["jobs"]}
    assert listed[jobs[0]["id"]]["state"] == "cancelled"
    assert listed[jobs[1]["id"]]["queue_position"] == 1
    # 再取消一次 → 409
    r = c.delete(f"/api/jobs/{jobs[0]['id']}", headers=H)
    assert r.status_code == 409 and r.json() == {"message": "只能取消排隊中的工作"}

def test_cancel_finished_job_is_409_and_unknown_is_404(env):
    c, q, *_ = env
    job = c.post("/api/jobs", json={"urls": ["https://youtu.be/a"], "outputs": MP3, "filename": "s"}, headers=H).json()["jobs"][0]
    run_until_idle(q)
    r = c.delete(f"/api/jobs/{job['id']}", headers=H)
    assert r.status_code == 409 and r.json()["message"] == "只能取消排隊中的工作"
    assert c.delete("/api/jobs/nope", headers=H).status_code == 404
