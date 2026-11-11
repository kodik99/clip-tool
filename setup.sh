#!/usr/bin/env bash
# One-time setup: creates .venv, installs Python deps, checks ffmpeg/deno.
set -e
cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
  uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -r requirements.txt
else
  PY=""
  for c in python3.12 python3.13 python3.11 python3.10; do
    command -v "$c" >/dev/null 2>&1 && PY="$c" && break
  done
  if [ -z "$PY" ]; then
    echo "Need Python 3.10-3.13 (or uv). macOS: brew install python@3.12   (or: brew install uv)"; exit 1
  fi
  "$PY" -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

echo
echo "--- checks ---"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if command -v ffmpeg >/dev/null 2>&1; then
  if ffmpeg -hide_banner -filters 2>/dev/null | grep -q " subtitles "; then echo "ffmpeg: OK (libass present)"
  else echo "ffmpeg: FOUND BUT NO libass -> captions will not render. macOS: brew install ffmpeg-full"; fi
else
  echo "ffmpeg: MISSING. macOS: brew install ffmpeg-full   |   Linux: sudo apt install ffmpeg"
fi
command -v ffprobe >/dev/null 2>&1 || echo "ffprobe: MISSING (ships with ffmpeg)"
command -v deno >/dev/null 2>&1 && echo "deno: OK" || echo "deno: missing (optional but recommended for YouTube links): brew install deno"
echo
echo "Add your banner: put an .mp4 in banners/ (or upload it in the UI). Then run ./start.command"
