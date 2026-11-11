# memeclip — notes for Claude Code

Local FastAPI app (`app.py`) + single-page UI (`index.html`). Pipeline per job: yt-dlp download (or upload) ->
`compose.py` (faster-whisper captions via `captions.py` -> ASS file -> one ffmpeg filter graph: blur-fill/crop/fit +
looping banner overlay). Jobs run one at a time in a worker thread; state is in memory; output in `output/`, scratch in `jobs/`.

## Setup / run
- `./setup.sh` then `./start.command` (serves http://127.0.0.1:8765). Server must stay bound to 127.0.0.1.
- Whole-video mode needs no API key. "Find clips" mode needs an Anthropic key: `llm.get_key()` reads `ANTHROPIC_API_KEY`, then the
  OS keychain (service `memeclip`, set with `python setkey.py`, or `autoclip` if AutoClip was used). **Never ask the user to paste secrets
  in chat** (if they do, tell them to revoke the key). Claude Code can't type keys for the user.

## Gotchas (all hit in real use)
- **ffmpeg needs libass** or captions are silently skipped. macOS: `brew install ffmpeg-full` (not `ffmpeg`).
  `compose.py` looks for ffmpeg in `$FFMPEG_DIR`, `./tools/bin`, then PATH.
- **PyAV must be < 17** (`av>=14,<17`): newer versions break faster-whisper (`open() got an unexpected keyword argument 'metadata_errors'`).
- **YouTube downloads** want a JS runtime (deno) plus `yt-dlp[default]` (yt-dlp-ejs). The app prepends `/opt/homebrew/bin` to PATH for yt-dlp.
  If YouTube shows a bot check, set yt-dlp cookies-from-browser or upload the file instead.
- **Homebrew on a new macOS** may say "unsupported macOS version": run `brew update` first. On Apple Silicon use the native `/opt/homebrew` install, not the Intel `/usr/local` one.
- Claude Code's auto mode may refuse to run binaries downloaded from outside; prefer `brew`/`pip` installs.

## Layout geometry
Frame 1080x1920. Banner width = 65 % of frame, bottom edge 280 px above the bottom (clears TikTok UI), video block centred at y=720,
captions bottom at `banner_y - 40`. Change via `compose.py` flags `--banner-scale --banner-bottom --video-center-y`.

## Disk hygiene
`run_job` deletes `jobs/<id>/` in a `finally` block (full downloaded video, audio.wav, words.json); only finished clips remain in `output/`.
`jobs/` is also wiped on server start. Never keep full-length sources around.

## Don't commit
`banners/*.mp4`, `output/`, `jobs/`, `samples/`, `tools/`, `.venv/` (see `.gitignore`). Banners are the user's own branded assets.

## Find-clips pipeline (`findclips.py`)
ffmpeg audio extract (optionally a `--offset`/`--limit-sec` range) -> faster-whisper words (`words.json`) -> sentences -> `llm.pick_clips` (one Claude call, tool
`submit_clips`: sentence-id ranges + title + description) -> validate length/overlap -> `compose.py --start --end --words-json` per clip.
Subprocess protocol on stdout: `STAGE x`, `PCT n`, `NOTE text`, `CLIP {json}` (parsed by `app.py`). the whole video is downloaded with
yt-dlp's native downloader (fast, ~250 MB/hour at 1080p) and `findclips --offset/--limit-sec` cuts the from/to range locally, keeping source timestamps.
**Do not use `yt-dlp --download-sections`**: it routes through ffmpeg and crawled at ~0.14x realtime (a 20 min range never finished). Gotcha: current Claude models reject forced `tool_choice`, `temperature` and assistant prefill - use plain tool calls.

## Ideas / next
Descriptions for whole-video mode, safe-zone preview in the UI, face-tracking crop for podcasts (see AutoClip).
