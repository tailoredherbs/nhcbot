"""Insight capture v4: extract -> write per-insight -> de-slop. Voice/text rambles
become LinkedIn POV drafts."""
import logging
import requests

from config import OPENAI_API_KEY
from filter_llm import _call_llm, _parse

log = logging.getLogger("capture")

# Paste 2-3 paragraphs of Jakob's own published writing between the triple quotes
# below — they anchor the voice far better than any rule list. Until then the
# rules carry it alone.
WRITING_SAMPLES = """"""

VOICE_RULES = """HIS VOICE:
- Declarative sentences. No contractions. Fragments allowed. Uneven rhythm is style.
- Measured and reflective. He thinks out loud with quiet authority. Skepticism reads
  as experience, not attack.
- Concrete over abstract, always. His actual phrasings, numbers, and examples survive.
- No emojis, no exclamation marks, 0-2 hashtags or none, no rhetorical-question hooks,
  maximum 2 em dashes.
- Critique patterns, never named venues or people. Named venues only positive/neutral.
"""

EXTRACT_BRIEF = """You analyze a spoken work-ramble from the founder of a wellness
field-intelligence platform. Identify the 1-3 DISTINCT post-worthy insights.

An insight = ONE specific, arguable observation about the premium wellness category
(longevity clinics, retreats, social wellness clubs, practitioners). Not a plan, not a
to-do, not generic advice. Keep insights strictly separate — never merge two points
that happen to be adjacent in the ramble.

For each insight collect his raw material: the verbatim phrases, numbers, and examples
from the transcript that carry it.

If nothing qualifies, return an empty list.

Respond ONLY with JSON, no fences:
{"insights": [{"label": "3-6 word internal label",
  "point": "the single claim, one sentence, in plain words",
  "material": ["verbatim phrase 1", "verbatim phrase 2", "..."]}]}"""

WRITE_BRIEF = """You ghost-write a LinkedIn post for Jakob, founder of The New Health
Club (field intelligence on premium wellness spaces) and New Health Access (private
placement desk). Psychology background, Chinese medicine, contemplative training.

""" + VOICE_RULES + """
{samples}
TASK: Write ONE post developing ONLY the single insight given. 150-280 words, short
paragraphs separated by blank lines. Open with the observation itself. Develop it
through his raw material — reuse his verbatim phrases where they are strong. Close on
what it means, plainly. Do not import any other point.

Also select the post's single strongest line as a pull quote (max 16 words, from the
post text, light trimming allowed).

Respond ONLY with JSON, no fences:
{{"post": "the full post text", "pull_quote": "strongest line"}}"""

DESLOP_BRIEF = """You are a ruthless editor. The text below is a LinkedIn post draft.
Rewrite it with one goal: remove everything that could appear in a generic AI-written
LinkedIn post. Specifically delete or rewrite: abstract filler ("comprehensive",
"crucial", "diverse", "landscape", "richer experience", "broader offering", "it is
important"), balanced both-sides hedging that says nothing, and any closing paragraph
that merely restates the post. Keep: the concrete observations, numbers, personal
experience, the author's verbatim phrasings, the declarative no-contractions style.
The result should be shorter or equal in length, never longer. Do not add new ideas.

Respond ONLY with JSON, no fences:
{"post": "the edited post", "pull_quote": "strongest line, max 16 words"}"""


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
        out = _parse(_call_llm(EXTRACT_BRIEF, f"TRANSCRIPT:\n{transcript}",
                               max_tokens=2000, temperature=0.2))
        insights = (out or {}).get("insights", [])
    except Exception as ex:
        log.error("Extraction failed: %s", ex)
        return []

    samples = ""
    if WRITING_SAMPLES.strip():
        samples = ("EXAMPLES OF HIS ACTUAL PUBLISHED WRITING — match this voice "
                   "exactly:\n" + WRITING_SAMPLES.strip() + "\n\n")
    posts = []
    for ins in insights[:3]:
        user = (f"THE INSIGHT: {ins.get('point','')}\n\n"
                f"HIS RAW MATERIAL:\n- " + "\n- ".join(ins.get("material", [])))
        try:
            draft = _parse(_call_llm(WRITE_BRIEF.format(samples=samples), user,
                                     max_tokens=1500, temperature=0.8))
            if not draft or not draft.get("post"):
                continue
            final = _parse(_call_llm(DESLOP_BRIEF, draft["post"],
                                     max_tokens=1500, temperature=0.4))
            if final and final.get("post"):
                draft = final
            posts.append({"title": ins.get("label", ""),
                          "post": draft.get("post", ""),
                          "pull_quote": draft.get("pull_quote", "")})
        except Exception as ex:
            log.error("Write/deslop failed for '%s': %s", ins.get("label"), ex)
    return posts
