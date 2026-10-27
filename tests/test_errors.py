import pytest
from vid_snatch.errors import VidSnatchError, translate

@pytest.mark.parametrize("raw,kind,message", [
    ("ERROR: [youtube] abc: Private video. Sign in", "private", "這是私人影片，無法下載"),
    ("Sign in to confirm your age", "age", "這部影片有年齡限制，無法下載"),
    ("ERROR: Video unavailable", "unavailable", "影片不存在或已被移除"),
    ("This live event will begin in 2 hours", "live", "直播尚未結束，請結束後再試"),
    ("Unable to extract uploader id", "extractor_outdated", "YouTube 改版，正在自動更新下載工具…"),
    ("HTTP Error 403: Forbidden", "extractor_outdated", "YouTube 改版，正在自動更新下載工具…"),
    ("[Errno 8] nodename nor servname provided: getaddrinfo failed", "network", "無法連線，請檢查網路"),
    ("The read operation timed out", "network", "無法連線，請檢查網路"),
    ("something weird", "unknown", "發生未知錯誤"),
])
def test_translate(raw, kind, message):
    err = translate(RuntimeError(raw))
    assert isinstance(err, VidSnatchError)
    assert err.kind == kind
    assert err.message == message
    assert err.detail == raw

def test_translate_passthrough():
    e = VidSnatchError("network", "無法連線，請檢查網路", "x")
    assert translate(e) is e

def test_bot_check_is_unknown():
    assert translate(RuntimeError("Sign in to confirm you're not a bot")).kind == "unknown"

def test_kinds_include_update_failed():
    # #27：自動更新 yt-dlp 後仍失敗的工作用這個 kind；translate 不會產生它（只由 jobs 的重試流程丟出）
    from vid_snatch.errors import KINDS
    assert "update_failed" in KINDS
    assert all(translate(RuntimeError(raw)).kind != "update_failed" for raw in ("HTTP Error 403", "x"))
