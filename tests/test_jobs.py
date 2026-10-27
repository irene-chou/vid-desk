import threading
from pathlib import Path
import pytest
from vid_snatch.jobs import JobQueue
from vid_snatch.outputs import OutputOptions
from vid_snatch.errors import VidSnatchError

class FakeBackend:
    def __init__(self):
        self.updated = 0; self.fail_once = False; self.title_failures = 0; self.overwrites = []
        self.calls = []
    def fetch_title(self, url):
        if self.title_failures:
            self.title_failures -= 1
            raise VidSnatchError("extractor_outdated", "YouTube 改版，正在自動更新下載工具…", "Unable to extract title")
        return "Same Title"
    def download_audio(self, url, output_dir, filename, audio_format="mp3", on_progress=None, *, overwrite=False):
        self.overwrites.append(overwrite)
        self.calls.append(("download_audio", audio_format))
        if self.fail_once:
            self.fail_once = False
            raise VidSnatchError("extractor_outdated", "YouTube 改版，正在自動更新下載工具…", "403")
        on_progress and on_progress(50.0)
        on_progress and on_progress(None)
        p = output_dir / f"{filename}.{audio_format}"; p.write_bytes(b"x" * 10); return p
    def convert_audio(self, src, dst, audio_format):
        self.calls.append(("convert_audio", audio_format))
        dst.write_bytes(b"y" * 5); return dst
    def download_video(self, url, output_dir, filename, on_progress=None, *, overwrite=False, max_height=None):
        self.overwrites.append(overwrite)
        self.calls.append(("download_video", max_height))
        on_progress and on_progress(50.0)
        on_progress and on_progress(None)
        on_progress and on_progress(None)  # 影片 + 音訊兩個檔案各一次 finished
        p = output_dir / f"{filename}.mp4"; p.write_bytes(b"x"); return p
    def separate(self, audio_path, output_dir, on_progress=None, *, model="htdemucs_ft", stems=("instrumental",), audio_format="mp3"):
        self.calls.append(("separate", model, tuple(stems), audio_format))
        on_progress and on_progress(50.0)
        out = {}
        for s in stems:
            p = output_dir / f"{audio_path.stem}{'_no_vocals' if s == 'instrumental' else '_vocals'}.{audio_format}"
            p.write_bytes(b"z" * 3); out[s] = p
        return out
    def update_ytdlp(self, timeout=30): self.updated += 1; return True

def run_until_idle(q, timeout=5):
    deadline = threading.Event()
    for _ in range(int(timeout * 20)):
        if all(j.state in ("done", "failed", "cancelled") for j in q.list()): return
        deadline.wait(0.05)
    raise AssertionError("queue did not drain")

def drain(events):
    return [events.get_nowait() for _ in range(events.qsize())]

AUDIO_ALL = {"audio": {"versions": ["original", "instrumental", "vocals"]}}

@pytest.fixture
def q(tmp_path):
    q = JobQueue(tmp_path, backend=FakeBackend()); q.start(); yield q; q.stop()

def test_mp3_job_completes_with_steps(q, tmp_path):
    events = q.subscribe()
    job = q.add("https://youtu.be/a", "mp3")
    run_until_idle(q)
    assert job.state == "done" and job.result_path == str(tmp_path / "Same Title.mp3")
    seen = drain(events)
    assert [e["step_name"] for e in seen if e["state"] == "running"][:2] == ["取得資訊", "下載"]
    assert any(e["percent"] == 50.0 for e in seen)
    assert job.steps == ["取得資訊", "下載", "轉檔"] and job.step_total == 3

def test_same_title_twice_gets_suffix(q, tmp_path):
    q.add("https://youtu.be/a", "mp3"); q.add("https://youtu.be/b", "mp3")
    run_until_idle(q)
    paths = sorted(j.result_path for j in q.list())
    assert paths == [str(tmp_path / "Same Title (1).mp3"), str(tmp_path / "Same Title.mp3")]

def test_no_vocals_removes_wav(q, tmp_path):
    events = q.subscribe()
    job = q.add("https://youtu.be/a", "no_vocals", filename="song")
    run_until_idle(q)
    seen = drain(events)
    assert any(e["step"] == 4 and e["step_name"] == "分離" and e["percent"] == 50.0 for e in seen)
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
    # #27：自動更新後仍失敗是獨立的 error_kind，前端據此顯示「更新」鈕，不比對中文訊息
    assert job.message == "下載工具更新後仍無法下載"
    assert job.error_kind == "update_failed"
    assert job.to_dict()["error_kind"] == "update_failed"
    assert job.detail == "Unable to extract title"
    assert job.step == 1 and job.step_name == "取得資訊"  # 失敗停在哪一步
    assert [o.state for o in job.outputs] == ["failed"]

def test_display_name_is_resolved_title(q):
    job = q.add("https://youtu.be/a", "mp3", filename=None)
    assert job.to_dict()["display_name"] is None
    run_until_idle(q)
    assert job.display_name == "Same Title"

def test_title_is_fetched_even_with_custom_filename(q):
    job = q.add("https://youtu.be/a", "mp3", filename="custom")
    run_until_idle(q)
    assert job.title == "Same Title" and job.display_name == "custom"

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


# ---- 多輸出 ----

def test_all_versions_download_once_and_separate_once(q, tmp_path):
    job = q.add("https://youtu.be/a", {"audio": {"versions": ["vocals", "original", "instrumental"]}}, filename="song")
    run_until_idle(q)
    assert job.state == "done"
    kinds = [c[0] for c in q.backend.calls]
    assert kinds == ["download_audio", "convert_audio", "separate"]
    assert q.backend.calls[0] == ("download_audio", "wav")
    assert q.backend.calls[1] == ("convert_audio", "mp3")
    assert q.backend.calls[2] == ("separate", "htdemucs_ft", ("instrumental", "vocals"), "mp3")
    # 版本依固定順序排列，各自有結果路徑與大小
    assert [o.kind for o in job.outputs] == ["original", "instrumental", "vocals"]
    assert [o.state for o in job.outputs] == ["done"] * 3
    assert [o.filename for o in job.outputs] == ["song.mp3", "song_no_vocals.mp3", "song_vocals.mp3"]
    assert [o.size_bytes for o in job.outputs] == [5, 3, 3]
    assert not (tmp_path / "song.wav").exists()
    assert job.steps == ["取得資訊", "下載", "轉檔", "分離"]

def test_original_wav_with_separation_keeps_wav(q, tmp_path):
    job = q.add("https://youtu.be/a", {"audio": {"versions": ["original", "instrumental"], "format": "wav"}}, filename="song")
    run_until_idle(q)
    assert [c[0] for c in q.backend.calls] == ["download_audio", "separate"]
    assert (tmp_path / "song.wav").exists()
    assert [o.filename for o in job.outputs] == ["song.wav", "song_no_vocals.wav"]

def test_m4a_stems_stay_m4a(q, tmp_path):
    job = q.add("https://youtu.be/a", {"audio": {"versions": ["original", "vocals"], "format": "m4a", "model": "htdemucs"}}, filename="song")
    run_until_idle(q)
    assert [o.filename for o in job.outputs] == ["song.m4a", "song_vocals.m4a"]
    assert [o.ext for o in job.outputs] == ["m4a", "m4a"]
    assert q.backend.calls[-1] == ("separate", "htdemucs", ("vocals",), "m4a")

def test_audio_and_video_steps_and_output_states(q, tmp_path):
    events = q.subscribe()
    job = q.add("https://youtu.be/a", {"audio": {"versions": ["original"]}, "video": {"max_height": 720}}, filename="song")
    run_until_idle(q)
    assert job.steps == ["取得資訊", "下載", "轉檔", "下載影片", "合併"]
    assert ("download_video", 720) in q.backend.calls
    seen = drain(events)
    # 原曲完成時影片還在排隊；影片第二次 finished 不會把步驟推過頭
    snap = next(e for e in seen if e["outputs"][0]["state"] == "done" and e["outputs"][1]["state"] == "queued")
    assert snap["step_name"] == "轉檔"
    assert max(e["step"] for e in seen) == 5
    assert [o["state"] for o in job.to_dict()["outputs"]] == ["done", "done"]

def test_video_only_steps(q):
    job = q.add("https://youtu.be/a", {"video": {}}, filename="v")
    run_until_idle(q)
    assert job.steps == ["取得資訊", "下載", "合併"] and job.state == "done"
    assert job.to_dict()["options"] == {"audio": None, "video": {"max_height": None}}

def test_failure_marks_unfinished_outputs_failed_and_keeps_step(q, tmp_path):
    class Broken(FakeBackend):
        def separate(self, *a, **k):
            raise RuntimeError("boom")
    q.backend = Broken()
    job = q.add("https://youtu.be/a", AUDIO_ALL, filename="song")
    run_until_idle(q)
    assert job.state == "failed" and job.step_name == "分離" and job.step == 4
    assert [o.state for o in job.outputs] == ["done", "failed", "failed"]
    assert job.result_path == str(tmp_path / "song.mp3")
    assert not (tmp_path / "song.wav").exists()
    assert job.finished_at is not None and job.eta_seconds is None

def test_queue_position_and_timing(tmp_path):
    gate = threading.Event()

    class Slow(FakeBackend):
        def download_audio(self, *a, **k):
            gate.wait(5)
            return super().download_audio(*a, **k)

    q = JobQueue(tmp_path, backend=Slow()); events = q.subscribe()
    a = q.add("https://youtu.be/a", "mp3", filename="a")
    b = q.add("https://youtu.be/b", "mp3", filename="b")
    c = q.add("https://youtu.be/c", "mp3", filename="c")
    assert [j.queue_position for j in (a, b, c)] == [1, 2, 3]
    assert a.started_at is None and a.to_dict()["elapsed_seconds"] is None
    q.start()
    for _ in range(100):
        if a.state == "running": break
        threading.Event().wait(0.02)
    assert a.queue_position is None and (b.queue_position, c.queue_position) == (1, 2)
    seen = drain(events)
    assert any(e["id"] == b.id and e["queue_position"] == 1 for e in seen)  # 順位變了也會推送
    assert a.started_at is not None and a.to_dict()["elapsed_seconds"] >= 0
    gate.set(); run_until_idle(q); q.stop()
    assert all(j.queue_position is None for j in (a, b, c))
    assert a.finished_at >= a.started_at and a.to_dict()["elapsed_seconds"] >= 0

def test_eta_estimated_from_step_progress(q):
    events = q.subscribe()
    q.add("https://youtu.be/a", "mp3", filename="a")
    run_until_idle(q)
    seen = drain(events)
    at_half = next(e for e in seen if e["percent"] == 50.0)
    assert at_half["eta_seconds"] is not None and at_half["eta_seconds"] >= 0
    assert seen[-1]["state"] == "done" and seen[-1]["eta_seconds"] is None and seen[-1]["percent"] == 100.0

def test_retry_reuses_options(q):
    job = q.add("https://youtu.be/a", {"audio": {"versions": ["instrumental"], "model": "htdemucs"}, "video": {}}, filename="x")
    run_until_idle(q)
    again = q.retry(job.id)
    run_until_idle(q)
    assert again.options == job.options and again.state == "done"

def test_job_dict_schema(q):
    job = q.add("https://youtu.be/a", AUDIO_ALL, filename="song")
    d = job.to_dict()
    assert set(d) == {"id", "url", "filename", "overwrite", "options", "outputs", "steps", "state", "step", "step_total",
                      "step_name", "percent", "message", "detail", "error_kind", "result_path", "title", "display_name",
                      "queue_position", "created_at", "started_at", "finished_at", "elapsed_seconds", "eta_seconds"}
    assert set(d["outputs"][0]) == {"kind", "ext", "state", "filename", "result_path", "size_bytes"}
    assert d["options"]["audio"] == {"versions": ["original", "instrumental", "vocals"], "format": "mp3", "model": "htdemucs_ft"}

def test_add_rejects_invalid_options(q):
    with pytest.raises(ValueError):
        q.add("https://youtu.be/a", {})
    with pytest.raises(ValueError):
        q.add("https://youtu.be/a", {"audio": {"versions": []}})
    with pytest.raises(ValueError):
        q.add("https://youtu.be/a", "flac")


# ---- 取消 ----

def test_cancel_queued_job_renumbers_and_worker_skips_it(tmp_path):
    gate = threading.Event()

    class Slow(FakeBackend):
        def download_audio(self, *a, **k):
            gate.wait(5)
            return super().download_audio(*a, **k)

    q = JobQueue(tmp_path, backend=Slow()); events = q.subscribe()
    a = q.add("https://youtu.be/a", "mp3", filename="a")
    b = q.add("https://youtu.be/b", "mp3", filename="b")
    c = q.add("https://youtu.be/c", "mp3", filename="c")
    q.start()
    for _ in range(100):
        if a.state == "running": break
        threading.Event().wait(0.02)
    drain(events)
    cancelled = q.cancel(b.id)
    assert cancelled is b and b.state == "cancelled" and b.queue_position is None
    assert b.finished_at is not None and b.started_at is None and b.to_dict()["elapsed_seconds"] is None
    assert c.queue_position == 1  # 後面的工作往前補
    seen = drain(events)
    assert any(e["id"] == b.id and e["state"] == "cancelled" for e in seen)
    assert any(e["id"] == c.id and e["queue_position"] == 1 for e in seen)
    # 執行中的不能取消；取消過的也不能再取消
    with pytest.raises(ValueError, match="只能取消排隊中的工作"):
        q.cancel(a.id)
    with pytest.raises(ValueError):
        q.cancel(b.id)
    with pytest.raises(KeyError):
        q.cancel("nope")
    gate.set(); run_until_idle(q); q.stop()
    assert (a.state, b.state, c.state) == ("done", "cancelled", "done")
    assert [x[0] for x in q.backend.calls].count("download_audio") == 2  # b 沒有被跑

def test_cancel_before_worker_starts_is_never_run(tmp_path):
    q = JobQueue(tmp_path, backend=FakeBackend())
    job = q.add("https://youtu.be/a", "mp3", filename="a")
    q.cancel(job.id)
    q.start(); run_until_idle(q); q.stop()
    assert job.state == "cancelled" and q.backend.calls == []
    assert [o.state for o in job.outputs] == ["queued"]

def test_retry_cancelled_job_creates_new_queued_job(q):
    q.stop()
    job = q.add("https://youtu.be/a", "mp3", filename="a")
    q.cancel(job.id)
    again = q.retry(job.id)
    assert again.id != job.id and again.state == "queued" and again.queue_position == 1
