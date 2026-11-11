"""Groq speech-to-text (free tier): Whisper large-v3 running in Groq's cloud - much faster than the local CPU models.
The audio is cut into 10-minute FLAC chunks (16 kHz mono, ~10-15 MB each; the free tier allows 25 MB per file), each chunk is
sent to the OpenAI-compatible endpoint with word timestamps, and the timestamps are shifted back to the start of the media.
Free-plan limits (see console.groq.com/docs/rate-limits): about 20 requests/min and 7,200 audio seconds/hour; a 429 answer carries a
`retry-after` header, which is honoured. Note: the audio leaves this computer."""
import subprocess, tempfile, time
from pathlib import Path

import httpx

import keys

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3"
CHUNK_SEC = 600
MAX_BYTES = 24 * 1024 * 1024


class GroqError(RuntimeError):
    pass


def _post(client, key, flac, language, model, prompt, sleep=time.sleep):
    data = {"model": model, "response_format": "verbose_json", "timestamp_granularities[]": "word", "temperature": "0"}
    if language:
        data["language"] = language
    if prompt:
        data["prompt"] = prompt
    for attempt in range(4):
        with open(flac, "rb") as fh:
            r = client.post(URL, headers={"Authorization": f"Bearer {key}"}, data=data,
                            files={"file": (Path(flac).name, fh, "audio/flac")})
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401:
            raise GroqError("Groq rejected the API key")
        if r.status_code == 429:
            wait = float(r.headers.get("retry-after", "20"))
            if wait > 120 or attempt == 3:
                raise GroqError(f"Groq free-tier limit reached (retry in {wait:.0f}s)")
            sleep(wait + 1)
            continue
        raise GroqError(f"Groq error {r.status_code}: {r.text[:200]}")


def _words_from_segments(segments, offset):
    """Fallback when no word timestamps come back: spread each segment's words evenly over its time span."""
    out = []
    for s in segments or []:
        toks = (s.get("text") or "").split()
        if not toks:
            continue
        a, b = float(s["start"]), float(s["end"])
        step = (b - a) / len(toks)
        out += [(offset + a + i * step, offset + a + (i + 1) * step, t) for i, t in enumerate(toks)]
    return out


def transcribe(media, language=None, on_progress=None, model=MODEL, prompt=None):
    """-> (words [(start, end, text)], language). Times are seconds from the start of `media`."""
    key = keys.get_secret("groq")
    if not key:
        raise GroqError("no Groq key. Create a free one at console.groq.com, then run: python setkey.py groq")
    from compose import FFMPEG, probe_duration            # imported lazily: compose imports captions
    total = probe_duration(str(media))
    words, lang = [], language
    with tempfile.TemporaryDirectory() as td, httpx.Client(timeout=600) as client:
        start = 0.0
        while total - start > 1.0:
            length = min(CHUNK_SEC, total - start)
            flac = Path(td) / "chunk.flac"
            subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(media),
                            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(flac)], check=True)
            if flac.stat().st_size > MAX_BYTES:
                raise GroqError("an audio chunk is larger than the 25 MB free-tier limit")
            j = _post(client, key, flac, language, model, prompt)
            lang = j.get("language") or lang
            got = [(start + float(w["start"]), start + float(w["end"]), (w.get("word") or "").strip())
                   for w in (j.get("words") or []) if (w.get("word") or "").strip()]
            words += got or _words_from_segments(j.get("segments"), start)
            start += length
            if on_progress:
                on_progress(start)
    return words, lang
