FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl unzip && \
    rm -rf /var/lib/apt/lists/* && \
    curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /app

# 先裝依賴（這層很少變動，可善用 Docker cache）
# 注意：這層之前不要 COPY 任何會隨版本變動的檔案（pyproject.toml、vid_snatch/__init__.py），
# 否則只改版本號就會讓相依套件層與模型層（約 670 MB）全部重抓；tests/test_dockerfile.py 會檢查
# demucs 依賴的 sphn 在 aarch64 沒有預編譯 wheel，需暫時裝編譯工具從原始碼建置，裝完即移除
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential cmake && \
    pip install --no-cache-dir \
        torch torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    CMAKE_POLICY_VERSION_MINIMUM=3.5 pip install --no-cache-dir yt-dlp demucs numpy && \
    pip install --no-cache-dir fastapi 'uvicorn[standard]' sse-starlette && \
    apt-get purge -y --auto-remove build-essential cmake && \
    rm -rf /var/lib/apt/lists/* /root/.cache /root/.cargo /root/.rustup

# 預載兩個 Demucs 模型（快速 htdemucs 約 80 MB、高品質 htdemucs_ft 約 320 MB），第一次去人聲不必等下載。
# demucs 4.1 從 Hugging Face Hub 讀模型，所以放進 HF 快取（/root/.cache/huggingface）；
# 執行時 HF_HUB_OFFLINE=1 只讀快取、不連網
COPY vid_snatch/models.py /tmp/models.py
RUN python /tmp/models.py && rm /tmp/models.py
ENV HF_HUB_OFFLINE=1

# 最後才複製 pyproject.toml 與程式碼（改程式碼或版本號只會重建這幾層，約 1 MB）
COPY pyproject.toml ./
COPY vid_snatch/ ./vid_snatch/
RUN pip install --no-cache-dir --no-deps .

ENV VS_OUTPUT_DIR=/app/output VS_CONFIG_DIR=/app/config
EXPOSE 8080

ENTRYPOINT ["vid-snatch"]
