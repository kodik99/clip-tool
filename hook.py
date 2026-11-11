"""Hook headline: render a short bold-serif title with colour emojis to a transparent PNG (drawn above the video).
Colour emojis can't be drawn by the subtitle engine, so the whole headline is rendered as an image with Pillow.
Fonts: Georgia Bold / Times New Roman Bold + Apple Color Emoji on macOS; elsewhere DejaVu Serif Bold (if matplotlib is
installed) or the bundled Anton, and emojis are dropped when no colour-emoji font is found."""
import os, re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SERIF_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "C:/Windows/Fonts/georgiab.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
]
EMOJI_CANDIDATES = [
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
]
EMOJI_BITMAP_SIZE = {"Apple Color Emoji.ttc": 160, "NotoColorEmoji.ttf": 109}

EMOJI_RE = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2}"
    "|[#*0-9]\uFE0F?\u20E3"
    "|(?:[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B55\u2B1B\u2B1C\u2300-\u23FF\u2934\u2935\u3030\u303D\u3297\u3299"
    "\u00A9\u00AE\u203C\u2049\u2122\u2139\u25AA-\u25FE]\uFE0F?[\U0001F3FB-\U0001F3FF]?"
    "(?:\u200D[\U0001F300-\U0001FAFF\u2600-\u27BF\u2640\u2642\u2695\u2696\u2708\u2764]\uFE0F?[\U0001F3FB-\U0001F3FF]?)*))")


def _first_existing(paths):
    return next((p for p in paths if os.path.exists(p)), None)


def serif_path():
    p = _first_existing(SERIF_CANDIDATES)
    if p:
        return p
    try:
        import matplotlib
        d = Path(matplotlib.__file__).parent / "mpl-data/fonts/ttf/DejaVuSerif-Bold.ttf"
        if d.exists():
            return str(d)
    except Exception:
        pass
    return str(HERE / "fonts/Anton-Regular.ttf")


_emoji_cache = {}


def _emoji_font():
    p = _first_existing(EMOJI_CANDIDATES)
    if not p:
        return None
    return ImageFont.truetype(p, EMOJI_BITMAP_SIZE.get(Path(p).name, 109))


def _emoji_image(ch, em):
    """Colour emoji as an RGBA image `em` px tall (None if it cannot be drawn)."""
    key = (ch, em)
    if key in _emoji_cache:
        return _emoji_cache[key]
    img = None
    f = _emoji_font()
    if f is not None:
        try:
            canvas = Image.new("RGBA", (260, 260), (0, 0, 0, 0))
            ImageDraw.Draw(canvas).text((10, 10), ch, font=f, embedded_color=True)
            box = canvas.getbbox()
            if box:
                glyph = canvas.crop(box)
                scale = em / glyph.height
                img = glyph.resize((max(1, round(glyph.width * scale)), em), Image.LANCZOS)
        except Exception:
            img = None
    _emoji_cache[key] = img
    return img


def _tokens(text):
    """[(kind, string)] with kind 'w' (word) or 'e' (emoji); whitespace only separates tokens."""
    out, pos = [], 0
    for m in EMOJI_RE.finditer(text):
        for w in text[pos:m.start()].split():
            out.append(("w", w))
        out.append(("e", m.group(0)))
        pos = m.end()
    for w in text[pos:].split():
        out.append(("w", w))
    return out


def _wrap(tokens, font, em, max_w):
    space = font.getlength(" ")
    lines, cur, cur_w = [], [], 0.0
    for kind, s in tokens:
        w = font.getlength(s) if kind == "w" else (_emoji_image(s, em).width if _emoji_image(s, em) else 0)
        if kind == "e" and not w:
            continue                                   # emoji we cannot draw: skip it
        add = w + (space if cur else 0)
        if cur and cur_w + add > max_w:
            lines.append((cur, cur_w)); cur, cur_w, add = [], 0.0, w
        cur.append((kind, s, w)); cur_w += add
    if cur:
        lines.append((cur, cur_w))
    return lines


def render_hook(text, path, W=1080, max_w=930, max_h=250, max_lines=3, backdrop=False, pad_top=0):
    """Render the headline to `path` (PNG, W px wide). Returns (width, height) of the image."""
    text = " ".join((text or "").split())
    if not text:
        return None
    tokens = _tokens(text)
    spath = serif_path()
    best = None
    for lines_allowed, min_size in ((2, 56), (max_lines, 40)):   # prefer 2 big lines, else allow more, smaller
        for size in range(84, min_size - 1, -4):
            font = ImageFont.truetype(spath, size)
            em = int(size * 0.95)
            lines = _wrap(tokens, font, em, max_w)
            line_h = int(size * 1.22)
            if len(lines) <= lines_allowed and len(lines) * line_h <= max_h:
                n = len(lines)                            # balance: shrink the wrap width while the line count stays
                for w in range(max_w, 300, -20):
                    trial = _wrap(tokens, font, em, w)
                    if len(trial) == n:
                        lines = trial
                    else:
                        break
                best = (font, em, lines, size, line_h)
                break
        if best:
            break
    if best is None:                                     # very long text: smallest size, cut to max_lines
        font = ImageFont.truetype(spath, 40); em = 38
        best = (font, em, _wrap(tokens, font, em, max_w)[:max_lines], 40, 49)
    font, em, lines, size, line_h = best
    sw = max(3, size // 11)                              # outline width
    H = pad_top + len(lines) * line_h + sw * 2 + 8
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if backdrop:                                          # soft dark gradient so the text reads over a bright picture
        grad = Image.new("L", (1, H))
        for y in range(H):
            grad.putpixel((0, y), int(150 * (1 - y / H) ** 1.2))
        img.paste(Image.new("RGBA", (W, H), (0, 0, 0, 255)), (0, 0), grad.resize((W, H)))
    d = ImageDraw.Draw(img)
    space = font.getlength(" ")
    for i, (items, lw) in enumerate(lines):
        x = (W - lw) / 2
        y = pad_top + i * line_h + sw + 4
        for kind, s, w in items:
            if kind == "w":
                d.text((x, y), s, font=font, fill=(255, 255, 255, 255), stroke_width=sw, stroke_fill=(0, 0, 0, 255))
            else:
                e = _emoji_image(s, em)
                img.alpha_composite(e, (int(x), int(y + (line_h - em) / 2 - 2)))
            x += w + space
    img.save(path)
    return img.size
