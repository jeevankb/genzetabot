import asyncio
import aiohttp
import os
import random
import time
import uuid
import logging
from dotenv import load_dotenv

load_dotenv()

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

VOICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")
os.makedirs(VOICE_DIR, exist_ok=True)

FISH_AUDIO_KEY = os.getenv("FISH_AUDIO_API_KEY")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY")

# 1. Custom Cloned Voices on Fish Audio (Created from user audio episodes)
FISH_VOICE_MODELS = {
    "acc1": "8d4b31ea18e7498586849a0164391f9e",  # mrmerlin (Account 1 - Ep - 1322)
    "acc2": "5209483f80ab447288d1459216fb2505",  # Mrfool (Account 2 - Ep 1427)
    "acc3": "3e61b198fdcd4d689f563b5c1811c8f7"   # ruthvikyamzaki (Account 3 - Ep 1850)
}

# 2. ElevenLabs Natural Human Male Voices
ELEVENLABS_VOICE_MODELS = {
    "acc1": "TX3LPaxmHKxFdv7VOQHJ",  # Liam (Energetic young adult)
    "acc2": "IKne3meq5aSn9XLyUdCD",  # Charlie (Deeper casual guy)
    "acc3": "CwhRBWXzGAHq8TQ4Fs17"   # Roger (Laid-back resonant guy)
}

# 3. Edge-TTS Neural Fallbacks
BOY_VOICE_PROFILES = {
    "acc1": {
        "name": "Boy 1 (Casual Adult Guy)",
        "voice": "hi-IN-MadhurNeural",
        "rate": "+4%",
        "pitch": "+0Hz"
    },
    "acc2": {
        "name": "Boy 2 (Deeper Chill Guy)",
        "voice": "hi-IN-MadhurNeural",
        "rate": "-3%",
        "pitch": "-6Hz"
    },
    "acc3": {
        "name": "Boy 3 (Energetic Expressive Guy)",
        "voice": "hi-IN-MadhurNeural",
        "rate": "+8%",
        "pitch": "+6Hz"
    }
}

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

async def generate_voice_note(account_key: str, context_text: str = None, category: str = "banter") -> tuple[str, str]:
    """
    Generates a realistic spoken voice note (.ogg/.mp3) for the given account.
    Prioritizes:
    1. Fish Audio Custom Cloned Models (mrmerlin, Mrfool, ruthvikyamzaki)
    2. ElevenLabs Multilingual v2 Ultra-Realistic Voices (Liam, Charlie, Roger)
    3. Edge-TTS Neural Male Profiles (Pitch/Rate calibrated)
    Returns: (file_path, spoken_text) or (None, None) if unavailable.
    """
    spoken_text = context_text
    if not spoken_text:
        cat_lines = SAMPLE_VOICE_LINES.get(category, SAMPLE_VOICE_LINES["banter"])
        candidates = [l for l in cat_lines if l not in recent_spoken_lines]
        spoken_text = random.choice(candidates if candidates else cat_lines)
    
    recent_spoken_lines.append(spoken_text)
    if len(recent_spoken_lines) > 30:
        recent_spoken_lines.pop(0)

    filename = f"vn_{account_key}_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp3"
    filepath = os.path.join(VOICE_DIR, filename)

    # -------------------------------------------------------------
    # 1. ATTEMPT FISH AUDIO CLONED MODEL (Option C)
    # -------------------------------------------------------------
    fish_key = os.getenv("FISH_AUDIO_API_KEY") or FISH_AUDIO_KEY
    if fish_key and account_key in FISH_VOICE_MODELS:
        ref_id = FISH_VOICE_MODELS[account_key]
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
                async with session.post("https://api.fish.audio/v1/tts", headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        audio_data = await resp.read()
                        if audio_data and len(audio_data) > 1000:
                            with open(filepath, "wb") as f:
                                f.write(audio_data)
                            logging.info(f"🎙 [Fish Audio Cloned] Generated voice note for {account_key} (Model: {ref_id}): '{spoken_text}'")
                            return filepath, spoken_text
                    else:
                        logging.warning(f"Fish Audio returned {resp.status} (Credits check required), failing over to ElevenLabs...")
        except Exception as fe:
            logging.warning(f"Fish Audio generation error: {fe}, failing over...")

    # -------------------------------------------------------------
    # 2. ATTEMPT ELEVENLABS MULTILINGUAL v2 (Option A)
    # -------------------------------------------------------------
    eleven_key = os.getenv("ELEVENLABS_API_KEY") or ELEVENLABS_KEY
    if eleven_key and account_key in ELEVENLABS_VOICE_MODELS:
        voice_id = ELEVENLABS_VOICE_MODELS[account_key]
        try:
            headers = {
                "xi-api-key": eleven_key,
                "Content-Type": "application/json"
            }
            payload = {
                "text": spoken_text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.45,
                    "similarity_boost": 0.80,
                    "style": 0.25,
                    "use_speaker_boost": True
                }
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}", headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        audio_data = await resp.read()
                        if audio_data and len(audio_data) > 1000:
                            with open(filepath, "wb") as f:
                                f.write(audio_data)
                            logging.info(f"🎙 [ElevenLabs] Generated realistic speech for {account_key} (Voice: {voice_id}): '{spoken_text}'")
                            return filepath, spoken_text
                    else:
                        logging.warning(f"ElevenLabs returned {resp.status}, failing over to Edge-TTS...")
        except Exception as ee:
            logging.warning(f"ElevenLabs generation error: {ee}, failing over...")

    # -------------------------------------------------------------
    # 3. ATTEMPT EDGE-TTS NEURAL MALE PROFILES
    # -------------------------------------------------------------
    if HAS_EDGE_TTS:
        profile = BOY_VOICE_PROFILES.get(account_key, BOY_VOICE_PROFILES["acc1"])
        ogg_filepath = filepath.replace(".mp3", ".ogg")
        try:
            communicate = edge_tts.Communicate(
                text=spoken_text,
                voice=profile["voice"],
                rate=profile["rate"],
                pitch=profile["pitch"]
            )
            await communicate.save(ogg_filepath)
            if os.path.exists(ogg_filepath) and os.path.getsize(ogg_filepath) > 0:
                logging.info(f"🎙 [Edge-TTS] Generated voice note for {account_key} ({profile['name']}): '{spoken_text}'")
                return ogg_filepath, spoken_text
        except Exception as e:
            logging.error(f"Error generating voice note with edge-tts: {e}")
            if os.path.exists(ogg_filepath):
                try: os.remove(ogg_filepath)
                except: pass

    return None, None

def cleanup_old_voice_notes(max_age_seconds: int = 3600):
    """Deletes voice files older than 1 hour to keep storage clean."""
    now = time.time()
    try:
        for f in os.listdir(VOICE_DIR):
            fp = os.path.join(VOICE_DIR, f)
            if os.path.isfile(fp) and (now - os.path.getmtime(fp)) > max_age_seconds:
                try: os.remove(fp)
                except: pass
    except:
        pass
