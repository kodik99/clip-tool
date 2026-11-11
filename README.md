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

## Not included (yet)

Auto-picking highlights from long videos / generating post descriptions needs an LLM and an API key.
The plan is to plug in [AutoClip](https://github.com/artbyjazi/autoclip) for that. Short videos are processed whole.

## Notes

- Only download/clip content you have the rights to use; YouTube's terms and copyright still apply.
- Bundled font: Anton (SIL Open Font License).
