#!/usr/bin/env python3
"""Long video -> the N best clips (Whisper + Claude) -> 9:16 clips with captions + banner + post descriptions.
Prints progress lines (STAGE / PCT / NOTE / CLIP) that app.py turns into the UI."""
import argparse, json, re, subprocess, sys
from pathlib import Path

import captions, llm
from compose import FFMPEG, probe_duration

HERE = Path(__file__).resolve().parent

def emit(tag, payload=""):
    print(f"{tag} {payload}", flush=True)

def to_sentences(words, max_words=28, gap=0.9):
    out, cur = [], []
    def flush():
        if cur:
            out.append({"i": len(out), "start": cur[0][0], "end": cur[-1][1], "text": " ".join(w[2] for w in cur)})
    for w in words:
        if cur and (w[0] - cur[-1][1] > gap or len(cur) >= max_words):
            flush(); cur = []
        cur.append(w)
        if re.search(r"[.!?…]$", w[2]):
            flush(); cur = []
    flush()
    return out

def resolve(clips, sents, lo, total, n, min_len, max_len):
    """Turn Claude's sentence ranges into clip times. Near misses are fixed instead of dropped:
    too long -> cut sentences off the end (keeps the hook), too short -> pull in the following sentences."""
    by = {s["i"]: s for s in sents}
    last = max(by) if by else -1
    hi = max_len * 1.15
    ok = []
    for c in clips:
        try:
            ia, ib = int(c.get("start_id")), int(c.get("end_id"))
        except (TypeError, ValueError):
            continue
        if ia > ib:
            ia, ib = ib, ia
        if ia not in by or ib not in by:
            continue
        while ib > ia and by[ib]["end"] - by[ia]["start"] > hi:
            ib -= 1
        while ib < last and by[ib]["end"] - by[ia]["start"] < min_len * 0.85 and by[ib + 1]["end"] - by[ia]["start"] <= hi:
            ib += 1
        st, en = max(lo, by[ia]["start"] - 0.25), min(total, by[ib]["end"] + 0.4)
        if not (min_len * 0.6 <= en - st <= max_len * 1.4):
            continue
        ok.append({**c, "start": st, "end": en})
    ok.sort(key=lambda c: -c.get("score", 0))
    kept = []
    for c in ok:
        if all(c["end"] <= k["start"] or c["start"] >= k["end"] for k in kept):
            kept.append(c)
    return sorted(kept[:n], key=lambda c: c["start"])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source"); ap.add_argument("banner"); ap.add_argument("outdir")
    ap.add_argument("--layout", default="blur")
    ap.add_argument("--captions", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--language", default=None)
    ap.add_argument("--offset", type=float, default=0, help="start second of the range to analyse")
    ap.add_argument("--limit-sec", type=float, default=0, help="length of the range in seconds (0 = to the end)")
    ap.add_argument("--max-clips", type=int, default=5)
    ap.add_argument("--min-len", type=float, default=15)
    ap.add_argument("--max-len", type=float, default=60)
    ap.add_argument("--desc-lang", default="")
    ap.add_argument("--caption-size", default="normal")
    ap.add_argument("--hook", action=argparse.BooleanOptionalAction, default=False)
    ap.add_argument("--crop-fix", action=argparse.BooleanOptionalAction, default=False)
    ap.add_argument("--manual", action=argparse.BooleanOptionalAction, default=False,
                    help="the clip is exactly --offset .. --offset+--limit-sec (no AI picking)")
    ap.add_argument("--describe", action=argparse.BooleanOptionalAction, default=False,
                    help="manual mode: Claude writes title + description for the chosen part")
    a = ap.parse_args()

    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    need_ai = a.hook or a.describe
    if not a.manual and not llm.get_key():
        sys.exit("No Anthropic API key found. Run: python setkey.py (in a terminal)")
    if a.manual:
        if not a.limit_sec:
            sys.exit("choose a start and an end for the part")
        if need_ai and not llm.get_key():              # the clip itself does not need AI: carry on without the extra text
            emit("NOTE", "no Anthropic key: skipped the title / description / hook (run: python setkey.py)")
            need_ai, a.hook, a.describe = False, False, False
    need_words = (not a.manual) or a.captions or need_ai

    words, lang, wjson = [], None, None
    if need_words:
        emit("STAGE", "extracting audio")
        wav = out / "audio.wav"
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", *(["-ss", str(a.offset)] if a.offset else []), "-i", a.source,
                        *(["-t", str(a.limit_sec)] if a.limit_sec else []),
                        "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
        span = probe_duration(str(wav))
        total = a.offset + span          # all times below are in source-video seconds

        emit("STAGE", "transcribing")
        words, lang = captions.transcribe_words(str(wav), a.whisper_model, a.language,
                                                on_progress=lambda t: emit("PCT", f"{min(99.0, t / span * 100):.1f}"))
        if not words and not a.manual:
            sys.exit("no speech found in this video")
        words = [(s + a.offset, e + a.offset, t) for s, e, t in words]
        if words:
            wjson = out / "words.json"
            captions.save_words(words, lang, wjson)
        emit("NOTE", f"{len(words)} words, {span / 60:.1f} min analysed (from {a.offset / 60:.1f}), language={lang}")
    else:                                                # manual clip, no captions, no AI: nothing to transcribe
        total = min(a.offset + a.limit_sec, probe_duration(a.source))

    if a.manual:
        c = {"start": a.offset, "end": total, "title": "", "description": "", "hook": ""}
        if need_ai and words:
            emit("STAGE", "writing the text (claude)"); emit("PCT", "0")
            try:
                info, u = llm.describe_clip(" ".join(w[2] for w in words), a.desc_lang, want_hook=a.hook)
                c.update(info)
                emit("NOTE", f"claude: about ${u['usd']:.4f} ({u['model']})")
            except Exception as e:                       # the clip is still made without the text
                emit("NOTE", f"title / description skipped ({e})")
        chosen = [c]
    else:
        sents = to_sentences(words)
        emit("STAGE", "picking clips (claude)"); emit("PCT", "0")
        clips, u = llm.pick_clips(sents, a.max_clips, a.min_len, a.max_len, a.desc_lang, want_hook=a.hook)
        emit("NOTE", f"claude: {u['in']} tokens in, {u['out']} out = about ${u['usd']:.3f} ({u['model']})")
        chosen = resolve(clips, sents, a.offset, total, a.max_clips, a.min_len, a.max_len)
        if not chosen:
            sys.exit("claude found no clips that fit the length limits")
    (out / "clips.json").write_text(json.dumps(chosen, ensure_ascii=False, indent=1), encoding="utf-8")
    use_captions = a.captions and bool(wjson)

    for k, c in enumerate(chosen, 1):
        emit("STAGE", f"rendering clip {k}/{len(chosen)}")
        f = out / f"clip_{k}.mp4"
        cmd = [sys.executable, str(HERE / "compose.py"), a.source, a.banner, str(f), "--layout", a.layout,
               "--start", f"{c['start']:.3f}", "--end", f"{c['end']:.3f}",
               *(["--words-json", str(wjson)] if wjson else []),
               "--captions" if use_captions else "--no-captions", "--crop-fix" if a.crop_fix else "--no-crop-fix", "--caption-size", a.caption_size,
               *(["--hook", c["hook"]] if a.hook and c.get("hook") else [])]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        dur = c["end"] - c["start"]
        for line in p.stdout:
            line = line.strip()
            if line.startswith("out_time_us="):
                try: emit("PCT", f"{min(99.0, ((k - 1) + int(line.split('=')[1]) / 1e6 / dur) / len(chosen) * 100):.1f}")
                except ValueError: pass
            elif line and "=" not in line and not line.startswith(("STAGE", "DURATION")) and not re.search(r"warn|tip:|^INFO:|^[IWE]\d{4} |^objc\[", line, re.I):
                print(line, flush=True)
        if p.wait() != 0 or not f.exists():
            sys.exit(f"render of clip {k} failed")
        emit("CLIP", json.dumps({"file": str(f), "title": c.get("title", ""), "description": c.get("description", ""),
                                  "reason": c.get("reason", ""), "hook": c.get("hook", "") if a.hook else "", "start": round(c["start"], 1), "end": round(c["end"], 1)},
                                 ensure_ascii=False))

if __name__ == "__main__":
    main()
