"""Dockerfile 層次順序（issue #36）：會隨版本變動的檔案只能在最重的層（相依套件、模型）之後才 COPY。

0.3.1 → 0.3.2 曾因為 `COPY pyproject.toml` 放在 pip install 之前，只改版本號就讓 Mac 重抓約 670 MB。
"""
from pathlib import Path
import re

ROOT = Path(__file__).parent.parent
DOCKERFILE = ROOT / "Dockerfile"

# 只改版本號就會變的檔案；pip install 相依套件與下載模型都不需要它們
VERSIONED = {"pyproject.toml", "vid_snatch/__init__.py"}
# 重的層之前唯一允許 COPY 的來源：預載模型用的獨立腳本
ALLOWED_BEFORE_HEAVY = {"vid_snatch/models.py"}


def instructions():
    text = DOCKERFILE.read_text(encoding="utf-8")
    text = re.sub(r"\\\n", " ", text)  # 併回續行
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, rest = line.partition(" ")
        out.append((name.upper(), rest.strip()))
    return out


def copy_sources(args):
    parts = args.split()
    parts = [p for p in parts if not p.startswith("--")]
    return parts[:-1]  # 最後一個是目的地


def is_heavy(name, args):
    if name != "RUN":
        return False
    installs_deps = "pip install" in args and "--no-deps" not in args
    downloads_models = "models.py" in args
    return installs_deps or downloads_models


def covers(source, path):
    source = source.rstrip("/")
    return path == source or path.startswith(source + "/")


def test_no_versioned_file_is_copied_before_heavy_layers():
    ins = instructions()
    last_heavy = max(i for i, (n, a) in enumerate(ins) if is_heavy(n, a))
    for name, args in ins[:last_heavy]:
        if name != "COPY":
            continue
        for src in copy_sources(args):
            assert src in ALLOWED_BEFORE_HEAVY, f"重的層之前不該 COPY {src}（改版本號會讓相依套件／模型層全部重建）"
            for v in VERSIONED:
                assert not covers(src, v), f"COPY {src} 會把 {v} 帶進重的層之前"


def test_models_preload_only_needs_models_py():
    # 預載模型的那層只依賴 vid_snatch/models.py 本身，不能 import 整個套件（否則 __init__ 的版本號會牽動它）
    ins = instructions()
    models_copy = next(a for n, a in ins if n == "COPY" and "models.py" in a)
    assert copy_sources(models_copy) == ["vid_snatch/models.py"]
    assert "/tmp/models.py" in models_copy
    src = (ROOT / "vid_snatch/models.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+vid_snatch", src, re.M)
    assert not re.search(r"^\s*from\s+\.", src, re.M)


def test_versioned_files_are_copied_last_and_package_installed_without_deps():
    ins = instructions()
    last_heavy = max(i for i, (n, a) in enumerate(ins) if is_heavy(n, a))
    tail = ins[last_heavy + 1 :]
    copies = [copy_sources(a) for n, a in tail if n == "COPY"]
    assert ["pyproject.toml"] in copies, "pip install . 需要 pyproject.toml，要在重的層之後 COPY"
    assert any(covers(src, "vid_snatch/__init__.py") for c in copies for src in c)
    runs = [a for n, a in tail if n == "RUN"]
    assert runs == ["pip install --no-cache-dir --no-deps ."]
    # 之後的層不再抓任何套件
    for a in runs:
        assert "--index-url" not in a and "torch" not in a


def test_package_script_ships_everything_the_local_build_fallback_needs():
    script = (ROOT / "scripts/build-package.sh").read_text(encoding="utf-8")
    assert '"$WORK/src/Dockerfile" "$WORK/src/pyproject.toml" "$PKG/files/"' in script
    assert 'cp -R "$WORK/src/vid_snatch" "$PKG/files/vid_snatch"' in script
