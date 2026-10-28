"""Ko-fi 贊助連結（issue #41）：FUNDING.yml 讓 repo 頁面出現 Sponsor 按鈕；README 低調放一個連結。"""
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
KOFI_URL = "https://ko-fi.com/zephyrinn"


def test_funding_yml_points_to_kofi():
    text = (ROOT / ".github/FUNDING.yml").read_text(encoding="utf-8")
    assert yaml.safe_load(text) == {"ko_fi": "zephyrinn"}


def test_readme_has_kofi_link_without_youtube_download_wording():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## 支持這個專案" in readme
    section = readme.split("## 支持這個專案", 1)[1].split("\n## ", 1)[0]
    assert f"[請我喝杯咖啡 ☕]({KOFI_URL})" in section
    assert "YouTube 下載" not in section
