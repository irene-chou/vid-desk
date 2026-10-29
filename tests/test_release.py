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
MAIN_SCRIPT = ROOT / "vid-desk.ps1"


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
    # 新 release 以標籤命名、標為 latest 並附上 vid-desk.zip；舊的 latest release 物件要清掉
    assert 'gh release create "$TAG"' in scripts and "--latest" in scripts
    assert 'gh release upload "$TAG" "$RUNNER_TEMP/pkg/vid-desk.zip" --clobber' in scripts
    assert "gh release delete latest --yes" in scripts
    # 標籤必須與 pyproject.toml 的版本一致
    assert "pyproject.toml" in scripts and '"v$version" != "$TAG"' in scripts


def test_release_tag_check_matches_pyproject_version_format():
    version = re.search(r'^version = "(.+)"$', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    init = (ROOT / "vid_desk/__init__.py").read_text(encoding="utf-8")
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


# ---- 回滾（issue #33）：rollback.yml 把指定舊版重新設為 latest ----

def rollback_steps():
    data, _ = load_workflow("rollback.yml")
    return data, data["jobs"]["rollback"]["steps"]


def test_rollback_is_manual_only_with_version_input_and_minimal_permissions():
    data, on = load_workflow("rollback.yml")
    assert list(on) == ["workflow_dispatch"]
    version = on["workflow_dispatch"]["inputs"]["version"]
    assert version["required"] is True and version["type"] == "string"
    assert data["permissions"] == {"contents": "write", "packages": "write"}
    # 與 release.yml 共用 concurrency 群組，回滾與發版不會同時改 latest
    assert data["concurrency"]["group"] == load_workflow("release.yml")[0]["concurrency"]["group"]


def test_rollback_version_regex_accepts_x_y_z_with_or_without_v():
    _, steps = rollback_steps()
    script = next(s for s in steps if s.get("id") == "version")["run"]
    pattern = re.search(r"=~ (\^v\?.+?\$) \]\]", script).group(1)
    assert pattern == r"^v?[0-9]+\.[0-9]+\.[0-9]+$"
    for ok in ["0.3.0", "v0.3.0", "10.20.30"]:
        assert re.fullmatch(pattern, ok), ok
    for bad in ["0.3", "latest", "v0.3.0-rc1", "main", "0.3.0.1", "V0.3.0", "b650caa", ""]:
        assert not re.fullmatch(pattern, bad), bad
    # 去掉前綴 v 後以 X.Y.Z 當 GHCR 標籤、vX.Y.Z 當 release / git 標籤
    assert 'version="${raw#v}"' in script
    assert 'echo "tag=v$version"' in script


def test_rollback_validates_everything_before_touching_any_latest():
    _, steps = rollback_steps()
    check = next(i for i, s in enumerate(steps) if s.get("id") == "check")
    check_script = steps[check]["run"]
    # 驗證三樣都存在：git 標籤、release（非草稿／預先發布）、GHCR 多架構映像檔
    assert 'git rev-parse --verify --quiet "refs/tags/$TAG^{commit}"' in check_script
    assert 'gh release view "$TAG" --json tagName,isDraft,isPrerelease' in check_script
    assert 'docker buildx imagetools inspect "$IMAGE:$VERSION"' in check_script
    assert '"$archs" != "amd64,arm64"' in check_script
    # 驗證之前的步驟都不能改東西
    for s in steps[: check + 1]:
        run = s.get("run", "")
        for mutating in ["gh release edit", "gh release delete", "git push", "imagetools create"]:
            assert mutating not in run, (s.get("name"), mutating)
    # 三個 latest 的順序：release → git 標籤 → 清掉舊 latest release → GHCR → 確認
    after = "\n".join(s.get("run", "") for s in steps[check + 1 :])
    order = [
        after.index('gh release edit "$TAG" --draft=false --prerelease=false --latest'),
        after.index('git tag -f latest "$COMMIT"'),
        after.index("git push -f origin latest"),
        after.index("gh release delete latest --yes"),
        after.index('docker buildx imagetools create -t "$IMAGE:latest" "$IMAGE:$VERSION"'),
        after.index("$GITHUB_STEP_SUMMARY"),
    ]
    assert order == sorted(order)


def test_rollback_summary_reports_three_latests_and_fails_on_mismatch():
    _, steps = rollback_steps()
    script = steps[-1]["run"]
    assert "gh release view --json tagName --jq .tagName" in script
    assert "git ls-remote origin refs/tags/latest" in script
    assert 'docker buildx imagetools inspect "$IMAGE:latest"' in script
    for expected in ['"$release_latest" = "$TAG"', '"$git_latest" = "$COMMIT"', '"$latest_digest" = "$DIGEST"']:
        assert expected in script
    assert '[ -n "$ok" ]' in script


def test_rollback_uses_same_pinned_actions_as_release_and_publish():
    _, steps = rollback_steps()
    used = {s["uses"] for s in steps if "uses" in s}
    allowed = set()
    for name in ["release.yml", "publish.yml"]:
        data, _ = load_workflow(name)
        for job in data["jobs"].values():
            allowed |= {s["uses"] for s in job["steps"] if "uses" in s}
    assert used <= allowed, used - allowed
    assert {"actions/checkout@v4", "docker/setup-buildx-action@v3", "docker/login-action@v3"} <= used


def test_next_release_still_moves_latest_regardless_of_rollback():
    # release.yml / publish.yml 不看現在 latest 指到哪，直接以 --latest、-f、type=raw 覆蓋，回滾後再發版不會卡住
    data, _ = load_workflow("release.yml")
    scripts = "\n".join(step.get("run", "") for step in data["jobs"]["package"]["steps"])
    assert 'gh release edit "$TAG" --draft=false --prerelease=false --latest' in scripts
    assert "git push -f origin latest" in scripts
    data, _ = load_workflow("publish.yml")
    meta = next(s for s in data["jobs"]["merge"]["steps"] if s.get("id") == "meta")
    assert "type=raw,value=latest" in meta["with"]["tags"].split()
    assert "latest=false" in meta["with"]["flavor"]


def test_readme_documents_rollback():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "rollback.yml" in readme
    assert "gh workflow run rollback.yml -f version=" in readme
