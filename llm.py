"""Claude calls: pick the best short-form moments from a transcript and write post descriptions."""
import os

# Sonnet-class pricing in USD per million tokens (see platform.claude.com/docs/en/about-claude/pricing)
PRICE_IN, PRICE_OUT = 2.0, 10.0
MODELS = [m for m in (os.environ.get("MEMECLIP_MODEL"), "claude-sonnet-5-5", "claude-sonnet-5") if m]

def get_key():
    """env ANTHROPIC_API_KEY -> keychain 'memeclip' -> keychain 'autoclip' (if you used AutoClip)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        import keyring
    except ImportError:
        return None
    for service in ("memeclip", "autoclip"):
        try:
            v = keyring.get_password(service, "anthropic")
            if v:
                return v
        except Exception:
            pass
    return None

def _mmss(t):
    return f"{int(t // 60):02d}:{int(t % 60):02d}"

TOOL = {
    "name": "submit_clips",
    "description": "Submit the chosen clips.",
    "input_schema": {
        "type": "object",
        "properties": {"clips": {"type": "array", "items": {"type": "object", "properties": {
            "start_id": {"type": "integer", "description": "id of the first sentence of the clip"},
            "end_id": {"type": "integer", "description": "id of the last sentence of the clip (inclusive)"},
            "title": {"type": "string", "description": "short hook, max 60 chars"},
            "description": {"type": "string", "description": "ready-to-post TikTok/Reels caption + 3-5 hashtags"},
            "reason": {"type": "string", "description": "one sentence: why this works as a standalone clip"},
            "score": {"type": "integer", "description": "1-10 virality/interest"},
        }, "required": ["start_id", "end_id", "title", "description", "reason", "score"]}}},
        "required": ["clips"],
    },
}

def pick_clips(sentences, n, min_len, max_len, desc_lang=""):
    """Returns (clips, usage_dict). Sentences: [{i,start,end,text}]."""
    import anthropic
    key = get_key()
    if not key:
        raise RuntimeError("No Anthropic API key found. Run: python setkey.py")
    lines = "\n".join(f"[{s['i']}] {_mmss(s['start'])} {s['text']}" for s in sentences)
    lang = desc_lang.strip() or "the same language as the transcript"
    system = (
        "You are a short-form video editor (TikTok / Instagram Reels). From a numbered transcript, choose the "
        f"{n} best moments that work as standalone vertical clips. Rules: each clip starts on a strong hook and ends "
        f"on a finished thought or punchline; it must make sense without earlier context; length between {min_len} and "
        f"{max_len} seconds (use the mm:ss timestamps to measure); clips must not overlap; prefer funny, surprising, "
        "emotional or insightful moments over small talk. Choose fewer than requested if there are not enough good ones. "
        f"Write titles and post descriptions in {lang}. A description is 1-2 punchy sentences plus 3-5 relevant hashtags. "
        "Return your answer only via the submit_clips tool."
    )
    client = anthropic.Anthropic(api_key=key)
    user = f"Transcript ({_mmss(sentences[-1]['end'])} long):\n{lines}"
    ti = to = 0
    clips, last = None, None
    for model in MODELS:
        try:
            for attempt in range(2):  # the model occasionally answers in prose; ask once more
                msg = client.messages.create(
                    model=model, max_tokens=8192, system=system, tools=[TOOL],
                    messages=[{"role": "user", "content": user if attempt == 0 else user + "\n\nCall the submit_clips tool now."}],
                )
                ti += msg.usage.input_tokens; to += msg.usage.output_tokens
                for block in msg.content:
                    if block.type == "tool_use":
                        clips = block.input.get("clips", [])
                if clips is not None:
                    break
            break
        except anthropic.NotFoundError as e:  # unknown model id -> try the next one
            last = e
    else:
        raise RuntimeError(f"No usable Claude model found: {last}")
    if clips is None:
        raise RuntimeError("Claude did not return clips")
    return clips, {"model": model, "in": ti, "out": to, "usd": (ti * PRICE_IN + to * PRICE_OUT) / 1e6}
