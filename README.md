# vid-snatch

Download YouTube audio/video and optionally remove vocals using Demucs.

## Quick Start

- **macOS** — Double-click `vid-snatch.command`
- **Windows** — Double-click `vid-snatch.bat`

## Usage (Docker CLI)

```bash
# Build once
docker build -t vid-snatch .

# Download audio (MP3)
docker run --rm -it -v ~/Music/vid-snatch:/app/output vid-snatch "URL"

# Download audio + remove vocals
docker run --rm -it -v ~/Music/vid-snatch:/app/output -v vid-snatch-models:/root/.cache/torch vid-snatch "URL" --no-vocals

# Download video (MP4)
docker run --rm -it -v ~/Music/vid-snatch:/app/output vid-snatch "URL" --video
```

Files are saved to `~/Music/vid-snatch/` by default. You can change the output path from the **Settings** menu (option 4). Settings are saved to `~/.config/vid-snatch/config`.

## Options

| Flag | Description |
|------|-------------|
| `-o, --output` | Output directory (default: `./output`) |
| `--video` | Download video (MP4) instead of audio |
| `--no-vocals` | Remove vocals with Demucs |

> First time running vocal removal will auto-download the Demucs `htdemucs_ft` model (~320MB).
