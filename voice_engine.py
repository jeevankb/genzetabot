import asyncio
import os
import random
import time
import uuid
import logging

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

VOICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")
os.makedirs(VOICE_DIR, exist_ok=True)

# Three distinct adult male/boy voice profiles
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
    Generates a realistic spoken voice note (.ogg) for the given account.
    Returns: (file_path, spoken_text) or (None, None) if unavailable.
    """
    if not HAS_EDGE_TTS:
        logging.warning("edge_tts is not installed. Voice note generation skipped.")
        return None, None

    profile = BOY_VOICE_PROFILES.get(account_key, BOY_VOICE_PROFILES["acc1"])
    
    # Select or clean text
    spoken_text = context_text
    if not spoken_text:
        cat_lines = SAMPLE_VOICE_LINES.get(category, SAMPLE_VOICE_LINES["banter"])
        candidates = [l for l in cat_lines if l not in recent_spoken_lines]
        spoken_text = random.choice(candidates if candidates else cat_lines)
    
    recent_spoken_lines.append(spoken_text)
    if len(recent_spoken_lines) > 30:
        recent_spoken_lines.pop(0)

    # Output file path
    filename = f"vn_{account_key}_{int(time.time())}_{uuid.uuid4().hex[:6]}.ogg"
    filepath = os.path.join(VOICE_DIR, filename)

    try:
        communicate = edge_tts.Communicate(
            text=spoken_text,
            voice=profile["voice"],
            rate=profile["rate"],
            pitch=profile["pitch"]
        )
        await communicate.save(filepath)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            logging.info(f"Generated realistic voice note for {account_key} ({profile['name']}): '{spoken_text}' -> {filepath}")
            return filepath, spoken_text
    except Exception as e:
        logging.error(f"Error generating voice note with edge-tts: {e}")
        if os.path.exists(filepath):
            try: os.remove(filepath)
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
