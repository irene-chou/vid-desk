"""宿主端動作佇列與心跳。

容器無法自行開 Finder、選資料夾或關閉自己，由宿主端啟動腳本輪詢
`GET /api/host-actions` 取得動作並執行；輪詢同時作為心跳。
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Callable


class _Action:
    def __init__(self, action_id: str, kind: str, payload: dict) -> None:
        self.id = action_id
        self.kind = kind
        self.payload = payload
        self.sent = False
        self.result: dict | None = None
        self.event = threading.Event()


class HostActionQueue:
    def __init__(
        self, started_at: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._started_at = started_at
        self._clock = clock
        self._lock = threading.Lock()
        self._actions: dict[str, _Action] = {}
        self.last_heartbeat: float | None = None

    def push(self, kind: str, payload: dict | None = None) -> str:
        action = _Action(uuid.uuid4().hex, kind, dict(payload or {}))
        with self._lock:
            self._actions[action.id] = action
        return action.id

    def poll(self) -> list[dict]:
        with self._lock:
            self.last_heartbeat = self._clock()
            out = []
            for a in self._actions.values():
                if not a.sent:
                    a.sent = True
                    out.append({"id": a.id, "kind": a.kind, "payload": a.payload})
            return out

    def set_result(self, action_id: str, result: dict | None) -> None:
        with self._lock:
            action = self._actions.get(action_id)
        if action is None:
            return
        action.result = result
        action.event.set()

    def wait_result(self, action_id: str, timeout: float) -> dict | None:
        with self._lock:
            action = self._actions.get(action_id)
        if action is None:
            time.sleep(max(0.0, timeout))
            return None
        if not action.event.wait(timeout):
            return None
        return action.result

    def heartbeat_lost(
        self, now: float, grace: float = 60, limit: float = 15
    ) -> bool:
        if now - self._started_at < grace:
            return False
        last = self.last_heartbeat
        return last is None or now - last > limit
