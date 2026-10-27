"""單 worker 工作佇列：依序執行下載工作，並把狀態變化推給訂閱者。"""
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from . import core, errors, outputs
from .errors import VidSnatchError
from .outputs import Backend, Hooks, Output, OutputOptions

JOB_STATES = ("queued", "running", "done", "failed", "cancelled")
CANCEL_ONLY_QUEUED_MESSAGE = "只能取消排隊中的工作"

_STOP = object()


@dataclass
class Job:
    id: str
    url: str
    options: OutputOptions
    filename: str | None
    overwrite: bool
    outputs: list[Output] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    state: str = "queued"
    step: int = 0
    step_name: str = ""
    percent: float | None = None
    message: str = ""
    detail: str = ""
    error_kind: str | None = None
    title: str | None = None          # YouTube 原標題
    display_name: str | None = None   # 實際使用的檔名主體（不含副檔名）
    queue_position: int | None = None  # 排隊中的順位（1 = 下一個），非排隊時為 None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    eta_seconds: float | None = None
    _step_started: float | None = field(default=None, repr=False, compare=False)

    @property
    def step_total(self) -> int:
        return len(self.steps)

    @property
    def result_path(self) -> str | None:
        """第一個完成的輸出路徑（「顯示檔案」用）。"""
        return next((o.result_path for o in self.outputs if o.state == "done" and o.result_path), None)

    def elapsed_seconds(self) -> float | None:
        if self.started_at is None:
            return None
        return round((self.finished_at or time.time()) - self.started_at, 1)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "filename": self.filename,
            "overwrite": self.overwrite,
            "options": self.options.to_dict(),
            "outputs": [o.to_dict() for o in self.outputs],
            "steps": list(self.steps),
            "state": self.state,
            "step": self.step,
            "step_total": self.step_total,
            "step_name": self.step_name,
            "percent": self.percent,
            "message": self.message,
            "detail": self.detail,
            "error_kind": self.error_kind,
            "result_path": self.result_path,
            "title": self.title,
            "display_name": self.display_name,
            "queue_position": self.queue_position,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": self.elapsed_seconds(),
            "eta_seconds": self.eta_seconds,
        }


UPDATE_FAILED_MESSAGE = "更新後仍無法下載，請稍後再試"


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
    def add(self, url: str, options: OutputOptions | dict | str, filename: str | None = None,
            overwrite: bool = False) -> Job:
        """options 可以是 OutputOptions、API 的 outputs dict，或舊的模式字串（mp3 / mp4 / no_vocals）。"""
        if isinstance(options, str):
            options = OutputOptions.from_mode(options)
        elif isinstance(options, dict):
            options = OutputOptions.from_dict(options)
        job = Job(uuid4().hex[:8], url, options, filename, overwrite,
                  outputs=options.outputs(), steps=options.steps())
        with self._lock:
            self._jobs[job.id] = job
            self._renumber()
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
        return self.add(old.url, old.options, old.filename, old.overwrite)

    def cancel(self, job_id: str) -> Job:
        """取消排隊中的工作；非排隊狀態丟 ValueError。worker 取到已取消的工作會直接跳過。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.state != "queued":
                raise ValueError(CANCEL_ONLY_QUEUED_MESSAGE)
            # state 變了，_update 會重排其他排隊工作的順位並推送
            self._update(job, state="cancelled", finished_at=time.time())
            return job

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

    def exists(self, filename: str, options: OutputOptions | dict | str) -> tuple[bool, str]:
        if isinstance(options, str):
            options = OutputOptions.from_mode(options)
        elif isinstance(options, dict):
            options = OutputOptions.from_dict(options)
        name = core.sanitize_filename(filename)
        base = self._unique_base(name, options)
        return base != name, base

    # ---- 內部 ----
    def _unique_base(self, name: str, options: OutputOptions) -> str:
        return outputs.unique_base(self.output_dir, name, options)

    def _renumber(self) -> "list[Job]":
        """重排排隊中工作的順位，回傳順位有變的工作（呼叫端持有 lock）。"""
        changed = []
        n = 0
        for job in self._jobs.values():
            pos = None
            if job.state == "queued":
                n += 1
                pos = n
            if job.queue_position != pos:
                job.queue_position = pos
                changed.append(job)
        return changed

    def _emit(self, job: Job) -> None:
        with self._lock:
            data = job.to_dict()
            for q in self._subscribers:
                q.put_nowait(dict(data))

    def _update(self, job: Job, **fields) -> None:
        with self._lock:
            for k, v in fields.items():
                setattr(job, k, v)
            if "state" in fields:
                for other in self._renumber():
                    if other is not job:
                        self._emit(other)
            self._emit(job)

    def _set_step(self, job: Job, step: int, **fields) -> None:
        with self._lock:
            job._step_started = time.monotonic()
            self._update(job, step=step, step_name=job.steps[step - 1], percent=None, eta_seconds=None, **fields)

    def _set_percent(self, job: Job, percent: float | None) -> None:
        with self._lock:
            eta = None
            if percent and percent > 0 and job._step_started is not None:
                spent = time.monotonic() - job._step_started
                eta = round(spent * (100 - percent) / percent, 1)
            self._update(job, percent=percent, eta_seconds=eta)

    def _set_output(self, job: Job, kind: str, state: str, path: Path | None) -> None:
        with self._lock:
            for o in job.outputs:
                if o.kind == kind:
                    o.state = state
                    if path is not None:
                        o.result_path = str(path)
                        o.filename = Path(path).name
                        try:
                            o.size_bytes = Path(path).stat().st_size
                        except OSError:
                            o.size_bytes = None
            self._emit(job)

    def _worker(self) -> None:
        while True:
            job_id = self._pending.get()
            if self._stopping.is_set():
                return
            if job_id is _STOP:
                continue
            job = self.get(job_id)
            if job is None or not self._claim(job):
                continue
            try:
                self._run(job)
            except Exception as e:  # 任何例外都只讓該工作失敗，不讓 worker 死掉
                err = errors.translate(e)
                with self._lock:
                    for o in job.outputs:
                        if o.state != "done":
                            o.state = "failed"
                    self._update(job, state="failed", finished_at=time.time(), eta_seconds=None,
                                 message=err.message, detail=err.detail, error_kind=err.kind)

    def _claim(self, job: Job) -> bool:
        """把排隊中的工作標成執行中（已取消的回 False）；順位重排在同一把鎖內完成，之後不能再取消。"""
        with self._lock:
            if job.state != "queued":
                return False
            job.state = "running"
            job.started_at = time.time()  # 隨第 1 步的事件一起送出
            for other in self._renumber():
                if other is not job:
                    self._emit(other)
            return True

    def _run(self, job: Job) -> None:
        try:
            self._attempt(job)
        except VidSnatchError as e:
            if e.kind != "extractor_outdated":
                raise
            self.backend.update_ytdlp()
            try:
                self._attempt(job)
            except VidSnatchError as e2:
                if e2.kind != "extractor_outdated":
                    raise
                raise VidSnatchError("extractor_outdated", UPDATE_FAILED_MESSAGE, e2.detail) from e2

        self._update(job, state="done", step=job.step_total, step_name=job.steps[-1], percent=100.0,
                     finished_at=time.time(), eta_seconds=None, message="", detail="", error_kind=None)

    def _attempt(self, job: Job) -> None:
        """取得標題與檔名並產出所有輸出；YouTube 改版時整段（含取標題）會在更新 yt-dlp 後重跑一次。"""
        with self._lock:
            for o in job.outputs:
                o.state, o.result_path, o.size_bytes = "queued", None, None
        self._set_step(job, 1, state="running")
        title = self.backend.fetch_title(job.url)
        name = core.sanitize_filename(job.filename if job.filename else title)
        if not job.overwrite:
            name = self._unique_base(name, job.options)
        with self._lock:
            job.title = title
            job.display_name = name
            for o in job.outputs:
                o.filename = job.options.filename(name, o.kind)
        hooks = Hooks(
            on_step=lambda i: self._set_step(job, i),
            on_progress=lambda p: self._set_percent(job, p),
            on_output=lambda kind, state, path: self._set_output(job, kind, state, path),
        )
        outputs.execute(job.options, job.url, self.output_dir, name, self.backend,
                        overwrite=job.overwrite, hooks=hooks)
