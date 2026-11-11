# memeclip — notes for Claude Code

Local FastAPI app (`app.py`) + single-page UI (`index.html`). Pipeline per job: yt-dlp download (or upload) ->
`compose.py` (faster-whisper captions via `captions.py` -> ASS file -> one ffmpeg filter graph: blur-fill/crop +
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

## Crop corrector (`reframe.py`)
`compose.py --layout crop --crop-fix`: ffmpeg scene detection -> shots; frames sampled at <=2 fps and scanned with MediaPipe BlazeFace
(model auto-downloaded to `models/`, git-ignored) at up to 1280 px wide in overlapping full-height square tiles; if a frame yields nothing,
a second pass with half-size tiles runs (far-away faces in wide two-shots are only ~55-80 px and are invisible to a single 640 px scan).
Per shot: cluster detections, rank by how CONSISTENTLY a face is seen (not by size: a big static false hit used to beat the small real
face), keep one person (ties -> the closer/larger face), choose a crop x that fully contains it and avoids half-cut second faces,
emit a piecewise-constant `crop=...:x='if(lt(t,..),..)'`. A shot with no face reuses the crop of a visually similar shot (same camera
angle, via a tiny frame signature) before falling back to a centre crop. No panning, no face-following.
Tuning facts (measured on a 2-person podcast): real faces score >=0.5, furniture/mug false hits 0.2-0.49 -> `MIN_CONF = 0.5`.
Masked/balaclava faces are still not detected (they use the reuse / centre fallback). OpenCV 5 ships no Haar cascades.
The NOTE line shows `face found in X, same-angle reuse Y, centre fallback Z` per render - check it when a crop looks wrong.

## Manual part mode (`findclips.py --manual`)
Mode `part` in the UI/app reuses `findclips.py` with `--manual --offset FROM --limit-sec LEN [--describe]` (the app passes `--describe` whenever the look-box hook toggle is ticked in part mode): no Claude pick, the clip is exactly
FROM..FROM+LEN. Transcription runs only if captions or AI text/hook are wanted (`need_words`); `llm.describe_clip` writes title/description/hook for
the chosen part and is skipped (with a NOTE) if there is no Anthropic key. App validation: both from and to required, 3 s <= length <= 10 min.
Times: a plain number is MINUTES ("5" = 5 min); use "0:05" for 5 seconds.

## Transcription engines (`captions.transcribe_words`)
`model` = tiny/base/small/medium (local faster-whisper) or `groq` (`groq_asr.py`: Whisper large-v3 via Groq's OpenAI-compatible
`/audio/transcriptions`, `verbose_json` + `timestamp_granularities[]=word`, language hint, 10-min 16 kHz mono FLAC chunks because of the
25 MB free-tier file cap, `retry-after` honoured on 429). Any Groq failure (no key, limit, offline) prints a `NOTE` and falls back to local
`small`. Keys live in `keys.py` (env var, then keychain service `memeclip`; `python setkey.py [anthropic|groq]`). Never ask for keys in chat.

## Hook headline (`hook.py`)
`compose.py --hook "text"` draws an explicit headline; `--hook-auto` asks `llm.make_hook` (one small Claude call on the transcript);
`findclips.py --hook` makes `llm.pick_clips(..., want_hook=True)` return a `hook` per clip (same call). The headline is a transparent
PNG (Pillow: bold serif + colour emojis; prefers 2 balanced lines, auto-shrinks) overlaid as ffmpeg input #2 at y=170 (below the TikTok
top UI). Blur layout: the video block is pushed down if needed so it never covers the hook. Crop layout / tall sources: the hook sits on
the picture with a soft dark gradient. Libass cannot draw colour emojis, which is why this is an image and not an ASS subtitle.
Fonts are the OS's (Georgia Bold + Apple Color Emoji on macOS); other systems fall back (see README). A failed hook never fails a render.

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
