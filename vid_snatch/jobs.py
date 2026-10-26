"""單 worker 工作佇列：依序執行下載工作，並把狀態變化推給訂閱者。"""
import queue
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from . import core, errors
from .errors import VidSnatchError

MODES = {
    "mp3": ["取得資訊", "下載", "轉檔"],
    "mp4": ["取得資訊", "下載", "合併"],
    "no_vocals": ["取得資訊", "下載", "轉檔", "分離人聲"],
}

_STOP = object()


@dataclass
class Job:
    id: str
    url: str
    mode: str
    filename: str | None
    overwrite: bool
    state: str = "queued"
    step: int = 0
    step_total: int = 0
    step_name: str = ""
    percent: float | None = None
    message: str = ""
    detail: str = ""
    result_path: str | None = None
    error_kind: str | None = None
    display_name: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class Backend(Protocol):
    def fetch_title(self, url: str) -> str: ...
    def download_audio(self, url, output_dir, filename, audio_format="mp3", on_progress=None, *, overwrite=False) -> Path: ...
    def download_video(self, url, output_dir, filename, on_progress=None, *, overwrite=False) -> Path: ...
    def remove_vocals(self, audio_path, output_dir, on_progress=None) -> Path: ...
    def update_ytdlp(self, timeout=30) -> bool: ...


UPDATE_FAILED_MESSAGE = "更新後仍無法下載，請稍後再試"


def _target_names(name: str, mode: str) -> list[str]:
    """這個模式會寫入（並可能刪除）的檔名；no_vocals 過程中會產生並刪除 <name>.wav。"""
    if mode == "no_vocals":
        return [f"{name}_no_vocals.mp3", f"{name}.wav"]
    return [f"{name}.{mode}"]


class JobQueue:
    def __init__(self, output_dir: Path, backend: Backend = core):
        self.output_dir = Path(output_dir)
        self.backend = backend
        self._jobs: dict[str, Job] = {}
        self._pending: queue.Queue = queue.Queue()
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    # ---- 公開 API ----
    def add(self, url: str, mode: str, filename: str | None = None, overwrite: bool = False) -> Job:
        if mode not in MODES:
            raise ValueError(f"未知模式：{mode}")
        job = Job(uuid4().hex[:8], url, mode, filename, overwrite, step_total=len(MODES[mode]))
        with self._lock:
            self._jobs[job.id] = job
            self._emit(job)
        self._pending.put(job.id)
        return job

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def retry(self, job_id: str) -> Job:
        old = self.get(job_id)
        if old is None:
            raise KeyError(job_id)
        return self.add(old.url, old.mode, old.filename, old.overwrite)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="vid-snatch-worker")
        self._thread.start()

    def stop(self) -> None:
        if self._thread:
            self._stopping.set()
            self._pending.put(_STOP)
            self._thread.join(timeout=5)
            if not self._thread.is_alive():
                self._thread = None

    def exists(self, filename: str, mode: str) -> tuple[bool, str]:
        name = core.sanitize_filename(filename)
        base = self._unique_base(name, mode)
        return base != name, base

    # ---- 內部 ----
    def _unique_base(self, name: str, mode: str) -> str:
        candidate, n = name, 0
        while any((self.output_dir / t).exists() for t in _target_names(candidate, mode)):
            n += 1
            candidate = f"{name} ({n})"
        return candidate

    def _emit(self, job: Job) -> None:
        with self._lock:
            data = job.to_dict()
            for q in self._subscribers:
                q.put_nowait(dict(data))

    def _update(self, job: Job, **fields) -> None:
        with self._lock:
            for k, v in fields.items():
                setattr(job, k, v)
            self._emit(job)

    def _set_step(self, job: Job, step: int) -> None:
        self._update(job, step=step, step_name=MODES[job.mode][step - 1], percent=None)

    def _worker(self) -> None:
        while True:
            job_id = self._pending.get()
            if self._stopping.is_set():
                return
            if job_id is _STOP:
                continue
            job = self.get(job_id)
            if job is None:
                continue
            try:
                self._run(job)
            except Exception as e:  # 任何例外都只讓該工作失敗，不讓 worker 死掉
                err = errors.translate(e)
                self._update(job, state="failed", message=err.message, detail=err.detail, error_kind=err.kind)

    def _run(self, job: Job) -> None:
        try:
            path = self._attempt(job)
        except VidSnatchError as e:
            if e.kind != "extractor_outdated":
                raise
            self.backend.update_ytdlp()
            try:
                path = self._attempt(job)
            except VidSnatchError as e2:
                if e2.kind != "extractor_outdated":
                    raise
                raise VidSnatchError("extractor_outdated", UPDATE_FAILED_MESSAGE, e2.detail) from e2

        self._update(job, state="done", step=job.step_total, step_name=MODES[job.mode][-1],
                     percent=100.0, result_path=str(path), message="", detail="", error_kind=None)

    def _attempt(self, job: Job) -> Path:
        """取得檔名並下載；YouTube 改版時整段（含取標題）會在更新 yt-dlp 後重跑一次。"""
        self._update(job, state="running", step=1, step_name=MODES[job.mode][0], percent=None)
        name = core.sanitize_filename(job.filename if job.filename else self.backend.fetch_title(job.url))
        if not job.overwrite:
            name = self._unique_base(name, job.mode)
        with self._lock:
            job.display_name = name  # 隨下一個步驟事件一起送出
        return self._download(job, name)

    def _download(self, job: Job, name: str) -> Path:
        b = self.backend
        self._set_step(job, 2)

        def on_progress(p: float | None) -> None:
            with self._lock:
                if p is None and job.step == 2:
                    self._set_step(job, 3)
                elif p is not None:
                    self._update(job, percent=p)

        if job.mode == "mp3":
            return b.download_audio(job.url, self.output_dir, name, "mp3", on_progress, overwrite=job.overwrite)
        if job.mode == "mp4":
            return b.download_video(job.url, self.output_dir, name, on_progress, overwrite=job.overwrite)
        wav = b.download_audio(job.url, self.output_dir, name, "wav", on_progress, overwrite=job.overwrite)
        try:
            self._set_step(job, 4)
            return b.remove_vocals(wav, self.output_dir, on_progress)
        finally:
            Path(wav).unlink(missing_ok=True)
