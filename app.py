"""Tiny local web UI: paste a link or drop a file -> 9:16 clip with blurred fill, captions and looping banner."""
import json, re, shutil, signal, subprocess, sys, threading, queue, time, uuid
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

HERE = Path(__file__).resolve().parent
BANNERS, OUTPUT, JOBS_DIR = HERE / "banners", HERE / "output", HERE / "jobs"
for d in (BANNERS, OUTPUT, JOBS_DIR):
    d.mkdir(exist_ok=True)
for _item in JOBS_DIR.iterdir():  # jobs live in memory only, so anything here is a leftover
    shutil.rmtree(_item, ignore_errors=True) if _item.is_dir() else _item.unlink()
import os, shutil as _sh
ENV = {**os.environ, "PATH": "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")}  # lets yt-dlp find deno + ffmpeg

app = FastAPI()
jobs: dict[str, dict] = {}
order: list[str] = []
q: "queue.Queue[str]" = queue.Queue()
procs: dict[str, subprocess.Popen] = {}

def _spawn(jid, cmd):
    """Run a job step in its own process group so 'kill' also stops ffmpeg / yt-dlp / whisper children."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=ENV, start_new_session=True)
    procs[jid] = p
    return p

def _killpg(p, sig):
    try: os.killpg(os.getpgid(p.pid), sig)
    except (ProcessLookupError, PermissionError): pass

def _ffmpeg_dir() -> str:
    for d in (os.environ.get("FFMPEG_DIR"), str(HERE / "tools/bin")):
        if d and (Path(d) / "ffmpeg").exists():
            return d
    found = _sh.which("ffmpeg", path=ENV["PATH"])
    return str(Path(found).parent) if found else ""

def parse_time(s: str):
    """'' -> None; '20' -> 20 min; 'm:ss' or 'h:mm:ss' -> seconds."""
    s = s.strip()
    if not s: return None
    try: n = [float(p) for p in s.split(":")]
    except ValueError: raise HTTPException(400, f"bad time '{s}' (use 20, 12:30 or 1:05:30)")
    if len(n) == 1: return n[0] * 60
    if len(n) == 2: return n[0] * 60 + n[1]
    if len(n) == 3: return n[0] * 3600 + n[1] * 60 + n[2]
    raise HTTPException(400, f"bad time '{s}'")

def safe_name(name: str) -> str:
    name = Path(name).name
    return re.sub(r"[^\w.\- ]", "_", name) or "file"

def log(job, line):
    line = line.rstrip()
    if line:
        job["log"] = (job["log"] + [line])[-30:]

def _save_meta(job):
    """Keep finished jobs (titles, descriptions, clip files) across server restarts."""
    meta = {k: v for k, v in job.items() if k not in ("opts", "log", "finished", "cancelled")}
    (OUTPUT / f"{job['id']}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

def _load_meta():
    for f in sorted(OUTPUT.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
            if all((OUTPUT / o["file"]).exists() for o in j["outputs"]):
                jobs[j["id"]] = {**j, "log": [], "opts": {}}; order.insert(0, j["id"])
            else:
                f.unlink()
        except Exception:
            pass

def run_job(jid):
    job = jobs[jid]; o = job["opts"]
    wd = JOBS_DIR / jid; wd.mkdir(exist_ok=True)
    job["status"] = "running"
    try:
        src = wd / "source.mp4"
        if o.get("upload"):
            src = Path(o["upload"])
        else:
            job["stage"], job["pct"] = "downloading", 0
            cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--newline", "--ffmpeg-location", _ffmpeg_dir(),
                   "-f", "bv*[height<=1080][vcodec^=avc1]+ba/bv*[height<=1080]+ba/b", "--merge-output-format", "mp4",
                   "-o", str(wd / "source.%(ext)s"), o["url"]]
            p = _spawn(jid, cmd)
            for line in p.stdout:
                if job.get("cancelled"): break
                m = re.search(r"\[download\]\s+([\d.]+)%", line)
                if m: job["pct"] = float(m.group(1))
                else: log(job, line)
            if job.get("cancelled"): raise RuntimeError("killed")
            if p.wait() != 0 or not src.exists():
                raise RuntimeError("download failed")
        if o["mode"] == "clips":
            cmd = [sys.executable, str(HERE / "findclips.py"), str(src), str(BANNERS / o["banner"]), str(wd / "clips"),
                   "--layout", o["layout"], "--whisper-model", o["model"], "--max-clips", str(o["max_clips"]),
                   "--min-len", str(o["min_len"]), "--max-len", str(o["max_len"]), "--desc-lang", o["desc_lang"],
                   "--captions" if o["captions"] else "--no-captions", "--crop-fix" if o.get("crop_fix") else "--no-crop-fix", "--caption-size", o["cap_size"], "--hook" if o.get("hook") else "--no-hook"]
            cmd += ["--offset", str(o.get("start_sec") or 0)]
            if o.get("end_sec"): cmd += ["--limit-sec", str(o["end_sec"] - (o.get("start_sec") or 0))]
        else:
            cmd = [sys.executable, str(HERE / "compose.py"), str(src), str(BANNERS / o["banner"]), str(wd / "out.mp4"),
                   "--layout", o["layout"], "--whisper-model", o["model"],
                   "--captions" if o["captions"] else "--no-captions", "--crop-fix" if o.get("crop_fix") else "--no-crop-fix",
                   "--caption-size", o["cap_size"], "--hook-auto" if o.get("hook") else "--no-hook-auto", "--desc-lang", o["desc_lang"]]
        if o.get("language"): cmd += ["--language", o["language"]]
        p = _spawn(jid, cmd)
        dur = 0.0
        job["stage"], job["pct"] = "starting", 0
        for line in p.stdout:
            if job.get("cancelled"): break
            line = line.strip()
            if line.startswith("DURATION "): dur = float(line.split()[1])
            elif line.startswith("STAGE "): job["stage"], job["pct"] = line[6:], 0
            elif line.startswith("PCT "): job["pct"] = float(line[4:])
            elif line.startswith("NOTE "): job["note"] = (job["note"] + "\n" + line[5:]).strip()
            elif line.startswith("CLIP "):
                c = json.loads(line[5:]); final = f"{jid}_{len(job['outputs']) + 1}.mp4"
                shutil.move(c["file"], OUTPUT / final)
                job["outputs"].append({**c, "file": final})
            elif line.startswith("out_time_us=") and dur:
                try: job["pct"] = min(99.0, int(line.split("=")[1]) / 1e6 / dur * 100)
                except ValueError: pass
            elif "=" in line and line.split("=")[0] in ("frame", "fps", "stream_0_0_q", "bitrate", "total_size", "out_time", "out_time_ms",
                                                         "dup_frames", "drop_frames", "speed", "progress"):
                pass
            elif not re.search(r"warn|tip:|^INFO:|^[IWE]\d{4} |^objc\[", line, re.I): log(job, line)
        if job.get("cancelled"): raise RuntimeError("killed")
        if p.wait() != 0:
            raise RuntimeError("clip finder failed" if o["mode"] == "clips" else "render failed")
        if o["mode"] != "clips":
            out = wd / "out.mp4"
            if not out.exists(): raise RuntimeError("render failed")
            final = f"{jid}.mp4"; shutil.move(str(out), OUTPUT / final)
            job["outputs"].append({"file": final, "title": "", "description": ""})
        if not job["outputs"]: raise RuntimeError("no clips produced")
        job.update(status="done", stage="done", pct=100)
        _save_meta(job)
    except Exception as e:
        job.update(status="error", stage="error")
        log(job, f"error: {e}")
    finally:
        shutil.rmtree(wd, ignore_errors=True)  # never keep the downloaded source / audio / scratch files
        procs.pop(jid, None)
        job["finished"] = True

def worker():
    while True:
        jid = q.get()
        job = jobs.get(jid)
        if job is None or job.get("cancelled"):   # killed while still waiting in the queue
            continue
        run_job(jid)

_load_meta()
threading.Thread(target=worker, daemon=True).start()

@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "index.html").read_text(encoding="utf-8")

@app.get("/api/banners")
def banners():
    return sorted(p.name for p in BANNERS.glob("*.mp4"))

@app.post("/api/banners")
async def upload_banner(file: UploadFile = File(...)):
    name = safe_name(file.filename or "banner.mp4")
    if not name.lower().endswith(".mp4"):
        raise HTTPException(400, "banner must be .mp4")
    with open(BANNERS / name, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"name": name}

@app.post("/api/jobs")
async def create_job(url: str = Form(""), banner: str = Form(...), layout: str = Form("blur"),
                     captions: bool = Form(True), crop_fix: bool = Form(False), hook: bool = Form(False), cap_size: str = Form("normal"), model: str = Form("small"), language: str = Form(""),
                     mode: str = Form("whole"), t_from: str = Form(""), t_to: str = Form(""), max_clips: int = Form(5),
                     min_len: float = Form(15), max_len: float = Form(60), desc_lang: str = Form(""),
                     file: UploadFile | None = File(None)):
    if mode not in ("whole", "clips"): raise HTTPException(400, "bad mode")
    if layout not in ("blur", "crop"): raise HTTPException(400, "bad layout")
    if cap_size not in ("normal", "large"): raise HTTPException(400, "bad caption size")
    if model not in ("tiny", "base", "small", "medium"): raise HTTPException(400, "bad model")
    if not (BANNERS / Path(banner).name).exists(): raise HTTPException(400, "banner not found")
    jid = uuid.uuid4().hex[:8]
    start_sec, end_sec = parse_time(t_from), parse_time(t_to)
    if end_sec is not None and end_sec <= (start_sec or 0): raise HTTPException(400, "'to' must be after 'from'")
    if end_sec is not None and end_sec - (start_sec or 0) > 4 * 3600: raise HTTPException(400, "range too long (max 4 h)")
    opts = dict(banner=Path(banner).name, layout=layout, captions=captions, crop_fix=crop_fix and layout == "crop", hook=hook, cap_size=cap_size, model=model, language=language.strip(),
                mode=mode, start_sec=start_sec or 0, end_sec=end_sec, max_clips=max(1, min(max_clips, 10)),
                min_len=max(5.0, min(min_len, 180.0)), max_len=max(10.0, min(max_len, 180.0)), desc_lang=desc_lang.strip()[:40])
    if file is not None and file.filename:
        wd = JOBS_DIR / jid; wd.mkdir(exist_ok=True)
        dest = wd / safe_name(file.filename)
        with open(dest, "wb") as f: shutil.copyfileobj(file.file, f)
        opts["upload"] = str(dest); title = file.filename
    elif url.strip().startswith(("http://", "https://")):
        opts["url"] = url.strip(); title = url.strip()
    else:
        raise HTTPException(400, "give a http(s) link or a file")
    jobs[jid] = dict(id=jid, title=title, status="queued", stage="queued", pct=0, log=[], note="", outputs=[], opts=opts, t=time.time())
    order.insert(0, jid); q.put(jid)
    return {"id": jid}

@app.get("/api/jobs")
def list_jobs():
    return [{k: v for k, v in jobs[j].items() if k != "opts"} for j in order]

@app.get("/out/{name}")
def out(name: str, dl: int = 0):
    p = OUTPUT / Path(name).name
    if not p.exists(): raise HTTPException(404)
    return FileResponse(p, media_type="video/mp4", filename=p.name if dl else None)


def _dir_size(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())

@app.get("/api/usage")
def usage():
    return {"bytes": _dir_size(OUTPUT) + _dir_size(JOBS_DIR)}

@app.delete("/api/jobs")
def clear_all():
    """Delete every finished video and every working file. Banners are never touched."""
    if any(j["status"] in ("queued", "running") for j in jobs.values()):
        raise HTTPException(409, "a job is still running")
    freed = 0
    for d in (OUTPUT, JOBS_DIR):
        freed += _dir_size(d)
        for item in d.iterdir():
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    jobs.clear(); order.clear()
    return {"freed": freed}


def _kill_job(jid):
    """Stop the job's processes, then delete everything it produced (scratch files and finished clips)."""
    job = jobs.get(jid)
    if not job: return
    job["cancelled"] = True
    p = procs.get(jid)
    if p and p.poll() is None: _killpg(p, signal.SIGTERM)
    if job["status"] == "running":
        for _ in range(80):                    # give the worker thread up to 8 s to clean up
            if job.get("finished"): break
            time.sleep(0.1)
        if p and p.poll() is None: _killpg(p, signal.SIGKILL)
    for o in job["outputs"]:
        (OUTPUT / o["file"]).unlink(missing_ok=True)
    (OUTPUT / f"{jid}.json").unlink(missing_ok=True)
    shutil.rmtree(JOBS_DIR / jid, ignore_errors=True)
    jobs.pop(jid, None)
    if jid in order: order.remove(jid)

@app.post("/api/kill")
def kill_current():
    """Full reset for the current video: kill the running/queued job(s) and wipe their files.
    With nothing active, wipes the most recent job instead. Banners and older jobs are untouched."""
    active = [j for j in order if jobs[j]["status"] in ("queued", "running")]
    targets = active or order[:1]
    for jid in list(targets):
        _kill_job(jid)
    return {"killed": len(active), "deleted": len(targets) - len(active)}
