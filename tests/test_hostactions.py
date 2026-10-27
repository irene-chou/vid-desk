import threading
from vid_snatch.hostactions import HostActionQueue


def test_push_poll_once():
    h = HostActionQueue(started_at=0.0)
    aid = h.push("reveal", {"path": "/x"})
    assert h.poll() == [{"id": aid, "kind": "reveal", "payload": {"path": "/x"}}]
    assert h.poll() == []
    assert h.last_heartbeat is not None


def test_wait_result():
    h = HostActionQueue(started_at=0.0)
    aid = h.push("pick_folder")
    threading.Timer(0.1, lambda: h.set_result(aid, {"path": "/picked"})).start()
    assert h.wait_result(aid, timeout=2) == {"path": "/picked"}
    assert h.wait_result("nope", timeout=0.1) is None


def test_heartbeat_grace_then_limit():
    now = {"t": 1000.0}
    h = HostActionQueue(started_at=1000.0, clock=lambda: now["t"])
    assert h.heartbeat_lost(now=1030.0) is False      # 寬限期內
    assert h.heartbeat_lost(now=1061.0) is True       # 過寬限、從未收到
    now["t"] = 1070.0; h.poll()                        # 收到心跳
    assert h.last_heartbeat == 1070.0
    assert h.heartbeat_lost(now=1080.0) is False
    assert h.heartbeat_lost(now=1086.0) is True
