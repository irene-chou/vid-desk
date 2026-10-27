FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl unzip && \
    rm -rf /var/lib/apt/lists/* && \
    curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /app

# 先裝依賴（這層很少變動，可善用 Docker cache）
# demucs 依賴的 sphn 在 aarch64 沒有預編譯 wheel，需暫時裝編譯工具從原始碼建置，裝完即移除
COPY pyproject.toml ./
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential cmake && \
    pip install --no-cache-dir \
        torch torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    CMAKE_POLICY_VERSION_MINIMUM=3.5 pip install --no-cache-dir yt-dlp demucs numpy && \
    pip install --no-cache-dir fastapi 'uvicorn[standard]' sse-starlette && \
    apt-get purge -y --auto-remove build-essential cmake && \
    rm -rf /var/lib/apt/lists/* /root/.cache /root/.cargo /root/.rustup

# 預載 Demucs htdemucs_ft 模型（4 個檔案，約 320 MB），第一次去人聲不必等下載
RUN mkdir -p /root/.cache/torch/hub/checkpoints && \
    curl -fsSL -o /root/.cache/torch/hub/checkpoints/f7e0c4bc-ba3fe64a.th \
        https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/f7e0c4bc-ba3fe64a.th && \
    curl -fsSL -o /root/.cache/torch/hub/checkpoints/d12395a8-e57c48e6.th \
        https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/d12395a8-e57c48e6.th && \
    curl -fsSL -o /root/.cache/torch/hub/checkpoints/92cfc3b6-ef3bcb9c.th \
        https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/92cfc3b6-ef3bcb9c.th && \
    curl -fsSL -o /root/.cache/torch/hub/checkpoints/04573f0d-f3cf25b2.th \
        https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/04573f0d-f3cf25b2.th

# 再複製程式碼（改程式碼不會重新下載依賴）
COPY vid_snatch/ ./vid_snatch/
RUN pip install --no-cache-dir --no-deps .

ENV VS_OUTPUT_DIR=/app/output VS_CONFIG_DIR=/app/config
EXPOSE 8080

ENTRYPOINT ["vid-snatch"]
