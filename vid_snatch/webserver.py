"""Run the web UI server (uvicorn) with heartbeat watchdog."""

import os
import threading
import time
from pathlib import Path

import uvicorn

from vid_snatch import core
from vid_snatch.hostactions import HostActionQueue
from vid_snatch.jobs import UPGRADE_MARKER, JobQueue
from vid_snatch.web import create_app


def run_web(port: int) -> None:
    output_dir = os.environ.get("VS_OUTPUT_DIR", "/app/output")
    config_dir = os.environ.get("VS_CONFIG_DIR", "/app/config")
    host_output_dir = os.environ.get("VS_HOST_OUTPUT_DIR", output_dir)
    bind = os.environ.get("VS_BIND", "0.0.0.0")

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 自動更新 yt-dlp 後仍失敗時寫 <config>/upgrade-pending，vid-snatch.ps1 下次啟動據此升級所有相依套件（#31）
    queue = JobQueue(Path(output_dir), upgrade_marker=Path(config_dir) / UPGRADE_MARKER)
    queue.start()
    host_actions = HostActionQueue(started_at=time.monotonic())

    app = create_app(
        output_dir=Path(output_dir),
        config_dir=Path(config_dir),
        host_output_dir=host_output_dir,
        queue=queue,
        host_actions=host_actions,
        on_shutdown=lambda: setattr(server, "should_exit", True),
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host=bind, port=port, log_level="warning")
    )

    def _update() -> None:
        try:
            core.update_ytdlp(timeout=30)
        except Exception:
            pass

    def _watchdog() -> None:
        while not server.should_exit:
            if host_actions.heartbeat_lost(time.monotonic()):
                server.should_exit = True
                return
            time.sleep(1)

    threading.Thread(target=_update, daemon=True).start()
    threading.Thread(target=_watchdog, daemon=True).start()
    try:
        server.run()
    finally:
        queue.stop()
