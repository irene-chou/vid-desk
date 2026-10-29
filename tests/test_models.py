import sys
import types

from vid_desk import core, models


def test_core_uses_models_constant():
    assert core.DEMUCS_MODEL == models.DEMUCS_MODEL == "htdemucs_ft"
    assert models.DEMUCS_MODELS == ("htdemucs", "htdemucs_ft")
    assert models.DEMUCS_MODEL in models.DEMUCS_MODELS


def _fake_hub(monkeypatch, tmp_path, calls):
    def fake_download(repo_id, filename):
        calls.append((repo_id, filename))
        if filename.endswith(".yaml"):
            bag = tmp_path / filename
            n = 4 if "ft" in filename else 1
            bag.write_text("models: [" + ", ".join(f"'{filename[:-5]}-{i}'" for i in range(n)) + "]\n", encoding="utf-8")
            return str(bag)
        return str(tmp_path / filename)

    hub = types.ModuleType("huggingface_hub")
    hub.hf_hub_download = fake_download
    demucs_pkg = types.ModuleType("demucs")
    hf = types.ModuleType("demucs.hf")
    hf.DEFAULT_NAMESPACE = "adefossez"
    hf.hf_repo_name = lambda name: {"htdemucs": "HTDemucs", "htdemucs_ft": "HTDemucs-ft"}[name]
    demucs_pkg.hf = hf
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "demucs", demucs_pkg)
    monkeypatch.setitem(sys.modules, "demucs.hf", hf)


def test_preload_downloads_bag_yaml_and_each_model(monkeypatch, tmp_path):
    calls = []
    _fake_hub(monkeypatch, tmp_path, calls)

    paths = models.preload()

    assert calls == [
        ("adefossez/HTDemucs-ft", "htdemucs_ft.yaml"),
        *(("adefossez/HTDemucs-ft", f"htdemucs_ft-{i}.safetensors") for i in range(4)),
    ]
    assert paths[0] == str(tmp_path / "htdemucs_ft.yaml")
    assert len(paths) == 5


def test_preload_all_covers_both_models(monkeypatch, tmp_path):
    calls = []
    _fake_hub(monkeypatch, tmp_path, calls)

    paths = models.preload_all()

    assert [c for c in calls if c[1].endswith(".yaml")] == [
        ("adefossez/HTDemucs", "htdemucs.yaml"),
        ("adefossez/HTDemucs-ft", "htdemucs_ft.yaml"),
    ]
    assert len(paths) == 2 + 1 + 4
