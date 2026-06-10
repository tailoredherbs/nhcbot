"""Commit approved signals to _signals/ in the site repo via the GitHub API."""
import base64, datetime, json, logging, re
import requests

from config import GITHUB_TOKEN, GITHUB_REPO

log = logging.getLogger("publisher")

def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:80]

def signal_markdown(llm: dict, source_url: str) -> str:
    date = datetime.date.today().isoformat()
    desc = (llm.get("description") or "").replace('"', "'")
    body = llm.get("body") or ""
    body += f"\n\nSource: {source_url}"
    return (
        "---\n"
        f"title: {llm['title']}\n"
        f"category: {llm.get('category','Other')}\n"
        f"location: {llm.get('location','')}\n"
        f"date: {date}\n"
        f"tag: {llm.get('tag','')}\n"
        f"description: {desc}\n"
        "---\n\n"
        f"{body}\n")

def publish(llm: dict, source_url: str) -> str:
    """Create the markdown file on main. Returns the file path. Raises on failure."""
    path = f"_signals/{_slug(llm['title'])}.md"
    content = signal_markdown(llm, source_url)
    r = requests.put(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                 "Accept": "application/vnd.github+json"},
        json={"message": f"Signal: {llm['title']}",
              "content": base64.b64encode(content.encode()).decode()},
        timeout=30)
    if r.status_code == 422:  # file exists -> add date suffix
        path = path.replace(".md", f"-{datetime.date.today().isoformat()}.md")
        r = requests.put(
            f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                     "Accept": "application/vnd.github+json"},
            json={"message": f"Signal: {llm['title']}",
                  "content": base64.b64encode(content.encode()).decode()},
            timeout=30)
    r.raise_for_status()
    log.info("Published %s", path)
    return path
