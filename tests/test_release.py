"""發版機制（issue #8）：release / publish 只在推 v* 標籤時跑，Windows 啟動器以 releases/latest 為準。

這些檔案在 PR 上不會真的執行，先在這裡把語法與約定鎖住。
"""
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).parent.parent
WORKFLOWS = ROOT / ".github/workflows"
LAUNCHER = ROOT / "windows/launcher.ps1"
SMOKE = ROOT / "windows/ci-smoke.ps1"
MAIN_SCRIPT = ROOT / "vid-snatch.ps1"


def load_workflow(name):
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # PyYAML 把 `on:` 讀成布林 True
    return data, data[True]


def test_all_workflows_parse():
    files = sorted(WORKFLOWS.glob("*.yml"))
    assert files
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert isinstance(data.get("jobs"), dict), f.name


def test_release_and_publish_only_run_on_version_tags():
    for name in ["release.yml", "publish.yml"]:
        data, on = load_workflow(name)
        assert on["push"] == {"tags": ["v*"]}, name
        assert "pull_request" not in on, name
        # workflow_dispatch 可以選到分支，job 自己要擋掉非 v* 標籤
        for job in data["jobs"].values():
            if job.get("needs"):
                continue
            assert job.get("if") == "startsWith(github.ref, 'refs/tags/v')", name


def test_release_keeps_latest_tag_for_old_launchers_and_marks_release_latest():
    data, _ = load_workflow("release.yml")
    scripts = "\n".join(step.get("run", "") for step in data["jobs"]["package"]["steps"])
    # 舊版啟動器查 commits/latest，這個標籤要跟著發版移動
    assert "git tag -f latest" in scripts and "git push -f origin latest" in scripts
    # 新 release 以標籤命名、標為 latest 並附上 vid-snatch.zip；舊的 latest release 物件要清掉
    assert 'gh release create "$TAG"' in scripts and "--latest" in scripts
    assert 'gh release upload "$TAG" "$RUNNER_TEMP/pkg/vid-snatch.zip" --clobber' in scripts
    assert "gh release delete latest --yes" in scripts
    # 標籤必須與 pyproject.toml 的版本一致
    assert "pyproject.toml" in scripts and '"v$version" != "$TAG"' in scripts


def test_release_tag_check_matches_pyproject_version_format():
    version = re.search(r'^version = "(.+)"$', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    init = (ROOT / "vid_snatch/__init__.py").read_text(encoding="utf-8")
    assert f'__version__ = "{version}"' in init
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)


def test_publish_tags_image_with_version_and_latest():
    data, _ = load_workflow("publish.yml")
    meta = next(s for s in data["jobs"]["merge"]["steps"] if s.get("id") == "meta")
    tags = meta["with"]["tags"].split()
    assert "type=semver,pattern={{version}}" in tags
    assert "type=raw,value=latest" in tags


def test_other_workflows_still_run_on_pull_request():
    for name in ["windows.yml", "docker-check.yml"]:
        _, on = load_workflow(name)
        assert "pull_request" in on, name


def test_launcher_queries_releases_latest_and_uses_tag_name():
    text = LAUNCHER.read_bytes()
    assert text.startswith(b"\xef\xbb\xbf") and not text[3:].startswith(b"\xef\xbb\xbf")
    assert text.count(b"\r\n") == text.count(b"\n"), "launcher.ps1 must be CRLF"
    src = text.decode("utf-8-sig")
    assert 'https://api.github.com/repos/$Repo/releases/latest' in src
    assert "commits/latest" not in src
    assert ".tag_name" in src
    # 下載走 archive/<ref>.zip：標籤與 sha 都接受，冒煙測試才能傳 sha
    assert 'https://github.com/$Repo/archive/$tag.zip' in src
    assert "$env:VS_UPDATE_API" in src


def test_smoke_mock_matches_launcher_endpoint_format():
    src = SMOKE.read_bytes().decode("utf-8-sig")
    assert "api.github.com" not in src, "冒煙測試不該再打 GitHub API"
    assert '"tag_name`": `"$Sha`"' in src
    assert "$env:VS_UPDATE_API = $MockApi" in src
    assert "'--directory', " in src and "latest.json" in src


def test_main_script_commit_contract_accepts_tag_or_sha():
    src = MAIN_SCRIPT.read_bytes().decode("utf-8-sig")
    assert "40 碼 commit sha" in src and "release 標籤名稱" in src
    assert "[string]$Commit = 'local'" in src
