# memeclip — notes for Claude Code

Local FastAPI app (`app.py`) + single-page UI (`index.html`). Pipeline per job: yt-dlp download (or upload) ->
`compose.py` (faster-whisper captions via `captions.py` -> ASS file -> one ffmpeg filter graph: blur-fill/crop/fit +
looping banner overlay). Jobs run one at a time in a worker thread; state is in memory; output in `output/`, scratch in `jobs/`.

## Setup / run
- `./setup.sh` then `./start.command` (serves http://127.0.0.1:8765). Server must stay bound to 127.0.0.1.
- No API key is needed. If an LLM is added later, store keys in the OS keychain; **never ask the user to paste secrets in chat**
  (if they do, tell them to revoke the key).

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

## Don't commit
`banners/*.mp4`, `output/`, `jobs/`, `samples/`, `tools/`, `.venv/` (see `.gitignore`). Banners are the user's own branded assets.

## Ideas / next
Long-video highlight finder (AutoClip approach: Whisper -> LLM picks moments -> clips), post-description generator, safe-zone preview in the UI.
