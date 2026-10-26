import pytest
from fastapi.testclient import TestClient
from vid_snatch.web import create_app
from vid_snatch.jobs import JobQueue
from vid_snatch.hostactions import HostActionQueue
from tests.test_jobs import FakeBackend, run_until_idle

H = {"X-Vid-Snatch": "1"}

@pytest.fixture
def env(tmp_path):
    out = tmp_path / "out"; out.mkdir(); cfg = tmp_path / "cfg"
    q = JobQueue(out, backend=FakeBackend()); q.start()
    h = HostActionQueue(started_at=0.0)
    shutdown = []
    app = create_app(out, cfg, "/Users/me/Music/vid-snatch", q, h, on_shutdown=lambda: shutdown.append(1))
    yield TestClient(app), q, h, cfg, shutdown
    q.stop()

def test_health(env):
    c, *_ = env
    assert c.get("/api/health").json()["ok"] is True

def test_post_without_header_is_403(env):
    c, *_ = env
    assert c.post("/api/jobs", json={"urls": ["https://youtu.be/a"], "mode": "mp3"}).status_code == 403

def test_info_invalid_url(env):
    c, *_ = env
    r = c.get("/api/info", params={"url": "https://vimeo.com/1"})
    assert r.status_code == 400 and r.json()["message"] == "這不是 YouTube 影片網址"

def test_create_jobs_and_list_reflects_progress(env):
    c, q, *_ = env
    r = c.post("/api/jobs", json={"urls": ["https://youtu.be/a", " https://youtu.be/b?si=1 "], "mode": "mp3", "filename": "ignored"}, headers=H)
    assert r.status_code == 200 and len(r.json()["jobs"]) == 2
    run_until_idle(q)
    jobs = c.get("/api/jobs").json()["jobs"]
    assert all(j["state"] == "done" and j["step"] == j["step_total"] for j in jobs)
    assert jobs[1]["url"] == "https://youtu.be/b"

def test_create_jobs_rejects_any_invalid_url(env):
    c, q, *_ = env
    r = c.post("/api/jobs", json={"urls": ["https://youtu.be/a", "nope"], "mode": "mp3"}, headers=H)
    assert r.status_code == 400 and q.list() == []

def test_reveal_pushes_host_path(env):
    c, q, h, *_ = env
    job = c.post("/api/jobs", json={"urls": ["https://youtu.be/a"], "mode": "mp3", "filename": "song"}, headers=H).json()["jobs"][0]
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
    assert r["restart_required"] is True and (cfg / "config").read_text() == "output_dir=/new/dir\n"

def test_shutdown_calls_hook(env):
    c, q, h, cfg, shutdown = env
    c.post("/api/shutdown", headers=H)
    assert shutdown == [1] and h.poll()[0]["kind"] == "shutdown"

def test_events_replays_existing_jobs(env):
    c, q, *_ = env
    c.post("/api/jobs", json={"urls": ["https://youtu.be/a"], "mode": "mp3", "filename": "s"}, headers=H)
    run_until_idle(q)
    body = ""
    with c.stream("GET", "/api/events") as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                body = line; break
    assert '"state": "done"' in body or '"state":"done"' in body
