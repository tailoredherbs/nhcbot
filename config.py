import os

# --- Required env vars ---
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])  # your personal chat id
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]                # classic PAT with 'repo' scope
GITHUB_REPO = os.environ.get("GITHUB_REPO", "tailoredherbs/new-health-club")

# --- LLM: set ONE of these ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# --- Behaviour ---
DB_PATH = os.environ.get("DB_PATH", "/data/nhc.db")     # attach a Railway volume at /data
TZ = os.environ.get("TZ", "Asia/Makassar")               # Bali time
DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "8"))   # daily digest at 08:00
FETCH_EVERY_HOURS = int(os.environ.get("FETCH_EVERY_HOURS", "6"))
MAX_ITEMS_PER_DIGEST = int(os.environ.get("MAX_ITEMS_PER_DIGEST", "15"))
SITE_URL = os.environ.get("SITE_URL", "https://thenewhealthclubs.com")

# --- Sources ---
# Run discover_feeds.py once to verify/correct these URLs, then update here.
FEEDS = {
    "HCM (Health Club Management)": "https://www.healthclubmanagement.co.uk/rss",
    "Spa Business": "https://www.spabusiness.com/rss",
    "Athletech News": "https://athletechnews.com/feed/",
    "American Spa": "https://www.americanspa.com/rss.xml",
    "Welltodo": "https://www.welltodoglobal.com/feed/",
    "Longevity.Technology": "https://longevity.technology/feed/",
    "Spa Executive": "https://spaexecutive.com/feed/",
}

# --- Private radar (never published): science & regulatory awareness for the desk ---
RADAR_FEEDS = {
    "Lifespan.io": "https://www.lifespan.io/feed/",
    "Peter Attia": "https://peterattiamd.com/feed/",
    "Psychedelic Alpha": "https://psychedelicalpha.com/feed/",
    "Longevity.Technology (science)": "https://longevity.technology/feed/",
    "DoubleBlind (psychedelics)": "https://doubleblindmag.com/feed/",
    "News scan: retreat incidents": "https://news.google.com/rss/search?q=%22retreat%22+(death+OR+lawsuit+OR+investigation+OR+misconduct+OR+allegations)+(wellness+OR+meditation+OR+ayahuasca+OR+psilocybin)&hl=en-US&gl=US&ceid=US:en",
    "News scan: psychedelic retreat regulation": "https://news.google.com/rss/search?q=(psilocybin+OR+ayahuasca+OR+ibogaine)+retreat+(legal+OR+regulation+OR+license+OR+program)&hl=en-US&gl=US&ceid=US:en",
}
RADAR_DIGEST_DAY = int(os.environ.get("RADAR_DIGEST_DAY", "6"))   # 0=Mon .. 6=Sun
RADAR_DIGEST_HOUR = int(os.environ.get("RADAR_DIGEST_HOUR", "9"))
