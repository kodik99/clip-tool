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
SCAN_W = 1280         # frames are scanned at up to this width (small faces in wide shots need resolution)
MIN_CONF = 0.5        # detection confidence threshold (real faces score >=0.5; false hits on furniture score ~0.2-0.49)
MIN_HIT = 0.3        # a face must show up in at least this share of a shot's frames to count
SAME_ANGLE = 14.0     # max mean pixel difference for two shots to count as the same camera angle
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


def _tiles(sw, sh):
    """Overlapping square tiles (side = frame height) covering the frame width."""
    if sw <= sh * 1.15:
        return [0]
    n = int(np.ceil((sw - sh) / (sh * 0.6))) + 1
    return [int(round(x)) for x in np.linspace(0, sw - sh, n)]


def scan_faces(ffmpeg, src, start, dur, W, H):
    """Yield (t, [(x1, x2, area), ...], signature) for frames sampled across the clip (SOURCE pixels).
    Small faces in wide shots are found by scanning at up to 1280 px wide in overlapping square tiles."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import FaceDetector, FaceDetectorOptions, RunningMode
    det = FaceDetector.create_from_options(FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=ensure_model()),
        running_mode=RunningMode.IMAGE, min_detection_confidence=MIN_CONF))
    sw = min(W, SCAN_W)
    sh = int(round(H * sw / W / 2)) * 2
    k = W / sw
    xs = _tiles(sw, sh)
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
        def run(tile, x0):
            out = []
            for d in det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(tile))).detections:
                b = d.bounding_box
                out.append((b.origin_x + x0, b.origin_x + x0 + b.width, b.width * b.height))
            return out
        found = []
        for x0 in xs:
            found += run(frame[:, x0:x0 + sh] if len(xs) > 1 else frame, x0)
        if not found:                      # nothing big: look again with small tiles so far-away faces look bigger
            small = sh // 2
            for y0 in (0, small // 2):
                for x0 in range(0, sw - small + 1, small // 2):
                    found += run(frame[y0:y0 + small, x0:x0 + small], x0)
        faces = []                                   # merge duplicates seen in two overlapping tiles
        for x1, x2, a in sorted(found, key=lambda f: -f[2]):
            c = (x1 + x2) / 2
            if all(abs(c - (f[0] + f[1]) / 2) > 0.5 * (x2 - x1) for f in faces):
                faces.append((x1, x2, a))
        sig = frame[::45, ::80].mean(axis=2)         # tiny picture of the shot, to recognise repeated camera angles
        yield i / fps, [(x1 * k, x2 * k, a * k * k) for x1, x2, a in faces], sig
        i += 1
    p.wait()


def _clusters(dets, n_frames):
    """Group detections of the same person (similar x position). Returns [[x1, x2, hits, mean_area], ...] best first.
    Ranked by how consistently the person is seen, not by size (a big one-off false hit must not beat a small real face);
    among near-equal candidates the larger (closer) face wins. Clusters seen in too few frames are dropped."""
    cl = []
    for x1, x2, area in sorted(dets, key=lambda d: -d[2]):
        c = (x1 + x2) / 2
        for g in cl:
            if abs(g["c"] - c) < 0.6 * g["w"]:
                g["items"].append((x1, x2, area)); break
        else:
            cl.append({"c": c, "w": x2 - x1, "items": [(x1, x2, area)]})
    out = [[float(np.median([i[0] for i in g["items"]])), float(np.median([i[1] for i in g["items"]])),
            len(g["items"]), float(np.mean([i[2] for i in g["items"]]))] for g in cl]
    out = [g for g in out if g[2] >= max(1, MIN_HIT * n_frames)]
    if not out:
        return []
    top = max(g[2] for g in out)
    strong = sorted([g for g in out if g[2] >= 0.7 * top], key=lambda g: -g[3])
    weak = sorted([g for g in out if g[2] < 0.7 * top], key=lambda g: -g[2])
    return strong + weak


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
    """Returns None (source not wider than 9:16) or {'cw','ch','segs':[(t_end, x)], 'shots', 'with_faces', 'reused', 'centred'}."""
    cw = int(round(H * 9 / 16 / 2)) * 2
    if cw >= W:
        return None
    cuts = shot_cuts(ffmpeg, src, start, dur)
    shots = list(zip(cuts[:-1], cuts[1:]))
    dets = [[] for _ in shots]
    sigs = [[] for _ in shots]
    for t, faces, sig in scan_faces(ffmpeg, src, start, dur, W, H):
        for j, (t0, t1) in enumerate(shots):
            if t0 <= t < t1:
                dets[j].extend(faces); sigs[j].append(sig); break
    sig_of = [np.mean(s, axis=0) if s else None for s in sigs]
    xs = []                                  # per shot: (x or None, weight = how much evidence)
    for d, sg in zip(dets, sigs):
        cl = _clusters(d, len(sg))
        if cl:
            others = [g for g in cl[1:] if g[2] >= 0.5 * cl[0][2]]
            xs.append((choose_x(cl[0], others, W, cw), len(d)))
        else:
            xs.append((None, 0))
    with_faces = sum(1 for x, _ in xs if x is not None)
    reused = centred = 0
    final = []
    for j, (x, _) in enumerate(xs):
        if x is None:                        # no face here: borrow the crop from the same camera angle, else centre
            best, best_d = None, SAME_ANGLE
            for m, (xm, wm) in enumerate(xs):
                if xm is not None and sig_of[j] is not None and sig_of[m] is not None:
                    dist = float(np.abs(sig_of[j] - sig_of[m]).mean())
                    if dist < best_d:
                        best, best_d = xm, dist
            if best is not None:
                x = best; reused += 1
            else:
                x = (W - cw) / 2; centred += 1
        final.append(int(round(x / 2)) * 2)
    segs = []
    for (t0, t1), x in zip(shots, final):
        if segs and abs(segs[-1][1] - x) < 8:
            segs[-1] = (t1, segs[-1][1])
        else:
            segs.append((t1, x))
    return {"cw": cw, "ch": H, "segs": segs, "shots": len(shots), "with_faces": with_faces,
            "reused": reused, "centred": centred}


def x_expr(segs):
    expr = str(segs[-1][1])
    for t_end, x in reversed(segs[:-1]):
        expr = f"if(lt(t,{t_end:.3f}),{x},{expr})"
    return expr
