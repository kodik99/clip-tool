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

def probe_size(path):
    out = subprocess.check_output([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=width,height", "-of", "csv=p=0", path], text=True).strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)

def probe_duration(path):
    out = subprocess.check_output([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", path], text=True).strip()
    return float(out)

def build_filter(layout, bw, banner_y, video_cy, ass=None):
    if layout == "blur":
        main = (f"[0:v]split[a][b];"
                f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:6[bg];"
                f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:{video_cy}-h/2[base]")
    elif layout == "crop":
        main = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}[base]"
    else:
        main = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:{video_cy}-ih/2:black[base]")
    cur = "base"
    if ass:
        esc = ass.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        main += f";[base]subtitles='{esc}':fontsdir='{FONTS}'[cap]"
        cur = "cap"
    return main + f";[1:v]scale={bw}:-2,fps=30[ban];[{cur}][ban]overlay=(W-w)/2:{banner_y}:shortest=1[v]"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("input"); p.add_argument("banner"); p.add_argument("output")
    p.add_argument("--layout", choices=["blur", "crop", "fit"], default="blur")
    p.add_argument("--banner-scale", type=float, default=0.65, help="banner width / frame width")
    p.add_argument("--banner-bottom", type=int, default=280, help="px from banner bottom to frame bottom")
    p.add_argument("--video-center-y", type=int, default=720, help="vertical centre of the video block (blur/fit)")
    p.add_argument("--captions", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--whisper-model", default="small")
    p.add_argument("--language", default=None)
    a = p.parse_args()

    bw_src, bh_src = probe_size(a.banner)
    bw = int(W * a.banner_scale) // 2 * 2
    bh = round(bw * bh_src / bw_src)
    banner_y = H - a.banner_bottom - bh
    ass = None
    print(f"DURATION {probe_duration(a.input)}", flush=True)
    if a.captions:
        print("STAGE transcribing", flush=True)
        import captions
        words, lang = captions.transcribe_words(a.input, a.whisper_model, a.language)
        if words:
            ass = str(Path(a.output).with_suffix(".ass"))
            n = captions.write_ass(words, ass, W, H, bottom_y=banner_y - 40)
            print(f"captions: {n} lines, language={lang}", file=sys.stderr)
        else:
            print("captions: no speech detected", file=sys.stderr)
    print("STAGE rendering", flush=True)
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
           "-i", a.input, "-stream_loop", "-1", "-i", a.banner,
           "-filter_complex", build_filter(a.layout, bw, banner_y, a.video_center_y, ass),
           "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", a.output]
    sys.exit(subprocess.run(cmd).returncode)

if __name__ == "__main__":
    main()
