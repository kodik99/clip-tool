"""'Crop corrector': when cropping 16:9 -> 9:16, choose ONE fixed crop position per camera shot so a person is never
cut off. No following / panning. With several people it keeps one (the most prominent) and avoids leaving a
half-cut second face at the edge. Face detection: MediaPipe BlazeFace (small model, downloaded on first use)."""
import re, subprocess, sys, urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_detector/"
             "blaze_face_short_range/float16/1/blaze_face_short_range.tflite")
MODEL_PATH = HERE / "models" / "blaze_face_short_range.tflite"
SCAN_W = 640          # frames are scanned at this width
MAX_FRAMES = 500      # cap for very long inputs


def ensure_model():
    if not MODEL_PATH.exists():
        MODEL_PATH.parent.mkdir(exist_ok=True)
        print(f"NOTE downloading face model (one time) -> {MODEL_PATH.name}", flush=True)
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return str(MODEL_PATH)


def shot_cuts(ffmpeg, src, start, dur, thresh=0.3, min_len=1.0):
    """Shot boundaries (seconds, relative to the start of the clip)."""
    cmd = [ffmpeg, "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src,
           "-vf", f"scale=320:-2,select='gt(scene,{thresh})',showinfo", "-an", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    cuts = sorted(float(m.group(1)) for m in re.finditer(r"pts_time:([\d.]+)", err))
    out = [0.0]
    for c in cuts:
        if c - out[-1] >= min_len and dur - c >= min_len:
            out.append(c)
    out.append(dur)
    return out


def scan_faces(ffmpeg, src, start, dur, W, H):
    """Yield (t, [(x1, x2, area), ...]) in SOURCE pixels for frames sampled across the clip."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import FaceDetector, FaceDetectorOptions, RunningMode
    det = FaceDetector.create_from_options(FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=ensure_model()),
        running_mode=RunningMode.IMAGE, min_detection_confidence=0.5))
    sw = SCAN_W
    sh = int(round(H * sw / W / 2)) * 2
    k = W / sw
    fps = max(0.2, min(2.0, MAX_FRAMES / max(dur, 1)))
    cmd = [ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src,
           "-vf", f"fps={fps},scale={sw}:{sh}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size, i = sw * sh * 3, 0
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        frame = np.frombuffer(buf, np.uint8).reshape(sh, sw, 3)
        res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=frame))
        faces = []
        for d in res.detections:
            b = d.bounding_box
            faces.append((b.origin_x * k, (b.origin_x + b.width) * k, b.width * b.height * k * k))
        yield i / fps, faces
        i += 1
    p.wait()


def _clusters(dets):
    """Group detections of the same person (similar x position). -> [[x1, x2, score], ...] best first."""
    cl = []
    for x1, x2, area in sorted(dets, key=lambda d: -d[2]):
        c = (x1 + x2) / 2
        for g in cl:
            if abs(g["c"] - c) < 0.6 * g["w"]:
                g["items"].append((x1, x2, area)); break
        else:
            cl.append({"c": c, "w": x2 - x1, "items": [(x1, x2, area)]})
    out = []
    for g in cl:
        out.append([float(np.median([i[0] for i in g["items"]])), float(np.median([i[1] for i in g["items"]])),
                    sum(i[2] for i in g["items"])])
    return sorted(out, key=lambda g: -g[2])


def choose_x(main, others, W, cw, margin=0.2):
    """Crop x (left edge) that keeps `main` fully inside, as centred as possible, without half-cut other faces."""
    mw = main[1] - main[0]
    ideal = min(max((main[0] + main[1]) / 2 - cw / 2, 0), W - cw)
    lo, hi = max(0.0, main[1] + mw * margin - cw), min(W - cw, main[0] - mw * margin)
    if lo > hi:
        return ideal
    best, best_s = ideal, None
    for x in np.arange(lo, hi + 1, 4.0):
        s = abs(x - ideal)
        for o in others:
            frac = max(0.0, min(o[1], x + cw) - max(o[0], x)) / max(1.0, o[1] - o[0])
            if 0.04 < frac < 0.96:
                s += 1000            # a second face cut in half at the edge looks worst
        if best_s is None or s < best_s:
            best, best_s = float(x), s
    return best


def plan(ffmpeg, src, start, dur, W, H):
    """Returns None (source not wider than 9:16) or {'cw','ch','segs':[(t_end, x)], 'shots','with_faces'}."""
    cw = int(round(H * 9 / 16 / 2)) * 2
    if cw >= W:
        return None
    cuts = shot_cuts(ffmpeg, src, start, dur)
    shots = list(zip(cuts[:-1], cuts[1:]))
    dets = [[] for _ in shots]
    for t, faces in scan_faces(ffmpeg, src, start, dur, W, H):
        for j, (t0, t1) in enumerate(shots):
            if t0 <= t < t1:
                dets[j].extend(faces); break
    segs, with_faces = [], 0
    for (t0, t1), d in zip(shots, dets):
        cl = _clusters(d)
        if cl:
            with_faces += 1
            others = [g for g in cl[1:] if g[2] >= 0.3 * cl[0][2]]
            x = choose_x(cl[0], others, W, cw)
        else:
            x = (W - cw) / 2          # no face found: plain centre crop
        x = int(round(x / 2)) * 2
        if segs and abs(segs[-1][1] - x) < 8:
            segs[-1] = (t1, segs[-1][1])
        else:
            segs.append((t1, x))
    return {"cw": cw, "ch": H, "segs": segs, "shots": len(shots), "with_faces": with_faces}


def x_expr(segs):
    expr = str(segs[-1][1])
    for t_end, x in reversed(segs[:-1]):
        expr = f"if(lt(t,{t_end:.3f}),{x},{expr})"
    return expr
