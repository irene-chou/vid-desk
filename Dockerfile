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

# 預載 Demucs htdemucs 模型，第一次去人聲不必等下載
RUN mkdir -p /root/.cache/torch/hub/checkpoints && \
    curl -fsSL -o /root/.cache/torch/hub/checkpoints/955717e8-8726e21a.th \
        https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th

# 再複製程式碼（改程式碼不會重新下載依賴）
COPY vid_snatch/ ./vid_snatch/
RUN pip install --no-cache-dir --no-deps .

ENV VS_OUTPUT_DIR=/app/output VS_CONFIG_DIR=/app/config
EXPOSE 8080

ENTRYPOINT ["vid-snatch"]
