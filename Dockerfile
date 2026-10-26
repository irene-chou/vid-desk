FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl unzip && \
    rm -rf /var/lib/apt/lists/* && \
    curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /app

# 先裝依賴（這層很少變動，可善用 Docker cache）
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        torch torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir yt-dlp demucs

# 再複製程式碼（改程式碼不會重新下載依賴）
COPY vid_snatch/ ./vid_snatch/
RUN pip install --no-cache-dir --no-deps .

ENTRYPOINT ["vid-snatch"]
