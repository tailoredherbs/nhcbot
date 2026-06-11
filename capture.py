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
(longevity clinics, retreats, social wellness clubs, practitioners) — something about
how the WORLD is, that a reader could disagree with. STRICTLY EXCLUDED: his plans and
intentions ("I want to...", "the site should..."), to-dos, and business strategy —
those are not insights. Keep insights strictly separate — never merge two points that
happen to be adjacent in the ramble. If two candidate insights substantially overlap,
keep only the stronger one.

For each insight collect his raw material GENEROUSLY: every verbatim sentence and
phrase from the transcript that touches it, in original order, including the rough
ones — 6-15 items. The next stage can only use what you collect.

If nothing qualifies, return an empty list.

Respond ONLY with JSON, no fences:
{"insights": [{"label": "3-6 word internal label",
  "point": "the single claim, one sentence, in plain words",
  "material": ["verbatim phrase 1", "verbatim phrase 2", "..."]}]}"""

SECRETARY_BRIEF = """You are a respectful secretary, not a ghost-writer. You turn one
insight from Jakob's spoken ramble into a LinkedIn post using HIS OWN WORDS.

THE METHOD — follow exactly:
1. Take the verbatim material provided. These are his actual sentences.
2. Select the sentences that carry the single insight given. Discard the rest.
3. Clean only: remove filler words (like, right, you know, kind of, basically, I mean),
   false starts, and exact repetitions. Expand obvious fragments minimally so they
   parse. Remove contractions (it's -> it is). Fix nothing else.
4. Arrange into a post: 100-250 words, short paragraphs separated by blank lines.
   You may add AT MOST two short connective phrases of your own (e.g. "And yet.",
   "That is the gap."). Nothing else may be invented — no new examples, no new claims,
   no vocabulary that is not his.
5. If his material ends without a conclusion, end the post where his thought ends.
   Do not write a closing summary for him.

The result should sound like a person thinking, not like content. Rough is correct.

Also select the single strongest line as a pull quote (max 16 words, verbatim from
the post).

Respond ONLY with JSON, no fences:
{"post": "the assembled post", "pull_quote": "strongest line"}"""


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

    posts = []
    for ins in insights[:3]:
        user = (f"THE INSIGHT: {ins.get('point','')}\n\n"
                f"HIS VERBATIM MATERIAL:\n- " + "\n- ".join(ins.get("material", [])))
        try:
            draft = _parse(_call_llm(SECRETARY_BRIEF, user,
                                     max_tokens=1500, temperature=0.3))
            if draft and draft.get("post"):
                posts.append({"title": ins.get("label", ""),
                              "post": draft.get("post", ""),
                              "pull_quote": draft.get("pull_quote", "")})
        except Exception as ex:
            log.error("Assembly failed for '%s': %s", ins.get("label"), ex)
    return posts
