"""Insight capture, final: one ramble -> one post (reports voice) or one auto-saved
seed. /compile turns accumulated seeds into posts when enough material clusters."""
import json, logging
import requests

from config import OPENAI_API_KEY
from filter_llm import _call_llm, _parse

log = logging.getLogger("capture")

POV_VOICE = """VOICE — the same register as The New Health Club market reports, in first
person: declarative, operator-literate, specific. No contractions. Short paragraphs of
1-3 sentences separated by blank lines. State the observation, develop it through his
concrete material — preserve his phrasings, numbers, and examples where strong — and
close plainly on what it means. No hype adjectives, no emojis, no exclamation marks,
no rhetorical-question hooks, 0-2 hashtags or none."""

PROCESS_BRIEF = """You process a spoken work-ramble from Jakob, founder of The New
Health Club (field intelligence on premium wellness spaces: longevity sanctuaries,
clinics, retreats, social wellness clubs) and New Health Access (private placement desk).

""" + POV_VOICE + """

DECIDE: Does the ramble contain enough developed, postable material for ONE solid
LinkedIn post of 120-250 words built substantially from his own sentences?

- If YES: write that one post. Synthesize the connected threads into one argument —
  do not fragment it. Also select its strongest line as a pull quote (max 16 words,
  from the post).
- If NO (thought too thin, or mostly plans/process-talk, or mostly out-of-scope
  opinion): save it as a seed instead — a 1-2 sentence summary of the core thought
  plus the verbatim phrases worth keeping.

Respond ONLY with JSON, no fences. Either:
{"mode": "post", "title": "3-6 word label", "post": "...", "pull_quote": "..."}
or:
{"mode": "seed", "title": "3-6 word label", "summary": "1-2 sentence core thought",
 "material": ["verbatim phrase", "..."]}"""

COMPILE_BRIEF = """You compile saved seed-thoughts from Jakob into LinkedIn posts.
Each seed has an id, a core thought, and raw verbatim material.

""" + POV_VOICE + """

TASK: Group seeds that genuinely belong to one argument. For each group with enough
combined material, write ONE post of 120-250 words built substantially from his
verbatim material, synthesized into a single argument. Ignore groups still too thin —
do not pad. A seed may be used in at most one post.

Respond ONLY with JSON, no fences:
{"posts": [{"title": "3-6 word label", "post": "...", "pull_quote": "max 16 words",
"seed_ids": [ids of the seeds used]}]}
If nothing has enough material, return {"posts": []}."""


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


def process(transcript: str) -> dict | None:
    try:
        return _parse(_call_llm(PROCESS_BRIEF, f"TRANSCRIPT:\n{transcript}",
                                max_tokens=2000, temperature=0.4))
    except Exception as ex:
        log.error("Capture processing failed: %s", ex)
        return None


def compile_seeds(seeds: list[dict]) -> list[dict]:
    lines = []
    for s in seeds:
        lines.append(f"SEED id={s['id']} — {s['title']}\n{s['post']}")
    try:
        out = _parse(_call_llm(COMPILE_BRIEF, "\n\n".join(lines),
                               max_tokens=3000, temperature=0.4))
        return (out or {}).get("posts", [])
    except Exception as ex:
        log.error("Seed compile failed: %s", ex)
        return []
