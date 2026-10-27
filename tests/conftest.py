import warnings

# starlette 1.10 建議改用 httpx2；在未安裝 httpx2 的環境中，只壓掉這一則棄用警告，
# 讓 `pytest -W error` 能正常收集 TestClient 測試。
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated")
    import starlette.testclient  # noqa: F401
