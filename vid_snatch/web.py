"""FastAPI 後端：把工作佇列、宿主端動作與設定接成 HTTP API。"""
import asyncio
import json
import queue as queue_mod
from pathlib import Path
from typing import Callable, Literal

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import __version__, config, core
from .errors import VidSnatchError
from .hostactions import HostActionQueue
from .jobs import JobQueue
from .outputs import OutputOptions

INDEX_HTML = Path(__file__).parent / "static" / "index.html"

AudioFormat = Literal["mp3", "m4a", "wav", "flac"]
Bitrate = Literal[128, 192, 320]
DemucsModel = Literal["htdemucs", "htdemucs_ft"]
MaxHeight = Literal[1080, 720]


class AudioIn(BaseModel):
    versions: list[Literal["original", "instrumental", "vocals"]]
    format: AudioFormat = "mp3"
    bitrate: Bitrate = 192
    model: DemucsModel = "htdemucs_ft"


class VideoIn(BaseModel):
    max_height: MaxHeight | None = None


class OutputsIn(BaseModel):
    audio: AudioIn | None = None
    video: VideoIn | None = None


class JobsIn(BaseModel):
    urls: list[str]
    outputs: OutputsIn
    filename: str | None = None
    overwrite: bool = False
    filenames: list[str | None] | None = None
    overwrites: list[bool] | None = None


class SettingsIn(BaseModel):
    """沒給的欄位維持原值；video_max_height 給 null 表示不限畫質。"""
    output_dir: str | None = None
    audio_format: AudioFormat | None = None
    audio_bitrate: Bitrate | None = None
    demucs_model: DemucsModel | None = None
    video_max_height: MaxHeight | None = None


class UninstallIn(BaseModel):
    delete_downloads: bool = False


ALLOWED_HOSTS = {"localhost", "127.0.0.1"}


def _host_allowed(host: str | None) -> bool:
    """只接受 localhost / 127.0.0.1（去掉埠號），擋 DNS rebinding。"""
    if not host:
        return False
    name, sep, port = host.rpartition(":")
    if not sep or not port.isdigit():
        name = host
    return name.lower() in ALLOWED_HOSTS


def _error(status: int, message: str, **extra) -> JSONResponse:
    return JSONResponse({"message": message, **extra}, status_code=status)


def create_app(
    output_dir: Path,
    config_dir: Path,
    host_output_dir: str,
    queue: JobQueue,
    host_actions: HostActionQueue,
    on_shutdown: Callable[[], None],
) -> FastAPI:
    app = FastAPI()
    sep = "\\" if "\\" in host_output_dir else "/"

    @app.middleware("http")
    async def require_header(request: Request, call_next):
        if not _host_allowed(request.headers.get("host")):
            return _error(403, "forbidden")
        if request.method in ("POST", "DELETE") and request.headers.get("X-Vid-Snatch") != "1":
            return _error(403, "forbidden")
        return await call_next(request)

    @app.get("/")
    def index():
        # 更新後瀏覽器不能沿用舊頁面
        return FileResponse(INDEX_HTML, headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/info")
    async def info(url: str):
        cleaned = core.clean_url(url)
        if cleaned is None:
            return _error(400, "這不是 YouTube 影片網址")
        try:
            title = await asyncio.to_thread(core.fetch_title, cleaned)
        except VidSnatchError as e:
            return _error(400, e.message, detail=e.detail, kind=e.kind)
        return {"title": title}

    @app.get("/api/exists")
    def exists(filename: str, versions: str = "", format: str = "mp3", video: bool = False):
        """versions 以逗號分隔（original,instrumental,vocals）；不勾音檔就留空。"""
        spec: dict = {}
        if versions.strip():
            spec["audio"] = {"versions": [v.strip() for v in versions.split(",") if v.strip()], "format": format}
        if video:
            spec["video"] = {}
        try:
            options = OutputOptions.from_dict(spec)
        except ValueError as e:
            return _error(400, str(e))
        found, suggestion = queue.exists(filename, options)
        return {"exists": found, "suggestion": suggestion,
                "files": [options.filename(suggestion, o.kind) for o in options.outputs()]}

    @app.post("/api/jobs")
    def create_jobs(body: JobsIn):
        try:
            options = OutputOptions.from_dict(body.outputs.model_dump())
        except ValueError as e:
            return _error(400, str(e))
        urls = []
        for i, raw in enumerate(body.urls, start=1):
            cleaned = core.clean_url(raw)
            if cleaned is None:
                return _error(400, f"第 {i} 行不是 YouTube 網址")
            urls.append(cleaned)
        n = len(urls)
        if body.filenames is not None and len(body.filenames) != n:
            return _error(400, "檔名數量和網址數量不一致")
        if body.overwrites is not None and len(body.overwrites) != n:
            return _error(400, "檔名數量和網址數量不一致")
        filenames = body.filenames or ([body.filename] if n == 1 else [None] * n)
        overwrites = body.overwrites or [body.overwrite] * n
        jobs = [queue.add(u, options, (f or "").strip() or None, o)
                for u, f, o in zip(urls, filenames, overwrites)]
        return {"jobs": [j.to_dict() for j in jobs]}

    @app.get("/api/jobs")
    def list_jobs():
        return {"jobs": [j.to_dict() for j in queue.list()]}

    @app.post("/api/jobs/{job_id}/retry")
    def retry_job(job_id: str):
        try:
            return queue.retry(job_id).to_dict()
        except KeyError:
            return _error(404, "找不到這個工作")

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(job_id: str):
        """取消排隊中的工作；只對 queued 生效，其他狀態回 409。"""
        try:
            return queue.cancel(job_id).to_dict()
        except KeyError:
            return _error(404, "找不到這個工作")
        except ValueError as e:
            return _error(409, str(e))

    @app.post("/api/jobs/{job_id}/reveal")
    def reveal_job(job_id: str):
        job = queue.get(job_id)
        if job is None:
            return _error(404, "找不到這個工作")
        if job.state != "done" or not job.result_path:
            return _error(409, "工作尚未完成")
        host_actions.push("reveal", {"path": host_output_dir + sep + Path(job.result_path).name})
        return {"ok": True}

    @app.get("/api/events")
    async def events(request: Request):
        async def stream():
            q = queue.subscribe()
            try:
                for job in queue.list():
                    yield {"event": "job", "data": json.dumps(job.to_dict())}
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.to_thread(q.get, True, 1.0)
                    except queue_mod.Empty:
                        continue
                    yield {"event": "job", "data": json.dumps(item)}
            finally:
                queue.unsubscribe(q)

        return EventSourceResponse(stream(), ping=15)

    def _settings(output_dir: str) -> dict:
        return {"output_dir": output_dir, **config.read_settings(config_dir)}

    @app.get("/api/settings")
    def get_settings():
        return _settings(host_output_dir)

    @app.post("/api/settings")
    def set_settings(body: SettingsIn):
        given = body.model_fields_set
        restart = False
        if "output_dir" in given:
            if not (body.output_dir or "").strip():
                return _error(400, "請輸入下載資料夾")
            config.write_output_dir(config_dir, body.output_dir)
            restart = True
        details = {k: getattr(body, k) for k in config.DEFAULT_SETTINGS if k in given}
        config.write_settings(config_dir, details)
        return {**_settings(body.output_dir if restart else host_output_dir), "restart_required": restart}

    @app.post("/api/settings/pick-folder")
    async def pick_folder():
        action_id = host_actions.push("pick_folder")
        result = await asyncio.to_thread(host_actions.wait_result, action_id, 120)
        path = (result or {}).get("path")
        if not path:
            return {"output_dir": host_output_dir, "changed": False}
        config.write_output_dir(config_dir, path)
        return {"output_dir": path, "changed": True, "restart_required": True}

    @app.post("/api/shutdown")
    def shutdown():
        host_actions.push("shutdown")
        on_shutdown()
        return {"ok": True}

    @app.post("/api/rebuild")
    def rebuild():
        host_actions.push("rebuild")
        return {"ok": True}

    @app.post("/api/uninstall")
    def uninstall(body: UninstallIn):
        host_actions.push("uninstall", {"delete_downloads": body.delete_downloads})
        return {"ok": True}

    @app.get("/api/host-actions")
    def poll_host_actions():
        return {"actions": host_actions.poll()}

    @app.post("/api/host-actions/{action_id}/result")
    async def host_action_result(action_id: str, request: Request):
        host_actions.set_result(action_id, await request.json())
        return {"ok": True}

    return app
