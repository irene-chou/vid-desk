import threading
from pathlib import Path
import pytest
from vid_snatch.jobs import JobQueue, MODES
from vid_snatch.errors import VidSnatchError

class FakeBackend:
    def __init__(self): self.updated = 0; self.fail_once = False
    def fetch_title(self, url): return "Same Title"
    def download_audio(self, url, output_dir, filename, audio_format="mp3", on_progress=None):
        if self.fail_once:
            self.fail_once = False
            raise VidSnatchError("extractor_outdated", "YouTube 改版，正在自動更新下載工具…", "403")
        on_progress and on_progress(50.0)
        p = output_dir / f"{filename}.{audio_format}"; p.write_bytes(b"x"); return p
    def download_video(self, url, output_dir, filename, on_progress=None):
        p = output_dir / f"{filename}.mp4"; p.write_bytes(b"x"); return p
    def remove_vocals(self, audio_path, output_dir, on_progress=None):
        p = output_dir / f"{audio_path.stem}_no_vocals.mp3"; p.write_bytes(b"x"); return p
    def update_ytdlp(self, timeout=30): self.updated += 1; return True

def run_until_idle(q, timeout=5):
    deadline = threading.Event()
    for _ in range(int(timeout * 20)):
        if all(j.state in ("done", "failed") for j in q.list()): return
        deadline.wait(0.05)
    raise AssertionError("queue did not drain")

@pytest.fixture
def q(tmp_path):
    q = JobQueue(tmp_path, backend=FakeBackend()); q.start(); yield q; q.stop()

def test_mp3_job_completes_with_steps(q, tmp_path):
    events = q.subscribe()
    job = q.add("https://youtu.be/a", "mp3")
    run_until_idle(q)
    assert job.state == "done" and job.result_path == str(tmp_path / "Same Title.mp3")
    seen = [events.get_nowait() for _ in range(events.qsize())]
    assert [e["step_name"] for e in seen if e["state"] == "running"][:2] == ["取得資訊", "下載"]
    assert any(e["percent"] == 50.0 for e in seen)
    assert job.step_total == len(MODES["mp3"])

def test_same_title_twice_gets_suffix(q, tmp_path):
    q.add("https://youtu.be/a", "mp3"); q.add("https://youtu.be/b", "mp3")
    run_until_idle(q)
    paths = sorted(j.result_path for j in q.list())
    assert paths == [str(tmp_path / "Same Title (1).mp3"), str(tmp_path / "Same Title.mp3")]

def test_no_vocals_removes_wav(q, tmp_path):
    job = q.add("https://youtu.be/a", "no_vocals", filename="song")
    run_until_idle(q)
    assert job.result_path == str(tmp_path / "song_no_vocals.mp3")
    assert not (tmp_path / "song.wav").exists()

def test_outdated_extractor_updates_and_retries(q):
    q.backend.fail_once = True
    job = q.add("https://youtu.be/a", "mp3")
    run_until_idle(q)
    assert job.state == "done" and q.backend.updated == 1

def test_exists_suggestion(q, tmp_path):
    (tmp_path / "song.mp3").touch()
    assert q.exists("song", "mp3") == (True, "song (1)")
    assert q.exists("other", "mp3") == (False, "other")
