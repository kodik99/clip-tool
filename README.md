# memeclip

Local web tool: paste a video link (or drop a file) and get a **9:16 vertical clip** for TikTok / Reels with

- a **blurred-fill background** (or crop),
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

**Layouts:** *blur-fill* shows the whole video over a blurred copy of itself (nothing is cropped); *crop* zooms in to fill the
screen and cuts off the sides.
**Crop corrector** (shown for *crop*): instead of always cropping the dead centre, it finds faces and picks one fixed,
face-safe crop position per camera shot (no panning). With two people it keeps one fully in frame. Small faces in wide two-shots are found by a tiled, higher-resolution scan; a shot with no
face reuses the crop of a similar camera angle, else a centre crop. First use downloads a 0.2 MB MediaPipe face model into `models/`.

Defaults (in `compose.py` flags): banner 65 % of frame width, bottom edge 280 px above the frame bottom,
video block centred at y = 720 px of 1920, captions just above the banner. First run downloads the Whisper `small` model.

## Faster / better transcription: Groq (free cloud, optional)

In **captions > accuracy** choose **groq cloud (free, fast)**: Whisper large-v3 running in [Groq](https://console.groq.com)'s cloud.
A 20-minute range takes seconds instead of ~10 minutes of local CPU, and large-v3 is more accurate than the local models on smaller
languages such as Latvian (set **language** to e.g. `lv` for best results). Create a free key at console.groq.com, then store it:

```bash
.venv/bin/python setkey.py groq
```

(or set `GROQ_API_KEY`). The audio is uploaded to Groq (in 10-minute FLAC chunks), so don't use it for private material. Free-plan limits
are roughly 20 requests/minute and 2 hours of audio per hour; if the key is missing or a limit is hit, the job continues with the local
*balanced* model and the job note says so.

## Hook headline (optional, needs an API key)

Tick **hook: headline on top** and Claude writes a short, catchy on-screen title (max ~55 characters) with 1-2 fitting emojis,
in the video's language (or the *desc lang* you set), drawn at the top of the frame. In *find clips* mode it comes from the same Claude
call as the title and description (almost free) and is on by default; in *whole video* mode it is one small extra call (about a tenth of a cent).
The text and colour emojis are drawn as an image with Pillow. **Fonts:** Georgia Bold + Apple Color Emoji on macOS. On other systems it
falls back to DejaVu Serif Bold / the bundled Anton, and emojis are skipped when no colour-emoji font (e.g. Noto Color Emoji) is installed.

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
