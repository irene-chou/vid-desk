"""預載去人聲模型。

demucs 4.1 先從 Hugging Face Hub 讀取模型（失敗才退回舊的 dl.fbaipublicfiles.com），
所以預載的是 Hub 上的檔案，放進 Hugging Face 的快取（HF_HOME）。伺服器執行時設
HF_HUB_OFFLINE=1，只讀快取、不連網。

這個檔案不 import vid_snatch 的其他模組，Dockerfile 才能在複製程式碼前單獨執行它：
    python models.py
"""

# 使用者可選的分離模型：快速（約 80 MB）與高品質（4 個模型的 bag，約 320 MB、慢約 4 倍）
DEMUCS_MODELS = ("htdemucs", "htdemucs_ft")
DEMUCS_MODEL = "htdemucs_ft"  # 預設：fine-tuned, best quality


def preload(name: str = DEMUCS_MODEL) -> list[str]:
    """下載 demucs.hf.get_hf_model(name) 會讀的所有檔案到 HF 快取，回傳本機路徑。"""
    import yaml
    from demucs.hf import DEFAULT_NAMESPACE, hf_repo_name
    from huggingface_hub import hf_hub_download

    # 與 demucs.hf.get_hf_model 相同的 repo 與檔名
    repo_id = f"{DEFAULT_NAMESPACE}/{hf_repo_name(name)}"
    bag_path = hf_hub_download(repo_id, f"{name}.yaml")
    with open(bag_path, encoding="utf-8") as f:
        bag = yaml.safe_load(f)
    paths = [bag_path]
    for sig in bag["models"]:
        paths.append(hf_hub_download(repo_id, f"{sig}.safetensors"))
    return paths


def preload_all(names: tuple[str, ...] = DEMUCS_MODELS) -> list[str]:
    """預載所有可選模型，回傳全部檔案路徑。"""
    paths: list[str] = []
    for name in names:
        paths.extend(preload(name))
    return paths


if __name__ == "__main__":
    # 只印 ASCII：Windows 上輸出被導向時預設是 cp1252，路徑裡的中文會讓 print 失敗
    print(f"demucs model files ready: {len(preload_all())}")
