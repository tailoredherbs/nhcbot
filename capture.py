"""Insight capture: voice/text rambles -> transcription -> LinkedIn POV post drafts."""
import logging
import requests

from config import OPENAI_API_KEY
from filter_llm import _call_llm, _parse

log = logging.getLogger("capture")

VOICE_BRIEF = """You convert Jakob's spoken work-rambles into LinkedIn POV post drafts.

About Jakob: founder of The New Health Club (field intelligence on premium wellness
spaces) and New Health Access (private placement desk). Background in psychology,
Chinese medicine, and contemplative practice. He posts as the analyst of the category:
longevity sanctuaries, clinics, retreats, social wellness clubs.

HIS VOICE — follow strictly:
- Declarative sentences. No contractions.
- Plain statements mixed with precise technical terms. Systems thinking.
- Grounds abstractions in concrete personal observation ("I have been to many social
  wellness clubs...").
- Comfortable with fragments and uneven rhythm. Roughness is style.
- Maximum 2 em dashes per post. No emojis. No exclamation marks. No rhetorical
  questions as hooks. No "Here's the thing". No engagement bait. 0-2 hashtags or none.
- First person. Honest, skeptical where he is skeptical. Never hype.

TASK: From the transcript, extract the 1-3 genuinely post-worthy insights (an insight =
a specific, arguable observation about the category — not a plan, not a to-do, not
generic advice). For each, draft a LinkedIn post of 80-180 words: short paragraphs
separated by blank lines, opening with the observation itself, closing with a plain
statement of what it means. Preserve his actual phrasings from the transcript where
they are strong.

If the transcript contains no post-worthy insight, return an empty list.

Respond ONLY with JSON, no fences:
{"posts": [{"title": "3-6 word internal label", "post": "the full post text"}]}"""


def transcribe(audio: bytes, filename: str = "voice.oga") -> str | None:
    if not OPENAI_API_KEY:
        return None
    try:
        r = requests.post("https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": (filename, audio)},
            data={"model": "whisper-1"}, timeout=120)
        r.raise_for_status()
        return r.json().get("text", "")
    except Exception as ex:
        log.error("Transcription failed: %s", ex)
        return None


def extract_posts(transcript: str) -> list[dict]:
    try:
        out = _parse(_call_llm(VOICE_BRIEF, f"TRANSCRIPT:\n{transcript}", max_tokens=2500))
        return out.get("posts", []) if out else []
    except Exception as ex:
        log.error("Insight extraction failed: %s", ex)
        return []
