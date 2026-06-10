"""Quarterly-style market reports synthesized from published signals."""
import base64, datetime, json, logging, re
import requests

from config import SITE_URL, GITHUB_TOKEN, GITHUB_REPO
from filter_llm import _call_llm, _parse

log = logging.getLogger("reports")

REPORT_BRIEF = """You are the analyst behind The New Health Club, a field-intelligence
platform on premium wellness spaces (longevity sanctuaries, clinics, boutiques, retreats,
social wellness clubs). You write Market Reports that synthesize recent signals into one
structural read on the category.

VOICE: declarative, operator-literate, specific. Short paragraphs (1-3 sentences each).
Name venues and operators. State patterns plainly. No hype adjectives, no buzzword strings,
no "in conclusion". The reader is an operator, investor, or intermediary.

TASK: From the signals provided, identify the SINGLE strongest structural pattern that is
NOT already covered by the existing report titles listed. Write one report on it:
- Open with the pattern stated in one plain sentence.
- Develop it through the concrete signals: who did what, where, with numbers when present.
- Close with 1-2 sentences on what this means for the category's structure (no predictions
  dressed as certainty; state the direction the evidence points).
- 350-550 words total.

Respond ONLY with JSON, no fences:
{"title": "sentence-case report title, max 9 words",
 "tag": "4-6 comma-separated topical tags",
 "description": "2 sentence summary for the list view",
 "readTime": "3",
 "body": "the full report text, paragraphs separated by blank lines"}"""


def _get_json(path):
    return requests.get(f"{SITE_URL}/{path}", timeout=20).json()


def _parse_date(s):
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%d %B %Y", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt).date()
        except Exception:
            continue
    return None


def gather(days: int | None = None):
    """Signals since last report (or `days` back). Returns (signals, since, existing_titles)."""
    signals = _get_json("signals-data.json")
    try:
        reports = _get_json("reports-data.json")
        titles = [r.get("title", "") for r in reports]
        last = max((d for d in (_parse_date(r.get("date", "")) for r in reports) if d),
                   default=None)
    except Exception:
        titles, last = [], None
    if days:
        since = datetime.date.today() - datetime.timedelta(days=days)
    else:
        since = last or (datetime.date.today() - datetime.timedelta(days=90))
    recent = [s for s in signals
              if (_parse_date(s.get("date", "")) or datetime.date.min) >= since]
    return recent, since, titles


def draft(days: int | None = None) -> dict | None:
    recent, since, titles = gather(days)
    if len(recent) < 5:
        return {"error": f"Only {len(recent)} signals since {since} — too few to synthesize. "
                         f"Try /report 180 for a longer window."}
    lines = []
    for s in recent:
        lines.append(f"- [{s.get('date','')}] {s.get('title','')} ({s.get('category','')}, "
                     f"{s.get('location','')}) — {s.get('description','')}")
    user = (f"EXISTING REPORT TITLES (do not repeat these themes):\n"
            + "\n".join(titles) +
            f"\n\nSIGNALS SINCE {since} ({len(recent)} total):\n" + "\n".join(lines))
    try:
        out = _parse(_call_llm(REPORT_BRIEF, user, max_tokens=3000))
        if out:
            out["n_signals"] = len(recent)
            out["since"] = str(since)
        return out
    except Exception as ex:
        log.error("Report draft failed: %s", ex)
        return None


def report_markdown(r: dict) -> str:
    date = datetime.date.today().strftime("%B %-d, %Y")
    desc = (r.get("description") or "").replace('"', "'")
    return ("---\n"
            f"title: {r['title']}\n"
            "type: Market Report\n"
            f"date: {date}\n"
            f"readTime: \"{r.get('readTime','3')}\"\n"
            f"tag: {r.get('tag','')}\n"
            f"description: {desc}\n"
            "---\n\n"
            f"{r.get('body','')}\n")


def publish(r: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", r["title"].lower()).strip("-")[:80]
    path = f"_reports/{slug}.md"
    resp = requests.put(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                 "Accept": "application/vnd.github+json"},
        json={"message": f"Report: {r['title']}",
              "content": base64.b64encode(report_markdown(r).encode()).decode()},
        timeout=30)
    resp.raise_for_status()
    return path
