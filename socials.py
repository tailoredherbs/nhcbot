"""Social pack: branded signal card (PNG) + IG/LinkedIn captions."""
import io, datetime, logging, os, textwrap

from PIL import Image, ImageDraw, ImageFont

from filter_llm import _call_llm, _parse

log = logging.getLogger("socials")

# --- The New Health Club design tokens (from site) ---
INK = (26, 22, 20)        # #1a1614
GRAY = (122, 112, 102)    # #7a7066
MID = (90, 82, 72)        # #5a5248
CREAM = (250, 250, 248)   # #fafaf8
LINE = (212, 207, 197)    # #d4cfc5

W, H = 1080, 1350         # 4:5 portrait — IG feed max, fine on LinkedIn
MARGIN = 96
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")


def _serif(size, weight=500):
    f = ImageFont.truetype(os.path.join(FONT_DIR, "Lora.ttf"), size)
    f.set_variation_by_axes([weight])
    return f

def _sans(size, weight=400):
    f = ImageFont.truetype(os.path.join(FONT_DIR, "Inter.ttf"), size)
    f.set_variation_by_axes([size if size <= 32 else 32, weight])
    return f

def _tracked(d, xy, text, font, fill, tracking=6):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + tracking
    return x - tracking

def _wrap(d, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_card(llm: dict, number: int | None = None, coords: tuple | None = None) -> bytes:
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    inner = W - 2 * MARGIN

    # Header: wordmark + rule
    y = 110
    _tracked(d, (MARGIN, y), "THE NEW HEALTH CLUB", _sans(26, 600), INK, tracking=8)
    y += 56
    d.line([(MARGIN, y), (W - MARGIN, y)], fill=INK, width=3)

    # Label: SIGNAL Nº · CATEGORY (with accent mark)
    y += 44
    d.rectangle([MARGIN, y + 6, MARGIN + 14, y + 20], fill=INK)
    label = "SIGNAL"
    if number:
        label += f" N\u00ba {number:03d}"
    cat = (llm.get("category") or "").upper()
    if cat:
        label += "  \u00b7  " + cat
    _tracked(d, (MARGIN + 32, y), label, _sans(24, 500), GRAY, tracking=5)

    # Headline (auto-size to fit available block)
    label_bottom = y + 40
    footer_top = H - 210
    avail = footer_top - label_bottom - 60
    title = llm.get("title", "")
    desc = llm.get("description", "")
    dfont = _sans(34, 400)
    desc_lines = _wrap(d, desc, dfont, inner)[:5]
    desc_h = (len(desc_lines) * 50 + 48) if desc_lines else 0

    size = 116
    while size > 54:
        font = _serif(size, 550)
        lines = _wrap(d, title, font, inner)
        line_h = int(size * 1.16)
        if len(lines) * line_h + desc_h <= avail:
            break
        size -= 6
    content_h = len(lines) * line_h + desc_h

    # Vertically center the content block (biased slightly upward)
    y = label_bottom + max(56, int((avail - content_h) * 0.42))
    for ln in lines:
        d.text((MARGIN, y), ln, font=font, fill=INK)
        y += line_h

    y += 48
    for ln in desc_lines:
        d.text((MARGIN, y), ln, font=dfont, fill=MID)
        y += 50

    # Footer block (anchored to bottom)
    fy = H - 210
    d.line([(MARGIN, fy), (W - MARGIN, fy)], fill=LINE, width=2)
    fy += 36
    loc = (llm.get("location") or "").upper()
    date = datetime.date.today().strftime("%d %B %Y").upper()
    meta = (loc + "  —  " + date) if loc else date
    _tracked(d, (MARGIN, fy), meta, _sans(23, 500), GRAY, tracking=4)
    if coords:
        lat, lng = coords
        cline = f"{abs(lat):.4f}\u00b0 {'N' if lat >= 0 else 'S'}   {abs(lng):.4f}\u00b0 {'E' if lng >= 0 else 'W'}"
        d.text((W - MARGIN - d.textlength(cline, font=_sans(23, 450)), fy), cline,
               font=_sans(23, 450), fill=GRAY)
    fy += 58
    _tracked(d, (MARGIN, fy), "THENEWHEALTHCLUBS.COM", _sans(22, 600), INK, tracking=6)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_note_card(pull_quote: str) -> bytes:
    """Pull-quote card for POV posts — sibling of the signal card."""
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    inner = W - 2 * MARGIN

    y = 110
    _tracked(d, (MARGIN, y), "THE NEW HEALTH CLUB", _sans(26, 600), INK, tracking=8)
    y += 56
    d.line([(MARGIN, y), (W - MARGIN, y)], fill=INK, width=3)
    y += 44
    d.rectangle([MARGIN, y + 6, MARGIN + 14, y + 20], fill=INK)
    _tracked(d, (MARGIN + 32, y), "FIELD NOTE", _sans(24, 500), GRAY, tracking=5)

    label_bottom = y + 40
    footer_top = H - 210
    avail = footer_top - label_bottom - 60

    quote = "\u201c" + pull_quote.strip().rstrip(".") + ".\u201d"
    size = 104
    while size > 56:
        font = _serif(size, 520)
        lines = _wrap(d, quote, font, inner)
        line_h = int(size * 1.22)
        if len(lines) * line_h <= avail:
            break
        size -= 6
    content_h = len(lines) * line_h
    y = label_bottom + max(56, int((avail - content_h) * 0.42))
    for ln in lines:
        d.text((MARGIN, y), ln, font=font, fill=INK)
        y += line_h

    fy = H - 210
    d.line([(MARGIN, fy), (W - MARGIN, fy)], fill=LINE, width=2)
    fy += 36
    date = datetime.date.today().strftime("%d %B %Y").upper()
    _tracked(d, (MARGIN, fy), "JAKOB \u00b7 NEW HEALTH ACCESS  \u2014  " + date,
             _sans(23, 500), GRAY, tracking=4)
    fy += 58
    _tracked(d, (MARGIN, fy), "THENEWHEALTHCLUBS.COM", _sans(22, 600), INK, tracking=6)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


CAPTION_PROMPT = """You write social posts for The New Health Club — a field-intelligence
platform mapping premium wellness spaces (longevity sanctuaries, clinics, retreats, clubs).
Voice: field intelligence. Factual, specific, operator-literate. No hype adjectives,
no exclamation marks, no emojis, no engagement-bait questions, no "exciting news".
Audience: operators, investors, travel designers, and discerning clients in luxury wellness.

Given a published signal, write:
1. instagram: 2-4 tight sentences. End with 4-6 lowercase hashtags on a new line, mixing
   category and location (e.g. #longevity #socialwellness #dubai #wellnessrealestate).
2. linkedin: 4-7 sentences, slightly more analytical — what happened, the numbers if any,
   and one sentence on why it matters for the category. 2 hashtags max at the end. No emojis.

Respond ONLY with JSON, no fences: {"instagram": "...", "linkedin": "..."}"""


def captions(llm: dict) -> dict | None:
    user = (f"SIGNAL\nTitle: {llm.get('title')}\nCategory: {llm.get('category')}\n"
            f"Location: {llm.get('location')}\nDescription: {llm.get('description')}\n"
            f"Body: {llm.get('body')}")
    try:
        return _parse(_call_llm(CAPTION_PROMPT, user))
    except Exception as ex:
        log.error("Caption generation failed: %s", ex)
        return None


import requests as _rq
from config import SITE_URL as _SITE

def signal_context(llm: dict) -> dict:
    """Best-effort: next signal number + venue coordinates from the live site."""
    out = {"number": None, "coords": None}
    try:
        sigs = _rq.get(f"{_SITE}/signals-data.json", timeout=15).json()
        out["number"] = len(sigs) + 1
    except Exception:
        pass
    try:
        venue = (llm.get("venue") or "").lower()
        if venue:
            spaces = _rq.get(f"{_SITE}/spaces-data.json", timeout=15).json()
            for s in spaces:
                n = s["name"].lower()
                if venue in n or n in venue:
                    out["coords"] = (s["coordinates"]["lat"], s["coordinates"]["lng"])
                    break
    except Exception:
        pass
    return out
