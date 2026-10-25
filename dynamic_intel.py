import aiohttp
import asyncio
import logging
import time
import re
import random
import xml.etree.ElementTree as ET

JIKAN_API_URL = "https://api.jikan.moe/v4/seasons/now"
ANILIST_API_URL = "https://graphql.anilist.co"

# In-memory cache for seasonal anime (Current & Trending 2025/2026)
_SEASONAL_ANIME_CACHE = [
    {"title": "Solo Leveling Season 2: Arise from the Shadow", "episodes": 13, "genres": ["Action", "Fantasy"]},
    {"title": "Dandadan", "episodes": 12, "genres": ["Action", "Supernatural", "Comedy"]},
    {"title": "Sakamoto Days", "episodes": 12, "genres": ["Action", "Comedy"]},
    {"title": "Chainsaw Man - The Movie: Reze Arc", "episodes": 1, "genres": ["Action", "Supernatural"]},
    {"title": "Bleach: Thousand-Year Blood War - The Conflict", "episodes": 13, "genres": ["Action", "Supernatural"]},
    {"title": "Demon Slayer: Infinity Castle Arc Movie Trilogy", "episodes": 3, "genres": ["Action", "Demons"]},
    {"title": "Dragon Ball Daima", "episodes": 20, "genres": ["Action", "Adventure"]},
    {"title": "Kaiju No. 8", "episodes": 12, "genres": ["Action", "Sci-Fi"]},
    {"title": "One Piece - Egghead Island & Elbaf Arc", "episodes": 50, "genres": ["Action", "Adventure"]},
    {"title": "Blue Lock vs. U-20 Japan", "episodes": 14, "genres": ["Sports"]},
    {"title": "Wind Breaker", "episodes": 13, "genres": ["Action", "School"]},
    {"title": "Jujutsu Kaisen Season 3: Culling Game", "episodes": 24, "genres": ["Action", "Dark Fantasy"]},
    {"title": "Frieren: Beyond Journey's End", "episodes": 28, "genres": ["Fantasy", "Drama"]},
    {"title": "Oshi no Ko Season 2", "episodes": 13, "genres": ["Drama", "Supernatural"]},
    {"title": "Re:Zero Season 3", "episodes": 16, "genres": ["Isekai", "Psychological"]},
    {"title": "Lookism & Omniscient Reader's Viewpoint", "episodes": 12, "genres": ["Action", "Webtoon"]}
]

# Trending Action Games (Current & Trending 2025/2026)
_TRENDING_GAMES_CACHE = [
    {"title": "GTA 6 (Grand Theft Auto VI)", "genre": "Open World / Action"},
    {"title": "Black Myth: Wukong", "genre": "Action RPG / Souls-like"},
    {"title": "Elden Ring: Shadow of the Erdtree", "genre": "Dark Fantasy RPG"},
    {"title": "Monster Hunter Wilds", "genre": "Action Hunting"},
    {"title": "Valorant (VCT & Ranked)", "genre": "Tactical FPS"},
    {"title": "BGMI / PUBG Mobile", "genre": "Battle Royale"},
    {"title": "Counter-Strike 2 (CS2)", "genre": "Competitive FPS"},
    {"title": "Marvel Rivals", "genre": "Hero Shooter"},
    {"title": "Tekken 8", "genre": "Fighting"},
    {"title": "Call of Duty: Black Ops 6", "genre": "Action FPS"}
]

_LAST_FETCH = 0
CACHE_TTL = 43200  # 12 hours

async def fetch_seasonal_anime():
    global _SEASONAL_ANIME_CACHE, _LAST_FETCH
    current_time = time.time()
    if _LAST_FETCH > 0 and (current_time - _LAST_FETCH) < CACHE_TTL:
        return _SEASONAL_ANIME_CACHE

    try:
        # Try Jikan first
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": "GunYamazakiBot/2.0"}
            async with session.get(JIKAN_API_URL, headers=headers, timeout=8) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("data", [])
                    cleaned = []
                    for item in items[:25]:
                        title = item.get("title_english") or item.get("title")
                        cleaned.append({
                            "title": title,
                            "episodes": item.get("episodes"),
                            "genres": [g.get("name") for g in item.get("genres", [])[:3]],
                            "score": item.get("score")
                        })
                    if cleaned:
                        _SEASONAL_ANIME_CACHE = cleaned
                        _LAST_FETCH = current_time
                        logging.info(f"Successfully fetched {len(cleaned)} seasonal anime from Jikan.")
                        return cleaned
    except Exception as je:
        logging.warning(f"Jikan seasonal fetch error: {je}")

    # Fallback return existing cache
    return _SEASONAL_ANIME_CACHE

def fetch_trending_topic():
    """
    Returns a random trending anime or game topic with its type ('anime' or 'game').
    """
    if random.random() < 0.6:
        item = random.choice(_SEASONAL_ANIME_CACHE)
        return item["title"], "anime"
    else:
        item = random.choice(_TRENDING_GAMES_CACHE)
        return item["title"], "game"

_LIVE_WEB_CACHE = []
_LAST_LIVE_FETCH = 0
LIVE_CACHE_TTL = 1800  # 30 minutes

LIVE_FEEDS = [
    ("anime", "https://news.google.com/rss/search?q=anime+movie+OR+season+release+when:3d&hl=en-IN&gl=IN&ceid=IN:en"),
    ("gaming", "https://news.google.com/rss/search?q=gaming+GTA+or+Valorant+or+PlayStation+or+Xbox+when:3d&hl=en-IN&gl=IN&ceid=IN:en"),
    ("sports", "https://news.google.com/rss/search?q=cricket+India+match+OR+squad+when:2d&hl=en-IN&gl=IN&ceid=IN:en")
]

async def fetch_live_web_intel():
    """
    Fetches real-time live breaking news headlines across Anime, Gaming, and Indian Sports via RSS.
    Returns: dict with 'title', 'category', 'source'.
    """
    global _LIVE_WEB_CACHE, _LAST_LIVE_FETCH
    current_time = time.time()
    if _LIVE_WEB_CACHE and (current_time - _LAST_LIVE_FETCH) < LIVE_CACHE_TTL:
        return random.choice(_LIVE_WEB_CACHE)

    category, feed_url = random.choice(LIVE_FEEDS)
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with session.get(feed_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    xml_text = await resp.text()
                    root = ET.fromstring(xml_text)
                    items = root.findall('.//item')[:10]
                    cleaned_news = []
                    for it in items:
                        raw_title = it.find('title')
                        if raw_title is not None and raw_title.text:
                            # Strip publisher suffix (e.g. " - IGN", " - Crunchyroll")
                            clean_t = re.sub(r'\s*-\s*[^-]+$', '', raw_title.text).strip()
                            if len(clean_t) > 12:
                                cleaned_news.append({
                                    "title": clean_t,
                                    "category": category,
                                    "source": "web"
                                })
                    if cleaned_news:
                        _LIVE_WEB_CACHE = cleaned_news
                        _LAST_LIVE_FETCH = current_time
                        logging.info(f"Successfully fetched {len(cleaned_news)} live {category} news items from web.")
                        return random.choice(cleaned_news)
    except Exception as e:
        logging.warning(f"Live web intel fetch error: {e}")

    # Fallback to local trending topic cache if network fails
    fallback_title, fallback_cat = fetch_trending_topic()
    return {"title": fallback_title, "category": fallback_cat, "source": "cache"}

def detect_language_mode(text_samples):
    """
    Detects whether the recent conversation is primarily Hinglish, Roman Hindi, or English.
    Returns: 'hinglish', 'hindi_roman', or 'english'.
    """
    if not text_samples:
        return 'hinglish'
    combined = " ".join(text_samples).lower()
    
    hindi_markers = [
        r'\bbhai\b', r'\bhn\b', r'\bha\b', r'\bnhi\b', r'\bkyu\b', r'\bkya\b', 
        r'\bsyd\b', r'\bacha\b', r'\barre\b', r'\bbas\b', r'\bbata\b', r'\bkar\b', 
        r'\bmila\b', r'\babhi\b', r'\bkal\b', r'\baaj\b', r'\bdekha\b', r'\bruk\b', 
        r'\bthik\b', r'\btheek\b', r'\bkuch\b', r'\btera\b', r'\bmera\b', r'\btum\b',
        r'\bkarega\b', r'\bdekh\b', r'\bhoga\b', r'\bhogaya\b', r'\bkr\b', r'\bwoh\b'
    ]
    
    hindi_hits = sum(1 for pattern in hindi_markers if re.search(pattern, combined))
    if hindi_hits >= 1:
        return 'hinglish'
    return 'english'

def get_account4_system_prompt(topic, recent_messages, lang_mode):
    """
    Builds context instructions for Account 4 to speak naturally as a 4th group member.
    """
    lang_instruction = (
        "Respond in natural, casual Hinglish/Roman Hindi (e.g. 'hn dekha tha', 'kal batata hu', 'sahi lag raha h'). "
        "Do NOT speak in formal or textbook Hindi. Use natural Indian texting slang."
        if lang_mode in ('hinglish', 'hindi_roman') else
        "Respond in casual, conversational Indian English. Keep it natural and unforced."
    )
    
    prompt = (
        f"You are Account 4, a casual member in a Telegram group chat with your 3 close friends (Account 1, Account 2, Account 3).\n"
        f"Conversation topic: {topic or 'general talk'}.\n"
        f"Language style: {lang_instruction}\n"
        f"IMPORTANT RULES:\n"
        f"1. Keep your reply short and natural (1 to 2 short sentences maximum).\n"
        f"2. Never announce you are an AI or bot. You are just a friend in the group.\n"
        f"3. Do not spam emojis (use 0 or 1 natural emoji at most, or none).\n"
        f"4. Match the flow and vibe of the recent messages:\n"
        f"{chr(10).join(recent_messages[-4:])}\n"
        f"Your response:"
    )
    return prompt
