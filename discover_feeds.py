"""One-time helper: discover working RSS feed URLs for the six publications.
Run locally or on Railway: python discover_feeds.py — then paste results into config.FEEDS."""
import re, requests, feedparser

UA = {"User-Agent": "Mozilla/5.0 (NHC feed discovery)"}
SITES = {
    "HCM": "https://www.healthclubmanagement.co.uk",
    "Spa Business": "https://www.spabusiness.com",
    "Athletech News": "https://athletechnews.com",
    "American Spa": "https://www.americanspa.com",
    "Welltodo": "https://www.welltodoglobal.com",
    "Longevity.Technology": "https://longevity.technology",
}
COMMON = ["/feed/", "/feed", "/rss", "/rss/", "/rss.xml", "/feed.xml", "/feeds/posts/default", "/?feed=rss2"]

def valid(url):
    try:
        r = requests.get(url, headers=UA, timeout=20)
        f = feedparser.parse(r.content)
        return len(f.entries) > 0
    except Exception:
        return False

for name, base in SITES.items():
    found = []
    # 1. <link rel="alternate"> on homepage
    try:
        html = requests.get(base, headers=UA, timeout=20).text
        for m in re.finditer(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"', html, re.I):
            href = m.group(1)
            if href.startswith("/"):
                href = base + href
            found.append(href)
    except Exception as e:
        print(f"{name}: homepage fetch failed ({e})")
    # 2. common paths
    for p in COMMON:
        found.append(base + p)
    hit = next((u for u in dict.fromkeys(found) if valid(u)), None)
    print(f"{name}: {hit or 'NOT FOUND — needs manual check / HTML scraper'}")
