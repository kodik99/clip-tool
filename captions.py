"""Transcribe with faster-whisper and write an ASS subtitle file (short, punchy caption chunks)."""
from pathlib import Path

def _ts(t):
    h, rem = divmod(t, 3600); m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"

def transcribe_words(media, model="small", language=None, on_progress=None):
    """model: tiny/base/small/medium (local, faster-whisper) or 'groq' (Whisper large-v3 in Groq's free cloud)."""
    if model == "groq":
        try:
            import groq_asr
            print("STAGE transcribing (groq large-v3, cloud)", flush=True)
            return groq_asr.transcribe(media, language=language, on_progress=on_progress)
        except Exception as e:                      # no key, rate limit, no internet...: don't fail the job
            print(f"NOTE groq unavailable ({e}); used the local 'small' model instead", flush=True)
            model = "small"
    from faster_whisper import WhisperModel
    sizes = {"tiny": "75 MB", "base": "140 MB", "small": "460 MB", "medium": "1.4 GB"}
    print(f"STAGE loading speech model ({model}; first use downloads about {sizes.get(model, '?')})", flush=True)
    m = WhisperModel(model, device="cpu", compute_type="int8")      # downloads the model on first use
    print("STAGE transcribing", flush=True)
    segs, info = m.transcribe(media, word_timestamps=True, language=language, vad_filter=True)
    words = []
    for s in segs:
        words += [(w.start, w.end, w.word.strip()) for w in (s.words or []) if w.word.strip()]
        if on_progress:
            on_progress(s.end)
    return words, info.language

def save_words(words, lang, path):
    import json
    Path(path).write_text(json.dumps({"language": lang, "words": words}), encoding="utf-8")

def load_words(path):
    import json
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return [tuple(w) for w in d["words"]], d["language"]

def window(words, start, end):
    """Words inside [start, end], re-timed so the clip starts at 0."""
    return [(s - start, e - start, t) for s, e, t in words if s >= start - 0.05 and e <= end + 0.05]

def chunk(words, max_words=3, max_chars=22, gap=0.6):
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or sum(len(x[2]) + 1 for x in cur) + len(w[2]) > max_chars or w[0] - cur[-1][1] > gap):
            out.append(cur); cur = []
        cur.append(w)
    if cur: out.append(cur)
    return out

def write_ass(words, path, W=1080, H=1920, bottom_y=1320, font="Anton", size=92, upper=True, outline=7, max_chars=22, max_words=3):
    marginv = H - bottom_y
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\n\n"
            f"[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
            f"Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,{outline},2,2,60,60,{marginv},1\n\n"
            f"[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    lines = []
    chunks = chunk(words, max_words=max_words, max_chars=max_chars)
    for i, c in enumerate(chunks):
        start = c[0][0]
        end = chunks[i + 1][0][0] if i + 1 < len(chunks) and chunks[i + 1][0][0] - c[-1][1] < 0.4 else c[-1][1] + 0.15
        text = " ".join(x[2] for x in c)
        text = (text.upper() if upper else text).replace("\n", " ")
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{text}")
    Path(path).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)
