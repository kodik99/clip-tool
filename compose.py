#!/usr/bin/env python3
"""Turn a (short) video into a 9:16 clip: blurred-fill background, fitted video, captions, looping banner."""
import argparse, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

def _find(name):
    """ffmpeg/ffprobe: $FFMPEG_DIR, then ./tools/bin, then PATH."""
    import os, shutil
    for d in (os.environ.get("FFMPEG_DIR"), str(HERE / "tools/bin")):
        if d and (Path(d) / name).exists():
            return str(Path(d) / name)
    found = shutil.which(name)
    if not found:
        sys.exit(f"{name} not found. Install ffmpeg (with libass) - see README.")
    return found

FFMPEG = _find("ffmpeg")
FFPROBE = _find("ffprobe")
FONTS = str(HERE / "fonts")
W, H = 1080, 1920
HOOK_TOP = 170      # top of the headline: below the TikTok / Reels top UI
CAPTION_STYLES = {   # font size / outline in px on the 1080x1920 frame; shorter lines for the big text
    "normal": dict(size=92, outline=7, max_chars=22, max_words=3),
    "large": dict(size=128, outline=9, max_chars=15, max_words=2),
}

def probe_size(path):
    out = subprocess.check_output([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=width,height", "-of", "csv=p=0", path], text=True).strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)

def probe_duration(path):
    out = subprocess.check_output([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", path], text=True).strip()
    return float(out)

def build_filter(layout, bw, banner_y, video_cy, ass=None, crop=None, hook_y=None):
    if layout == "blur":
        main = (f"[0:v]split[a][b];"
                f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:6[bg];"
                f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:{video_cy}-h/2[base]")
    elif layout == "crop" and crop:     # crop corrector: fixed, face-safe crop position per shot
        import reframe
        main = f"[0:v]crop={crop['cw']}:{crop['ch']}:x='{reframe.x_expr(crop['segs'])}':y=0,scale={W}:{H}[base]"
    elif layout == "crop":
        main = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}[base]"
    cur = "base"
    if ass:
        esc = ass.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        main += f";[base]subtitles='{esc}':fontsdir='{FONTS}'[cap]"
        cur = "cap"
    if hook_y is not None:                                   # hook headline image = input #2, full width
        main += f";[2:v]format=rgba[hk];[{cur}][hk]overlay=0:{hook_y}:shortest=1[hkd]"
        cur = "hkd"
    return main + f";[1:v]scale={bw}:-2,fps=30[ban];[{cur}][ban]overlay=(W-w)/2:{banner_y}:shortest=1[v]"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("input"); p.add_argument("banner"); p.add_argument("output")
    p.add_argument("--layout", choices=["blur", "crop"], default="blur")
    p.add_argument("--banner-scale", type=float, default=0.65, help="banner width / frame width")
    p.add_argument("--banner-bottom", type=int, default=280, help="px from banner bottom to frame bottom")
    p.add_argument("--video-center-y", type=int, default=720, help="vertical centre of the video block (blur)")
    p.add_argument("--captions", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--caption-size", choices=["normal", "large"], default="normal")
    p.add_argument("--whisper-model", default="small")
    p.add_argument("--language", default=None)
    p.add_argument("--start", type=float, default=None, help="cut: start second in the input")
    p.add_argument("--end", type=float, default=None, help="cut: end second in the input")
    p.add_argument("--crop-fix", action=argparse.BooleanOptionalAction, default=False,
                   help="crop layout only: pick a face-safe crop position per shot")
    p.add_argument("--hook", default=None, help="headline text to draw above the video (with emojis)")
    p.add_argument("--hook-auto", action=argparse.BooleanOptionalAction, default=False,
                   help="let Claude write the headline from the transcript (needs an API key)")
    p.add_argument("--desc-lang", default="", help="language for the AI headline (default: same as the video)")
    p.add_argument("--words-json", default=None, help="reuse an existing transcript instead of running Whisper")
    a = p.parse_args()

    bw_src, bh_src = probe_size(a.banner)
    bw = int(W * a.banner_scale) // 2 * 2
    bh = round(bw * bh_src / bw_src)
    banner_y = H - a.banner_bottom - bh
    ass = None
    cut = a.start is not None and a.end is not None
    dur = (a.end - a.start) if cut else probe_duration(a.input)
    print(f"DURATION {dur}", flush=True)
    crop = None
    if a.layout == "crop" and a.crop_fix:
        import reframe
        print("STAGE checking framing", flush=True)
        sw_, sh_ = probe_size(a.input)
        try:
            crop = reframe.plan(FFMPEG, a.input, a.start if cut else 0.0, dur, sw_, sh_)
            if crop: print(f"NOTE crop corrector: {crop['shots']} shot(s): face found in {crop['with_faces']}, "
                                  f"same-angle reuse {crop['reused']}, centre fallback {crop['centred']}", flush=True)
        except Exception as e:      # never fail the render because of framing; fall back to a centre crop
            print(f"NOTE crop corrector skipped ({e})", flush=True)
    words = lang = None
    if a.captions or (a.hook_auto and not a.hook):
        import captions
        if a.words_json:
            words, lang = captions.load_words(a.words_json)
            if cut:
                words = captions.window(words, a.start, a.end)
        else:
            print("STAGE transcribing", flush=True)
            words, lang = captions.transcribe_words(a.input, a.whisper_model, a.language)
        if a.captions:
            if words:
                ass = str(Path(a.output).with_suffix(".ass"))
                n = captions.write_ass(words, ass, W, H, bottom_y=banner_y - 40, **CAPTION_STYLES[a.caption_size])
                print(f"captions: {n} lines, language={lang}", file=sys.stderr)
            else:
                print("captions: no speech detected", file=sys.stderr)
    # ---- hook headline (text + colour emojis rendered as an image above the video)
    hook_text, hook_y, video_cy = a.hook, None, a.video_center_y
    if not hook_text and a.hook_auto and words:
        try:
            import llm
            print("STAGE writing hook", flush=True)
            hook_text, u = llm.make_hook(" ".join(w[2] for w in words), a.desc_lang)
            print(f"NOTE hook: {hook_text}  (about ${u['usd']:.4f})", flush=True)
        except Exception as e:                                # never fail the render because of the headline
            print(f"NOTE hook skipped ({e})", flush=True)
    hook_png = None
    if hook_text:
        import hook
        sw_, sh_ = probe_size(a.input)
        shown_h = sh_ * min(W / sw_, H / sh_)                 # height of the video block in the frame
        over_video = a.layout == "crop" or shown_h > 1000     # headline sits on the picture -> add a soft dark gradient
        hook_png = str(Path(a.output).with_suffix(".hook.png"))
        size = hook.render_hook(hook_text, hook_png, backdrop=over_video, pad_top=HOOK_TOP if over_video else 0)
        if size:
            hook_y = 0 if over_video else HOOK_TOP
            if not over_video:                                # keep the video block below the headline
                video_cy = int(max(video_cy, HOOK_TOP + size[1] + 20 + shown_h / 2))
        else:
            hook_png = None
    print("STAGE rendering", flush=True)
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
           *(["-ss", f"{a.start:.3f}", "-t", f"{dur:.3f}"] if cut else []),
           "-i", a.input, "-stream_loop", "-1", "-i", a.banner,
           *(["-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", hook_png] if hook_png else []),
           "-filter_complex", build_filter(a.layout, bw, banner_y, video_cy, ass, crop, hook_y if hook_png else None),
           "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", a.output]
    sys.exit(subprocess.run(cmd).returncode)

if __name__ == "__main__":
    main()
