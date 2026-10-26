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

INDEX_HTML = Path(__file__).parent / "static" / "index.html"


class JobsIn(BaseModel):
    urls: list[str]
    mode: Literal["mp3", "no_vocals", "mp4"]
    filename: str | None = None
    overwrite: bool = False


class SettingsIn(BaseModel):
    output_dir: str


class UninstallIn(BaseModel):
    delete_downloads: bool = False


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
        if request.method == "POST" and request.headers.get("X-Vid-Snatch") != "1":
            return _error(403, "forbidden")
        return await call_next(request)

    @app.get("/")
    def index():
        return FileResponse(INDEX_HTML)

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
    def exists(filename: str, mode: str):
        found, suggestion = queue.exists(filename, mode)
        return {"exists": found, "suggestion": suggestion}

    @app.post("/api/jobs")
    def create_jobs(body: JobsIn):
        urls = []
        for i, raw in enumerate(body.urls, start=1):
            cleaned = core.clean_url(raw)
            if cleaned is None:
                return _error(400, f"第 {i} 行不是 YouTube 網址")
            urls.append(cleaned)
        filename = body.filename if len(urls) == 1 else None
        jobs = [queue.add(u, body.mode, filename, body.overwrite) for u in urls]
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

    @app.get("/api/settings")
    def get_settings():
        return {"output_dir": host_output_dir}

    @app.post("/api/settings")
    def set_settings(body: SettingsIn):
        if not body.output_dir.strip():
            return _error(400, "請輸入下載資料夾")
        config.write_output_dir(config_dir, body.output_dir)
        return {"output_dir": body.output_dir, "restart_required": True}

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
