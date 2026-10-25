import asyncio
import aiohttp
import os
import random
import time
import uuid
import logging
from dotenv import load_dotenv

load_dotenv()

VOICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")
os.makedirs(VOICE_DIR, exist_ok=True)

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

def get_voice_mapping_summary() -> dict:
    """Returns the strict account-to-voice configuration mapping."""
    return {
        "acc1": {"name": ACCOUNT_NAMES["acc1"], "provider": "Fish Audio", "voice_id": FISH_VOICE_MODELS["acc1"]},
        "acc2": {"name": ACCOUNT_NAMES["acc2"], "provider": "Fish Audio", "voice_id": FISH_VOICE_MODELS["acc2"]},
        "acc3": {"name": ACCOUNT_NAMES["acc3"], "provider": "Fish Audio", "voice_id": FISH_VOICE_MODELS["acc3"]},
        "acc4": {"name": ACCOUNT_NAMES["acc4"], "provider": "ElevenLabs", "voice_id": ELEVENLABS_BOT_VOICE_ID}
    }

async def generate_fish_audio_voice(account_key: str, spoken_text: str) -> tuple[str, str]:
    """
    Synthesizes speech using the dedicated Fish Audio clone for the specified account.
    Strictly isolated: never falls back to generic TTS or another account's voice.
    """
    fish_key = os.getenv("FISH_AUDIO_API_KEY")
    if not fish_key:
        logging.warning(f"[VoiceEngine] Fish Audio API key missing for {account_key}.")
        return None, None

    ref_id = FISH_VOICE_MODELS.get(account_key)
    if not ref_id:
        logging.error(f"[VoiceEngine] No Fish Audio clone configured for account '{account_key}'.")
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
                        logging.info(f"🎙 [Fish Audio Cloned] Generated voice note for {ACCOUNT_NAMES.get(account_key, account_key)} (Model: {ref_id}): '{spoken_text[:50]}...'")
                        return filepath, spoken_text
                    else:
                        logging.warning(f"[VoiceEngine] Fish Audio returned empty or corrupt audio data for {account_key}.")
                        return None, None
                else:
                    err_text = await resp.text()
                    logging.warning(f"[VoiceEngine] Fish Audio API error HTTP {resp.status} for {account_key}: {err_text[:120]}")
                    return None, None
    except Exception as e:
        logging.warning(f"[VoiceEngine] Fish Audio request exception for {account_key}: {e}")
        return None, None

async def generate_bot_voice(spoken_text: str) -> tuple[str, str]:
    """
    Synthesizes speech using GenzetaBot's dedicated ElevenLabs voice.
    Strictly isolated: separate from all 3 Fish Audio voices, never falls back to generic TTS.
    """
    eleven_key = os.getenv("ELEVENLABS_API_KEY")
    if not eleven_key:
        logging.warning("[VoiceEngine] ElevenLabs API key missing for GenzetaBot.")
        return None, None

    voice_id = ELEVENLABS_BOT_VOICE_ID
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
                        logging.info(f"🎙 [ElevenLabs] Generated GenzetaBot speech (Voice: {voice_id}): '{spoken_text[:50]}...'")
                        return filepath, spoken_text
                    else:
                        logging.warning("[VoiceEngine] ElevenLabs returned empty audio payload.")
                        return None, None
                else:
                    err_text = await resp.text()
                    logging.warning(f"[VoiceEngine] ElevenLabs API error HTTP {resp.status}: {err_text[:120]}")
                    return None, None
    except Exception as e:
        logging.warning(f"[VoiceEngine] ElevenLabs request exception for GenzetaBot: {e}")
        return None, None

async def generate_voice_note(account_key: str, context_text: str = None, category: str = "banter") -> tuple[str, str]:
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
