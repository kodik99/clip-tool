# memeclip

Local web tool: paste a video link (or drop a file) and get a **9:16 vertical clip** for TikTok / Reels with

- a **blurred-fill background** (or crop / fit),
- **burned-in captions** (Whisper, runs offline),
- your **looping banner mp4** across the whole clip, placed above the TikTok UI zone.

Terminal-style UI, runs only on your own machine (`127.0.0.1:8765`). No API key needed.

## Install with Claude Code (easiest)

Open Claude Code in an empty folder and paste:

> Clone `https://github.com/kodik99/clip-tool`, read its README.md and CLAUDE.md, run the setup, fix anything the setup checks complain about, and start the app. Never ask me to paste secrets into the chat.

## Manual install

```bash
git clone https://github.com/kodik99/clip-tool memeclip && cd memeclip
./setup.sh          # creates .venv, installs deps, checks ffmpeg + deno
./start.command     # opens http://127.0.0.1:8765
```

Requirements: Python 3.10–3.13 (or `uv`), **ffmpeg built with libass**, optionally **deno** (YouTube links).

macOS: `brew install ffmpeg-full deno` — the plain `ffmpeg` formula has no libass, so captions silently fail.
Linux: `sudo apt install ffmpeg`.

## Using it

1. Put your banner `.mp4` in `banners/` (or use **+ upload** in the page). Banners are not part of this repo.
2. Paste a link or drop a file, pick layout + captions, press **run**.
3. Download the result. **clear all** deletes every generated video and working file (banners are kept).

Defaults (in `compose.py` flags): banner 65 % of frame width, bottom edge 280 px above the frame bottom,
video block centred at y = 720 px of 1920, captions just above the banner. First run downloads the Whisper `small` model.

## Find clips in long videos (needs an Anthropic API key)

Pick **mode: find clips**. The tool transcribes the video (Whisper, local), asks Claude for the best standalone moments,
renders each as a captioned 9:16 clip with your banner, and writes a **post description + hashtags** for each one
(shown under the clip with a copy button).

- **from / to**: only download and analyse that part of the video (saves time and money), e.g. `10:00` to `30:00`. Plain numbers mean minutes, `1:05:30` also works. Blank = start / end of the video.
- **max clips / length**: how many clips and how long each may be (seconds).
- **desc lang**: language for titles/descriptions (default: same as the video).
- Cost is shown per job. Roughly a few US cents for a 20-minute podcast with a Sonnet-class model.

Store your key once, in a terminal (hidden input, saved to the OS keychain; never paste keys into chats):

```bash
.venv/bin/python setkey.py
```

(or set `ANTHROPIC_API_KEY`). Whole-video mode needs no key.

## Notes

- Only download/clip content you have the rights to use; YouTube's terms and copyright still apply.
- Bundled font: Anton (SIL Open Font License).
