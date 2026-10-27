import sys
import types

from vid_snatch import core, models


def test_core_uses_models_constant():
    assert core.DEMUCS_MODEL == models.DEMUCS_MODEL == "htdemucs_ft"


def test_preload_downloads_bag_yaml_and_each_model(monkeypatch, tmp_path):
    calls = []
    bag = tmp_path / "htdemucs_ft.yaml"
    bag.write_text("models: ['aaa', 'bbb']\nweights: [[1.], [1.]]\n", encoding="utf-8")

    def fake_download(repo_id, filename):
        calls.append((repo_id, filename))
        return str(bag) if filename.endswith(".yaml") else str(tmp_path / filename)

    hub = types.ModuleType("huggingface_hub")
    hub.hf_hub_download = fake_download
    demucs_pkg = types.ModuleType("demucs")
    hf = types.ModuleType("demucs.hf")
    hf.DEFAULT_NAMESPACE = "adefossez"
    hf.hf_repo_name = lambda name: "HTDemucs-ft"
    demucs_pkg.hf = hf
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "demucs", demucs_pkg)
    monkeypatch.setitem(sys.modules, "demucs.hf", hf)

    paths = models.preload()

    assert calls == [
        ("adefossez/HTDemucs-ft", "htdemucs_ft.yaml"),
        ("adefossez/HTDemucs-ft", "aaa.safetensors"),
        ("adefossez/HTDemucs-ft", "bbb.safetensors"),
    ]
    assert paths[0] == str(bag)
    assert len(paths) == 3
