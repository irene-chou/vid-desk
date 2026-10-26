import threading
from pathlib import Path
import pytest
from vid_snatch.jobs import JobQueue, MODES
from vid_snatch.errors import VidSnatchError

class FakeBackend:
    def __init__(self):
        self.updated = 0; self.fail_once = False; self.title_failures = 0; self.overwrites = []
    def fetch_title(self, url):
        if self.title_failures:
            self.title_failures -= 1
            raise VidSnatchError("extractor_outdated", "YouTube 改版，正在自動更新下載工具…", "Unable to extract title")
        return "Same Title"
    def download_audio(self, url, output_dir, filename, audio_format="mp3", on_progress=None, *, overwrite=False):
        self.overwrites.append(overwrite)
        if self.fail_once:
            self.fail_once = False
            raise VidSnatchError("extractor_outdated", "YouTube 改版，正在自動更新下載工具…", "403")
        on_progress and on_progress(50.0)
        p = output_dir / f"{filename}.{audio_format}"; p.write_bytes(b"x"); return p
    def download_video(self, url, output_dir, filename, on_progress=None, *, overwrite=False):
        self.overwrites.append(overwrite)
        p = output_dir / f"{filename}.mp4"; p.write_bytes(b"x"); return p
    def remove_vocals(self, audio_path, output_dir, on_progress=None):
        on_progress and on_progress(50.0)
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
    events = q.subscribe()
    job = q.add("https://youtu.be/a", "no_vocals", filename="song")
    run_until_idle(q)
    seen = [events.get_nowait() for _ in range(events.qsize())]
    assert any(e["step"] == 4 and e["percent"] == 50.0 for e in seen)
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

def test_no_vocals_existing_target_gets_clean_suffix(q, tmp_path):
    (tmp_path / "song_no_vocals.mp3").touch()
    assert q.exists("song", "no_vocals") == (True, "song (1)")
    job = q.add("https://youtu.be/a", "no_vocals", filename="song")
    run_until_idle(q)
    assert job.result_path == str(tmp_path / "song (1)_no_vocals.mp3")

def test_stop_with_pending_jobs_ends_worker(tmp_path):
    gate = threading.Event()

    class Slow(FakeBackend):
        def download_audio(self, *a, **k):
            gate.wait(5)
            return super().download_audio(*a, **k)

    q = JobQueue(tmp_path, backend=Slow()); q.start()
    for i in range(4): q.add(f"https://youtu.be/{i}", "mp3", filename=f"s{i}")
    worker = q._thread
    threading.Timer(0.2, gate.set).start()
    q.stop()
    assert not worker.is_alive()
    assert q._thread is None


def test_title_outdated_updates_and_retries(q):
    q.backend.title_failures = 1
    job = q.add("https://youtu.be/a", "mp3")
    run_until_idle(q)
    assert job.state == "done" and q.backend.updated == 1

def test_title_outdated_twice_fails_with_message(q):
    q.backend.title_failures = 2
    job = q.add("https://youtu.be/a", "mp3")
    run_until_idle(q)
    assert job.state == "failed" and q.backend.updated == 1
    assert job.message == "更新後仍無法下載，請稍後再試"
    assert job.error_kind == "extractor_outdated"
    assert job.detail == "Unable to extract title"

def test_display_name_is_resolved_title(q):
    job = q.add("https://youtu.be/a", "mp3", filename=None)
    assert job.to_dict()["display_name"] is None
    run_until_idle(q)
    assert job.display_name == "Same Title"

@pytest.mark.parametrize("mode", ["mp3", "mp4", "no_vocals"])
def test_overwrite_is_passed_to_backend(q, mode):
    q.add("https://youtu.be/a", mode, filename="x", overwrite=True)
    q.add("https://youtu.be/b", mode, filename="y")
    run_until_idle(q)
    assert q.backend.overwrites == [True, False]

def test_no_vocals_skips_name_with_existing_wav(q, tmp_path):
    (tmp_path / "song.wav").write_bytes(b"keep")
    assert q.exists("song", "no_vocals") == (True, "song (1)")
    job = q.add("https://youtu.be/a", "no_vocals", filename="song")
    run_until_idle(q)
    assert job.result_path == str(tmp_path / "song (1)_no_vocals.mp3")
    assert (tmp_path / "song.wav").read_bytes() == b"keep"
