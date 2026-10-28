"""vid-snatch-Mac.command 的更新檢查（issue #36）：先比對遠端與本機的 digest，有新版才 pull，離線不卡啟動。

以 source 載入 .command 只取函式，再用假的 docker / uname 指令跑 ensure_image，檢查印出的訊息與實際呼叫。
Windows 沒有可靠的 bash，這些測試在 docker-check.yml 的 Linux job 上跑。
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).parent.parent
COMMAND = ROOT / "vid-snatch-Mac.command"
SRC = COMMAND.read_text(encoding="utf-8")

INDEX = "sha256:" + "1" * 64        # manifest list（index）digest：傳統 image store 的 RepoDigests 記這個
ARM64 = "sha256:" + "2" * 64        # linux/arm64 manifest digest：containerd image store 可能記這個
AMD64 = "sha256:" + "3" * 64
ATTEST = "sha256:" + "4" * 64
OLD = "sha256:" + "9" * 64

# 模擬 docker buildx imagetools inspect 的輸出（實際格式，含 attestation manifest）
IMAGETOOLS_OUTPUT = f"""Name:      ghcr.io/irene-chou/vid-snatch:latest
MediaType: application/vnd.oci.image.index.v1+json
Digest:    {INDEX}

Manifests:
  Name:        ghcr.io/irene-chou/vid-snatch:latest@{ARM64}
  MediaType:   application/vnd.oci.image.manifest.v1+json
  Platform:    linux/arm64

  Name:        ghcr.io/irene-chou/vid-snatch:latest@{ATTEST}
  MediaType:   application/vnd.oci.image.manifest.v1+json
  Platform:    unknown/unknown
  Annotations:
    vnd.docker.reference.digest: {ARM64}
    vnd.docker.reference.type:   attestation-manifest

  Name:        ghcr.io/irene-chou/vid-snatch:latest@{AMD64}
  MediaType:   application/vnd.oci.image.manifest.v1+json
  Platform:    linux/amd64
"""

FAKE_DOCKER = r'''#!/bin/bash
# 假 docker：行為由 FAKE_* 環境變數控制，每次呼叫記到 $FAKE_LOG
echo "$*" >> "$FAKE_LOG"
case "$1 $2 $3" in
    "buildx imagetools inspect")
        case "$FAKE_REMOTE" in
            ok)   printf '%s' "$FAKE_IMAGETOOLS_OUTPUT"; exit 0 ;;
            hang) sleep 60; exit 0 ;;
            *)    echo "error: failed to resolve" >&2; exit 1 ;;
        esac ;;
    "image inspect --format")
        # $4 = 樣板，$5 = 映像檔
        case "$5" in
            vid-snatch)
                [ "$FAKE_LOCAL_EXISTS" = "1" ] || { echo "Error: No such image" >&2; exit 1; }
                printf '%s' "$FAKE_LOCAL_DIGESTS"; exit 0 ;;
            ghcr.io/*)
                echo "${FAKE_PULLED_ARCH:-arm64}"; exit 0 ;;
        esac
        exit 1 ;;
    "image inspect vid-snatch")
        [ "$FAKE_LOCAL_EXISTS" = "1" ] && exit 0
        echo "Error: No such image" >&2; exit 1 ;;
    "pull "*)
        if [ "$FAKE_PULL_OK" = "1" ]; then echo "latest: Pulling from irene-chou/vid-snatch"; exit 0; fi
        echo "Error response from daemon: Get https://ghcr.io/v2/: dial tcp: lookup ghcr.io: no such host" >&2
        exit 1 ;;
    "tag "*)   exit 0 ;;
    "build "*) echo "[fake build]"; exit 0 ;;
esac
echo "unexpected docker call: $*" >&2
exit 99
'''

FAKE_UNAME = '''#!/bin/bash
# .command 只用 uname -m 判斷架構；固定假裝是 Apple Silicon
echo arm64
'''

needs_bash = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="需要 bash")


@pytest.fixture
def fake(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in [("docker", FAKE_DOCKER), ("uname", FAKE_UNAME)]:
        p = bin_dir / name
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
    log = tmp_path / "docker.log"
    log.write_text("", encoding="utf-8")

    def run(func="ensure_image", *, local=True, local_digest=INDEX, remote="ok", pull_ok=True, pulled_arch="arm64"):
        env = dict(
            os.environ,
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            FAKE_LOG=str(log),
            FAKE_REMOTE=remote,
            FAKE_IMAGETOOLS_OUTPUT=IMAGETOOLS_OUTPUT,
            FAKE_LOCAL_EXISTS="1" if local else "0",
            FAKE_LOCAL_DIGESTS=f"ghcr.io/irene-chou/vid-snatch@{local_digest} " if local_digest else "",
            FAKE_PULL_OK="1" if pull_ok else "0",
            FAKE_PULLED_ARCH=pulled_arch,
        )
        proc = subprocess.run(
            ["bash", "-c", f'source "$1"; {func}; echo "exit=$?"', "bash", str(COMMAND)],
            capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60,
        )
        calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
        log.write_text("", encoding="utf-8")
        return proc, calls

    return run


def pulled(calls):
    return [c for c in calls if c.startswith("pull ")]


def tagged(calls):
    return [c for c in calls if c.startswith("tag ")]


def built(calls):
    return [c for c in calls if c.startswith("build ")]


@needs_bash
def test_sourcing_only_defines_functions(fake):
    proc, calls = fake("true")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "exit=0"
    assert calls == []


@needs_bash
def test_up_to_date_when_local_matches_index_digest(fake):
    proc, calls = fake(local_digest=INDEX)
    assert "正在檢查更新…" in proc.stdout and "已是最新版" in proc.stdout
    assert "exit=0" in proc.stdout
    assert not pulled(calls) and not built(calls)
    assert any(c.startswith("buildx imagetools inspect ghcr.io/irene-chou/vid-snatch:latest") for c in calls)


@needs_bash
def test_up_to_date_when_local_matches_platform_manifest_digest(fake):
    # containerd image store 的 RepoDigests 可能記的是平台 manifest 而非 index
    proc, calls = fake(local_digest=ARM64)
    assert "已是最新版" in proc.stdout
    assert not pulled(calls)


@needs_bash
def test_new_version_pulls_with_visible_progress(fake):
    proc, calls = fake(local_digest=OLD)
    assert "發現新版本，正在下載…（第一次或大改版可能要幾分鐘）" in proc.stdout
    # docker pull 的輸出不再導到 /dev/null
    assert "latest: Pulling from irene-chou/vid-snatch" in proc.stdout
    assert "更新完成！" in proc.stdout and "exit=0" in proc.stdout
    assert pulled(calls) == ["pull ghcr.io/irene-chou/vid-snatch:latest"]
    assert tagged(calls) == ["tag ghcr.io/irene-chou/vid-snatch:latest vid-snatch"]
    assert not built(calls)


@needs_bash
def test_locally_built_image_has_no_digest_and_is_treated_as_outdated(fake):
    proc, calls = fake(local_digest="")
    assert "發現新版本" in proc.stdout
    assert pulled(calls)


@needs_bash
def test_new_version_but_pull_fails_keeps_current_image(fake):
    proc, calls = fake(local_digest=OLD, pull_ok=False)
    assert "下載失敗，先用目前版本啟動" in proc.stdout and "exit=0" in proc.stdout
    assert pulled(calls) and not tagged(calls) and not built(calls)


@needs_bash
def test_pulled_image_with_wrong_arch_is_not_tagged(fake):
    proc, calls = fake(local_digest=OLD, pulled_arch="amd64")
    assert "下載失敗，先用目前版本啟動" in proc.stdout
    assert not tagged(calls)


@needs_bash
def test_offline_skips_pull_and_starts_with_local_image(fake):
    proc, calls = fake(remote="fail")
    assert "無法檢查更新，先用目前版本啟動" in proc.stdout and "exit=0" in proc.stdout
    assert not pulled(calls) and not tagged(calls) and not built(calls)


@needs_bash
def test_first_use_pulls_then_tags(fake):
    proc, calls = fake(local=False)
    assert "正在下載 vid-snatch" in proc.stdout and "下載完成！" in proc.stdout
    assert "正在檢查更新" not in proc.stdout
    assert pulled(calls) and tagged(calls) and not built(calls)
    # 首次沒有本機映像檔可比對，不必多問一次 registry
    assert not any(c.startswith("buildx") for c in calls)


@needs_bash
def test_first_use_falls_back_to_local_build_when_pull_fails(fake):
    proc, calls = fake(local=False, pull_ok=False)
    assert "建置完成！" in proc.stdout and "exit=0" in proc.stdout
    assert pulled(calls) and not tagged(calls)
    assert len(built(calls)) == 1 and built(calls)[0].startswith("build -t vid-snatch ")


@needs_bash
def test_run_with_timeout_kills_hung_command(fake):
    proc, _ = fake("run_with_timeout 1 sleep 30")
    assert proc.stdout.strip() == "exit=124"
    proc, _ = fake("run_with_timeout 5 true")
    assert proc.stdout.strip() == "exit=0"
    proc, _ = fake("run_with_timeout 5 false")
    assert proc.stdout.strip() == "exit=1"


@needs_bash
def test_remote_digests_extracts_every_sha256_from_imagetools_output(fake):
    proc, _ = fake("remote_digests")
    lines = proc.stdout.strip().splitlines()
    assert lines[-1] == "exit=0"
    assert set(lines[:-1]) == {INDEX, ARM64, AMD64, ATTEST}


def test_update_check_never_blocks_startup():
    # 比對遠端有 15 秒上限，且只用 Docker Desktop 內建的 buildx（不需 jq / timeout / 登入）
    assert 'run_with_timeout 15 docker buildx imagetools inspect "$IMAGE_REMOTE"' in SRC
    for cmd in ["jq", "timeout", "docker manifest inspect", "docker login"]:
        # 只抓當成指令執行的位置（行首、管線、$( 之後），註解提到不算
        assert not re.search(rf"(?m)(^|[|;&(]|\$\()\s*{cmd} ", SRC), cmd
    # 不再把 pull 的進度藏起來
    assert 'docker pull "$IMAGE_REMOTE" > /dev/null' not in SRC
    assert '[ "${BASH_SOURCE[0]}" != "$0" ] && return 0' in SRC
