import os

# --- Required env vars ---
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])  # your personal chat id
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]                # classic PAT with 'repo' scope
GITHUB_REPO = os.environ.get("GITHUB_REPO", "tailoredherbs/new-health-club")

# --- LLM: set ONE of these ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-4.3")

# --- Behaviour ---
DB_PATH = os.environ.get("DB_PATH", "/data/nhc.db")     # attach a Railway volume at /data
TZ = os.environ.get("TZ", "Asia/Makassar")               # Bali time
DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "8"))   # daily digest at 08:00
FETCH_EVERY_HOURS = int(os.environ.get("FETCH_EVERY_HOURS", "6"))
MAX_ITEMS_PER_DIGEST = int(os.environ.get("MAX_ITEMS_PER_DIGEST", "15"))
SITE_URL = os.environ.get("SITE_URL", "https://thenewhealthclubs.com")
ENABLE_GROK_CHANNEL_SCAN = os.environ.get("ENABLE_GROK_CHANNEL_SCAN", "").lower() in ("1", "true", "yes")
GROK_CHANNEL_BATCH_SIZE = int(os.environ.get("GROK_CHANNEL_BATCH_SIZE", "8"))
PENDING_ARCHIVE_DAYS = int(os.environ.get("PENDING_ARCHIVE_DAYS", "28"))
SIGNAL_MAX_AGE_DAYS = int(os.environ.get("SIGNAL_MAX_AGE_DAYS", "45"))

# --- Sources ---
# Run discover_feeds.py once to verify/correct these URLs, then update here.
FEEDS = {
    "Athletech News": "https://athletechnews.com/feed/",
    "American Spa": "https://www.americanspa.com/rss.xml",
    "Longevity.Technology": "https://longevity.technology/feed/",
    "Industry publication watch": "https://news.google.com/rss/search?q=%28site%3Aspabusiness.com+OR+site%3Ahealthclubmanagement.co.uk%29+%28opening+OR+opens+OR+launches+OR+expands+OR+resort+OR+retreat+OR+spa+OR+wellness%29+when%3A45d+-%22job+vacancy%22+-%22press+release%22+-%22lighting+design%22+-%22equipment%22&hl=en-US&gl=US&ceid=US%3Aen",
    "Premium wellness openings": "https://news.google.com/rss/search?q=%28%22wellness+club%22+OR+%22wellness+space%22+OR+%22private+members+club%22%29+%28opening+OR+opens+OR+launches+OR+expands%29+when%3A45d&hl=en-US&gl=US&ceid=US%3Aen",
    "Retreat and destination watch": "https://news.google.com/rss/search?q=%28%22wellness+retreat%22+OR+%22destination+spa%22%29+%28opening+OR+launches+OR+program+OR+expansion%29+when%3A45d&hl=en-US&gl=US&ceid=US%3Aen",
    "Longevity clinic watch": "https://news.google.com/rss/search?q=%28%22longevity+clinic%22+OR+%22longevity+center%22+OR+%22healthspan+clinic%22%29+%28opening+OR+launches+OR+expands+OR+partnership%29+when%3A45d&hl=en-US&gl=US&ceid=US%3Aen",
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
RADAR_MAX_AGE_DAYS = int(os.environ.get("RADAR_MAX_AGE_DAYS", "180"))  # ignore older items
RADAR_DIGEST_DAY = int(os.environ.get("RADAR_DIGEST_DAY", "6"))   # 0=Mon .. 6=Sun
RADAR_DIGEST_HOUR = int(os.environ.get("RADAR_DIGEST_HOUR", "9"))
