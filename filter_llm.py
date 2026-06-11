"""LLM filter: scores each item against the editorial criteria, drafts the signal."""
import json, logging
import requests

from config import OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENAI_MODEL, ANTHROPIC_MODEL
from editorial import CRITERIA, OUTPUT_SPEC

log = logging.getLogger("filter")

def _call_llm(system: str, user: str, max_tokens: int = 1200, temperature: float = 0.2) -> str:
    if ANTHROPIC_API_KEY:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": ANTHROPIC_MODEL, "max_tokens": max_tokens, "temperature": temperature, "system": system,
                  "messages": [{"role": "user", "content": user}]}, timeout=90)
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:300]}")
        return "".join(b.get("text", "") for b in r.json()["content"])
    if OPENAI_API_KEY:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": OPENAI_MODEL, "temperature": temperature,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]}, timeout=90)
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAI API {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("Set OPENAI_API_KEY or ANTHROPIC_API_KEY")

def _parse(text: str) -> dict | None:
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except Exception:
        m = text[text.find("{"): text.rfind("}") + 1]
        try:
            return json.loads(m)
        except Exception:
            return None

def assess(item: dict, index_venues: list[str]) -> dict | None:
    system = CRITERIA + "\n\n" + OUTPUT_SPEC
    venues = ", ".join(index_venues) if index_venues else "(index list unavailable)"
    user = (f"INDEX VENUES: {venues}\n\n"
            f"NEWS ITEM\nSource: {item['source']}\nTitle: {item['title']}\n"
            f"URL: {item['url']}\nPublished: {item['published']}\n"
            f"Summary: {item['raw_summary']}")
    try:
        return _parse(_call_llm(system, user))
    except Exception as ex:
        log.error("LLM failed for item %s: %s", item["id"], ex)
        return None

def revise(item: dict, instruction: str) -> dict | None:
    llm = json.loads(item["llm"])
    system = CRITERIA + "\n\n" + OUTPUT_SPEC
    user = (f"Here is a drafted signal as JSON:\n{json.dumps(llm)}\n\n"
            f"Source summary for reference: {item['raw_summary']}\n\n"
            f"Revise it according to this instruction, keep the same JSON format, "
            f"set include=true: {instruction}")
    try:
        return _parse(_call_llm(system, user))
    except Exception as ex:
        log.error("LLM revise failed: %s", ex)
        return None
