"""yt-dlp 錯誤訊息的中文對照。"""
import re

KINDS = ("private", "age", "unavailable", "live", "extractor_outdated", "network", "unknown")


class VidSnatchError(Exception):
    def __init__(self, kind: str, message: str, detail: str = ""):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.detail = detail


# 由上到下，第一個命中者勝；比對忽略大小寫
_RULES = [
    (r"private video", "private", "這是私人影片，無法下載"),
    (r"confirm your age|age[- ]restricted|inappropriate for some users",
     "age", "這部影片有年齡限制，無法下載"),
    (r"video unavailable|no longer available|has been removed|not available|does not exist",
     "unavailable", "影片不存在或已被移除"),
    (r"live event will begin|premieres in|is live|this live stream",
     "live", "直播尚未結束，請結束後再試"),
    (r"unable to extract|http error 403|http error 410|sign in to confirm you.re not a bot",
     "extractor_outdated", "YouTube 改版，正在自動更新下載工具…"),
    (r"getaddrinfo|timed out|timeout|connection (?:reset|refused|aborted|error)|"
     r"network is unreachable|name or service not known|temporary failure in name resolution|"
     r"nodename nor servname|urlopen error",
     "network", "無法連線，請檢查網路"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), k, m) for p, k, m in _RULES]


def translate(exc: BaseException) -> VidSnatchError:
    if isinstance(exc, VidSnatchError):
        return exc
    raw = str(exc)
    for rx, kind, message in _COMPILED:
        if rx.search(raw):
            return VidSnatchError(kind, message, raw)
    return VidSnatchError("unknown", "發生未知錯誤", raw)
