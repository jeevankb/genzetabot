import aiohttp
import asyncio
import logging
import time
import re

JIKAN_API_URL = "https://api.jikan.moe/v4/seasons/now"
ANILIST_API_URL = "https://graphql.anilist.co"

# In-memory cache for seasonal anime
_SEASONAL_ANIME_CACHE = [
    {"title": "Bleach: Thousand-Year Blood War - The Conflict", "episodes": 13, "genres": ["Action", "Supernatural"]},
    {"title": "Mushoku Tensei III", "episodes": 12, "genres": ["Fantasy", "Adventure"]},
    {"title": "Youjo Senki II", "episodes": 12, "genres": ["Action", "Military"]},
    {"title": "Sakamoto Days", "episodes": 12, "genres": ["Action", "Comedy"]},
    {"title": "Solo Leveling Season 2", "episodes": 13, "genres": ["Action", "Fantasy"]},
    {"title": "Dandadan", "episodes": 12, "genres": ["Action", "Supernatural"]},
    {"title": "Blue Lock vs. U-20 Japan", "episodes": 14, "genres": ["Sports"]},
    {"title": "Chainsaw Man - The Movie: Reze Arc", "episodes": 1, "genres": ["Action", "Supernatural"]}
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
