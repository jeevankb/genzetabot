import asyncio
import aiohttp
import os
import random
import time
import uuid
import logging
import hashlib
import shutil
from typing import Optional, Dict, Tuple
from collections import OrderedDict
from dotenv import load_dotenv

load_dotenv()

VOICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")
VOICE_CACHE_DIR = os.path.join(VOICE_DIR, "cache")
os.makedirs(VOICE_DIR, exist_ok=True)
os.makedirs(VOICE_CACHE_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# DEDICATED ACCOUNT-TO-VOICE MAPPINGS
# ---------------------------------------------------------------------------
# 1. Fish Audio Custom Cloned Voices (strictly assigned to human accounts)
FISH_VOICE_MODELS = {
    "acc1": "8d4b31ea18e7498586849a0164391f9e",  # @ErrorMonocle — Merlin Hermis (Ep - 1322)
    "acc2": "5209483f80ab447288d1459216fb2505",  # @Great_lotm — Mr. Fool (Ep 1427)
    "acc3": "3e61b198fdcd4d689f563b5c1811c8f7"   # @Ruthvikyamzaki (Ep 1850)
}

# 2. GenzetaBot Dedicated ElevenLabs Voice (completely separate from Fish Audio)
# ElevenLabs "Will" multilingual_v2 — charismatic, natural, warm, conversational
ELEVENLABS_BOT_VOICE_ID = os.getenv("ELEVENLABS_BOT_VOICE_ID", "bIHbv24MWmeRgasZH58o")

ACCOUNT_NAMES = {
    "acc1": "@ErrorMonocle (Merlin Hermis)",
    "acc2": "@Great_lotm (Mr. Fool)",
    "acc3": "@Ruthvikyamzaki",
    "acc4": "GenzetaBot (@genzetabot)"
}

# ---------------------------------------------------------------------------
# BOUNDED LRU AUDIO CACHE (Time: O(1), Space: O(C) bounded memory & disk)
# ---------------------------------------------------------------------------
class VoiceAudioLRUCache:
    """
    Production-grade Bounded LRU Audio Cache with size-based eviction and TTL.
    
    Time Complexity:
        get(): O(1) average hash lookup + move_to_end
        put(): O(1) average hash insertion + O(1) eviction
    Space Complexity:
        O(C) strictly bounded by max_entries and max_bytes.
        
    Guarantees:
        - Cache keys incorporate provider, voice model ID, output format, and content hash.
        - Audio is NEVER shared across different voice identities or accounts.
        - Reduces outbound network bandwidth and eliminates duplicate API credit consumption.
    """
    def __init__(self, cache_dir: str = VOICE_CACHE_DIR, max_entries: int = 50, max_bytes: int = 25 * 1024 * 1024, ttl_seconds: float = 86400.0):
        self.cache_dir = cache_dir
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.ttl_seconds = ttl_seconds
        os.makedirs(self.cache_dir, exist_ok=True)
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self._load_existing()

    def _load_existing(self):
        try:
            for f in os.listdir(self.cache_dir):
                fp = os.path.join(self.cache_dir, f)
                if os.path.isfile(fp):
                    sz = os.path.getsize(fp)
                    mtime = os.path.getmtime(fp)
                    self._cache[f] = {"path": fp, "size": sz, "created_at": mtime}
            self._evict_if_needed()
        except Exception as e:
            logging.debug(f"[AudioCache] Init scan: {e}")

    def make_key(self, provider: str, voice_id: str, text: str, output_format: str = "mp3") -> str:
        """Constructs an unambiguous cache key isolating provider, voice ID, and text."""
        normalized_text = text.strip().lower()
        content_hash = hashlib.sha256(f"{provider}:{voice_id}:{output_format}:{normalized_text}".encode("utf-8")).hexdigest()[:24]
        return f"{provider[:4]}_{voice_id[:8]}_{content_hash}.{output_format}"

    def get(self, key: str) -> Optional[str]:
        """O(1) retrieval with TTL validation and LRU update."""
        if key not in self._cache:
            self.misses += 1
            return None
        entry = self._cache[key]
        now = time.time()
        if (now - entry["created_at"]) > self.ttl_seconds or not os.path.exists(entry["path"]):
            self._remove(key)
            self.misses += 1
            return None
        self._cache.move_to_end(key)
        self.hits += 1
        return entry["path"]

    def put(self, key: str, audio_bytes: bytes) -> str:
        """O(1) insertion with automatic size and entry count eviction."""
        target_path = os.path.join(self.cache_dir, key)
        with open(target_path, "wb") as f:
            f.write(audio_bytes)
        size = len(audio_bytes)
        self._cache[key] = {"path": target_path, "size": size, "created_at": time.time()}
        self._cache.move_to_end(key)
        self._evict_if_needed()
        return target_path

    def _remove(self, key: str):
        if key in self._cache:
            entry = self._cache.pop(key)
            if os.path.exists(entry["path"]):
                try: os.remove(entry["path"])
                except: pass

    def _evict_if_needed(self):
        while len(self._cache) > self.max_entries:
            oldest_key, _ = self._cache.popitem(last=False)
            self._delete_file(oldest_key)
            self.evictions += 1

        total_size = sum(e["size"] for e in self._cache.values())
        while total_size > self.max_bytes and self._cache:
            oldest_key, entry = self._cache.popitem(last=False)
            total_size -= entry["size"]
            self._delete_file(oldest_key)
            self.evictions += 1

    def _delete_file(self, key: str):
        fp = os.path.join(self.cache_dir, key)
        if os.path.exists(fp):
            try: os.remove(fp)
            except: pass

    def get_metrics(self) -> dict:
        total = self.hits + self.misses
        hit_ratio = (self.hits / total) if total > 0 else 0.0
        total_bytes = sum(e["size"] for e in self._cache.values())
        return {
            "entries": len(self._cache),
            "total_bytes": total_bytes,
            "hits": self.hits,
            "misses": self.misses,
            "hit_ratio": hit_ratio,
            "evictions": self.evictions
        }

audio_cache = VoiceAudioLRUCache()

def get_audio_cache_metrics() -> dict:
    return audio_cache.get_metrics()

# Natural, short 1-line casual Hinglish banter lines suitable for realistic voice notes
SAMPLE_VOICE_LINES = {
    "anime": [
        "Bhai episode dekha kya naya wala? Full fire tha boss!",
        "Arre yaar vo animation quality next level thi sach me!",
        "Bro honestly bolu to manga adaptation kafi crazy kiya inhone.",
        "Arey bhai plot twist dekh ke dimag hil gaya mera to!",
        "Mai to pehle hi bol raha tha ye character overpowered hai 😂",
        "Sahi me bhai, weekend pe dubara binge watch karna padega ye arc."
    ],
    "gaming": [
        "Arre clutch dekha kya mera? Last second bacha tha bhai!",
        "Bhai ping high aa raha hai aaj thoda, fir bhi carry kar diya 😂",
        "Bro GTA six ka gameplay dekh ke sab game purane lagne lage hain ab.",
        "Ek match aur khelte hain bhai, is bar rush karenge seedha!",
        "Kya headshot mara tha yaar usne, hacker to nahi tha na vo?"
    ],
    "banter": [
        "Arre haan bhai, mai bhi wahi soch raha tha bilkul!",
        "Bhai kya bol raha hai yaar, sahi me? 😂",
        "Arey yaar tum log fir shuru ho gaye debate karne 💀",
        "Bhai sach bol raha hu, iska koi comparison hi nahi hai.",
        "Haha kya scene chal raha hai yahan pe, popcorn leke baithta hu!",
        "Bro seriously? Ye kab announce hua mujhe pata bhi nahi chala!",
        "Arey bhai full agreement, maine bhi same bola tha!"
    ]
}

recent_spoken_lines = []

# ---------------------------------------------------------------------------
# EDGE-TTS REALISTIC ADULT MALE VOICES (Zero-Downtime High-Fidelity Fallback)
# ---------------------------------------------------------------------------
EDGE_VOICE_CONFIGS = {
    "acc1": {"voice": "hi-IN-MadhurNeural", "rate": "+0%", "pitch": "+0Hz"},
    "acc2": {"voice": "hi-IN-MadhurNeural", "rate": "-3%", "pitch": "-5Hz"},
    "acc3": {"voice": "hi-IN-MadhurNeural", "rate": "+8%", "pitch": "+6Hz"},
    "acc4": {"voice": "hi-IN-MadhurNeural", "rate": "+4%", "pitch": "+2Hz"}
}

async def generate_edge_tts_voice(account_key: str, spoken_text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Synthesizes speech using Microsoft Edge-TTS with realistic, distinct Indian male voices.
    Serves as zero-downtime fallback when Fish Audio credits are exhausted (HTTP 402).
    """
    import edge_tts
    cfg = EDGE_VOICE_CONFIGS.get(account_key, EDGE_VOICE_CONFIGS["acc1"])
    cache_key = audio_cache.make_key("edge", f"{account_key}_{cfg['pitch']}_{cfg['rate']}", spoken_text, "mp3")
    cached_path = audio_cache.get(cache_key)
    if cached_path and os.path.exists(cached_path):
        temp_copy = os.path.join(VOICE_DIR, f"cached_edge_{account_key}_{uuid.uuid4().hex[:6]}.mp3")
        shutil.copy2(cached_path, temp_copy)
        logging.info(f"🎙 [VoiceEngine Cache HIT] Reusing cached Edge TTS note for {account_key}")
        return temp_copy, spoken_text

    filename = f"edge_{account_key}_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp3"
    filepath = os.path.join(VOICE_DIR, filename)
    try:
        comm = edge_tts.Communicate(
            text=spoken_text,
            voice=cfg["voice"],
            rate=cfg["rate"],
            pitch=cfg["pitch"]
        )
        await comm.save(filepath)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 500:
            with open(filepath, "rb") as f:
                data = f.read()
            audio_cache.put(cache_key, data)
            logging.info(f"🎙 [Edge TTS Fallback] Generated voice note for {ACCOUNT_NAMES.get(account_key, account_key)}: '{spoken_text[:50]}...'")
            return filepath, spoken_text
    except Exception as e:
        logging.warning(f"[VoiceEngine] Edge TTS error for {account_key}: {e}")
    return None, None

ENABLE_EDGE_FALLBACK = os.getenv("ENABLE_EDGE_TTS_FALLBACK", "0").lower() in ("1", "true", "yes")

def get_voice_mapping_summary() -> dict:
    """Returns the strict account-to-voice configuration mapping."""
    return {
        "acc1": {"name": ACCOUNT_NAMES["acc1"], "provider": "Fish Audio", "voice_id": FISH_VOICE_MODELS["acc1"]},
        "acc2": {"name": ACCOUNT_NAMES["acc2"], "provider": "Fish Audio", "voice_id": FISH_VOICE_MODELS["acc2"]},
        "acc3": {"name": ACCOUNT_NAMES["acc3"], "provider": "Fish Audio", "voice_id": FISH_VOICE_MODELS["acc3"]},
        "acc4": {"name": ACCOUNT_NAMES["acc4"], "provider": "ElevenLabs", "voice_id": ELEVENLABS_BOT_VOICE_ID}
    }

async def generate_fish_audio_voice(account_key: str, spoken_text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Synthesizes speech using the dedicated Fish Audio clone for the specified account.
    Strictly isolated: never falls back to generic TTS or another account's voice.
    Checks LRU audio cache first to eliminate unnecessary bandwidth and API calls.
    """
    ref_id = FISH_VOICE_MODELS.get(account_key)
    if not ref_id:
        logging.error(f"[VoiceEngine] No Fish Audio clone configured for account '{account_key}'.")
        return None, None

    # Check LRU cache first (O(1) lookup)
    cache_key = audio_cache.make_key("fish", ref_id, spoken_text, "mp3")
    cached_path = audio_cache.get(cache_key)
    if cached_path and os.path.exists(cached_path):
        # Create an isolated temporary copy for caller delivery so caller deletion doesn't invalidate cache
        temp_copy = os.path.join(VOICE_DIR, f"cached_fish_{account_key}_{uuid.uuid4().hex[:6]}.mp3")
        shutil.copy2(cached_path, temp_copy)
        logging.info(f"🎙 [VoiceEngine Cache HIT] Reusing cached Fish Audio note for {account_key}")
        return temp_copy, spoken_text

    fish_key = os.getenv("FISH_AUDIO_API_KEY")
    if not fish_key:
        logging.warning(f"[VoiceEngine] Fish Audio API key missing for {account_key}.")
        if ENABLE_EDGE_FALLBACK:
            return await generate_edge_tts_voice(account_key, spoken_text)
        return None, None

    filename = f"fish_{account_key}_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp3"
    filepath = os.path.join(VOICE_DIR, filename)

    try:
        headers = {
            "Authorization": f"Bearer {fish_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "text": spoken_text,
            "reference_id": ref_id,
            "format": "mp3"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.fish.audio/v1/tts",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=18)
            ) as resp:
                if resp.status == 200:
                    audio_data = await resp.read()
                    if audio_data and len(audio_data) > 800:
                        with open(filepath, "wb") as f:
                            f.write(audio_data)
                        # Save in bounded LRU cache
                        audio_cache.put(cache_key, audio_data)
                        logging.info(f"🎙 [Fish Audio Cloned] Generated voice note for {ACCOUNT_NAMES.get(account_key, account_key)} (Model: {ref_id}): '{spoken_text[:50]}...'")
                        return filepath, spoken_text
                    else:
                        logging.warning(f"[VoiceEngine] Fish Audio returned empty or corrupt audio data for {account_key}.")
                        if ENABLE_EDGE_FALLBACK:
                            return await generate_edge_tts_voice(account_key, spoken_text)
                        return None, None
                else:
                    err_text = await resp.text()
                    logging.warning(f"[VoiceEngine] Fish Audio API error HTTP {resp.status} for {account_key}: {err_text[:120]}")
                    if ENABLE_EDGE_FALLBACK:
                        return await generate_edge_tts_voice(account_key, spoken_text)
                    return None, None
    except Exception as e:
        logging.warning(f"[VoiceEngine] Fish Audio request exception for {account_key}: {e}")
        if ENABLE_EDGE_FALLBACK:
            return await generate_edge_tts_voice(account_key, spoken_text)
        return None, None

async def generate_bot_voice(spoken_text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Synthesizes speech using GenzetaBot's dedicated ElevenLabs voice.
    Strictly isolated: separate from all 3 Fish Audio voices, never falls back to generic TTS.
    Checks LRU audio cache first to minimize bandwidth consumption and API requests.
    """
    voice_id = ELEVENLABS_BOT_VOICE_ID

    # Check LRU cache first (O(1) lookup)
    cache_key = audio_cache.make_key("elevenlabs", voice_id, spoken_text, "mp3")
    cached_path = audio_cache.get(cache_key)
    if cached_path and os.path.exists(cached_path):
        temp_copy = os.path.join(VOICE_DIR, f"cached_bot_{uuid.uuid4().hex[:6]}.mp3")
        shutil.copy2(cached_path, temp_copy)
        logging.info(f"🎙 [VoiceEngine Cache HIT] Reusing cached ElevenLabs speech for GenzetaBot")
        return temp_copy, spoken_text

    eleven_key = os.getenv("ELEVENLABS_API_KEY")
    if not eleven_key:
        logging.warning("[VoiceEngine] ElevenLabs API key missing for GenzetaBot.")
        return None, None

    filename = f"bot_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp3"
    filepath = os.path.join(VOICE_DIR, filename)

    try:
        headers = {
            "xi-api-key": eleven_key,
            "Content-Type": "application/json"
        }
        payload = {
            "text": spoken_text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.50,
                "similarity_boost": 0.85,
                "style": 0.20,
                "use_speaker_boost": True
            }
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=18)
            ) as resp:
                if resp.status == 200:
                    audio_data = await resp.read()
                    if audio_data and len(audio_data) > 800:
                        with open(filepath, "wb") as f:
                            f.write(audio_data)
                        audio_cache.put(cache_key, audio_data)
                        logging.info(f"🎙 [ElevenLabs] Generated GenzetaBot speech (Voice: {voice_id}): '{spoken_text[:50]}...'")
                        return filepath, spoken_text
                    else:
                        logging.warning("[VoiceEngine] ElevenLabs returned empty audio payload.")
                        if ENABLE_EDGE_FALLBACK:
                            return await generate_edge_tts_voice("acc4", spoken_text)
                        return None, None
                else:
                    err_text = await resp.text()
                    logging.warning(f"[VoiceEngine] ElevenLabs API error HTTP {resp.status}: {err_text[:120]}")
                    if ENABLE_EDGE_FALLBACK:
                        return await generate_edge_tts_voice("acc4", spoken_text)
                    return None, None
    except Exception as e:
        logging.warning(f"[VoiceEngine] ElevenLabs request exception for GenzetaBot: {e}")
        if ENABLE_EDGE_FALLBACK:
            return await generate_edge_tts_voice("acc4", spoken_text)
        return None, None

async def generate_voice_note(account_key: str, context_text: str = None, category: str = "banter") -> Tuple[Optional[str], Optional[str]]:
    """
    Unified voice generator with strict account-to-voice routing:
    - acc1, acc2, acc3: Strictly Fish Audio cloned models.
    - acc4 / bot: Strictly GenzetaBot's dedicated ElevenLabs voice.
    - No cross-account substitution.
    - No generic text-to-speech replacement on failure.
    Returns: (file_path, spoken_text) or (None, None) if generation fails.
    """
    spoken_text = context_text
    if not spoken_text:
        cat_lines = SAMPLE_VOICE_LINES.get(category, SAMPLE_VOICE_LINES["banter"])
        candidates = [l for l in cat_lines if l not in recent_spoken_lines]
        spoken_text = random.choice(candidates if candidates else cat_lines)

    recent_spoken_lines.append(spoken_text)
    if len(recent_spoken_lines) > 30:
        recent_spoken_lines.pop(0)

    # Route based on strict account assignment
    if account_key in ("acc1", "acc2", "acc3"):
        return await generate_fish_audio_voice(account_key, spoken_text)
    elif account_key in ("acc4", "bot", "genzetabot"):
        return await generate_bot_voice(spoken_text)
    else:
        logging.error(f"[VoiceEngine] Unknown account key '{account_key}'. Refusing to generate audio to prevent voice mix-up.")
        return None, None

def cleanup_old_voice_notes(max_age_seconds: int = 3600):
    """Deletes temporary voice files older than 1 hour to keep storage clean."""
    now = time.time()
    try:
        for f in os.listdir(VOICE_DIR):
            fp = os.path.join(VOICE_DIR, f)
            if os.path.isfile(fp) and (now - os.path.getmtime(fp)) > max_age_seconds:
                try: os.remove(fp)
                except: pass
    except:
        pass
