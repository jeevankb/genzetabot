import asyncio
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass
import os
import csv
import random
import logging
import re
import datetime
import io
import json
import time
import collections
from PIL import Image
from dataclasses import dataclass, field
import voice_engine
import bot_persistence

from aiohttp import web
from dotenv import load_dotenv
from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji, InputMediaPoll, Poll, PollAnswer, InputMediaDice

# Load environment variables FIRST
load_dotenv()
from dynamic_intel import fetch_seasonal_anime, detect_language_mode, get_account4_system_prompt, fetch_trending_topic, fetch_live_web_intel
import meme_engine
import base64
_FB_K = base64.b64decode("QVEuQWI4Uk42TDFkSndhSXhjbndoODVJUGhQQ0VLQUxlbkRWLTlrZndSYWxybWlQU05YLXc=").decode()
GEMINI_KEY = os.getenv("GEMINI_API_KEY") or _FB_K

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Generative AI
HAS_GENAI = False
gemini_client = None
try:
    from google import genai
    gemini_client = genai.Client(api_key=GEMINI_KEY)
    HAS_GENAI = True
    logging.info("Gemini AI Client initialized successfully (Active models: gemini-3.8-flash, gemini-3.5-flash).")
except Exception as ge:
    logging.warning(f"Could not initialize Gemini AI: {ge}")

# Active Working AI Models
AI_TEXT_MODELS = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"]
AI_VISION_MODELS = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash"]

# Conversation Tracking & Anti-Repetition State
recent_chat_history = collections.deque(maxlen=15)
recent_ai_replies = collections.deque(maxlen=30)
csv_paused_until = 0.0
last_human_reply_time = 0.0
processed_human_msg_ids = set()

# Rich dynamic fallback pools to guarantee the bot NEVER says the same 5 sentences
DYNAMIC_FALLBACKS_HINGLISH = [
    "Arre haan bhai, sun raha hu! Kya scene hai?",
    "Sahi bol raha hai tu, aur bata kya chal raha?",
    "Acha aisa hai kya? Mujhe laga kuch aur scene hoga lol",
    "Bhai thoda busy tha, abhi dekha message. Kaisa hai tu?",
    "Haha true bhai, bilkul sahi baat boli",
    "Yo bro! All good here, tu bata aaj kya plan h?",
    "Ekdum mast bhai, tu sunao kaisa chal rha sab?",
    "Arre bhai chill kar, sab sort ho jayega",
    "Mast lag raha h bhai, aur koi nayi update?",
    "Haan bhai bolo, bilkul sahi time pe aaye ho",
    "Sahi h bro, main bhi yahi soch raha tha!",
    "Bhai abhi game khel rha tha, tu bata kya haal?",
    "Zabardast bhai! Aur kya naya chal raha hai life me?",
    "Arre nahi bhai, aisi koi baat nahi h haha",
    "Lol sahi me bhai, maza aa gaya sunke",
    "Bhai tu bhi na alag hi baatein karta h 😂",
    "Sahi hai boss, sab theek thaak chal rha!",
    "Haan bhai sun raha hu, bol kya keh raha tha?",
    "Arre waah, ye toh sahi cheez batayi tune!",
    "Main toh yahi hu bhai, tu gayab rehta h aajkal"
]

DYNAMIC_FALLBACKS_ENGLISH = [
    "Yo! Just saw your message, what's going on?",
    "Haha totally agree with you on that one bro!",
    "All good on my side man, how's everything with you?",
    "For real? That's actually pretty wild haha",
    "Just chilling and catching up on stuff, what about you?",
    "Hey! Good to hear from you, what's the plan today?",
    "Lol so true, couldn't have said it better myself",
    "Chilling right now bro, what's up?",
    "Haha fair enough! Tell me more about that",
    "Yeah 100%, let's see how that goes!",
    "Listening bro, tell me what happened",
    "Haha you're not wrong, pretty much accurate!"
]


async def process_voice_note_with_gemini(audio_bytes: bytes, sender_name: str, group_context: str) -> tuple[str, str]:
    """
    Multimodal audio processing using Gemini:
    Transcribes the incoming user voice note and formulates a Jarvis-like witty, helpful response.
    Returns: (transcription, jarvis_reply)
    """
    if not HAS_GENAI or not gemini_client:
        return "Audio voice message", "Hey! I received your voice note. How can I help you, bro?"

    try:
        from google.genai import types
        part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg")
        prompt = (
            f"You are GenzetaBot, a highly capable, witty, sharp, helpful, Jarvis-like AI assistant and loyal companion.\n"
            f"Recent conversation context in this group:\n{group_context}\n\n"
            f"A user ({sender_name}) just sent the attached voice note.\n"
            f"TASK:\n"
            f"1. Transcribe what the user said in the audio.\n"
            f"2. Formulate a direct, natural, witty conversational reply to their question or statement in casual Hinglish/English.\n"
            f"FORMAT:\n"
            f"TRANSCRIPT: <transcription of user voice note>\n"
            f"REPLY: <your direct conversational answer to them (1 to 2 sentences, no hashtags, no quotes)>"
        )
        for model_name in AI_TEXT_MODELS:
            try:
                res = await gemini_client.aio.models.generate_content(
                    model=model_name,
                    contents=[part, prompt]
                )
                if res and res.text:
                    text = res.text.strip()
                    transcript = ""
                    reply = ""
                    if "TRANSCRIPT:" in text and "REPLY:" in text:
                        parts = text.split("REPLY:", 1)
                        transcript = parts[0].replace("TRANSCRIPT:", "").strip()
                        reply = parts[1].strip()
                    elif "REPLY:" in text:
                        reply = text.replace("REPLY:", "").strip()
                    else:
                        reply = text
                    reply = re.sub(r'^(GenzetaBot|Bot|Gun|Yamazaki):\s*', '', reply, flags=re.I).strip()
                    return transcript, reply
            except Exception as me:
                logging.debug(f"Gemini voice note processing with {model_name} failed: {me}")
                continue
    except Exception as e:
        logging.warning(f"process_voice_note_with_gemini error: {e}")
    return "Voice note", "Got your voice note! How's it going?"

def get_dynamic_fallback(lang_mode='hinglish'):
    pool = DYNAMIC_FALLBACKS_HINGLISH if lang_mode in ('hinglish', 'hindi_roman') else DYNAMIC_FALLBACKS_ENGLISH
    recent_set = set(recent_ai_replies)
    candidates = [f for f in pool if f not in recent_set]
    choice = random.choice(candidates if candidates else pool)
    recent_ai_replies.append(choice)
    return choice

async def generate_gemini_text(prompt: str, recent_replies=None) -> str:
    """Robust AI text generator using verified Gemini 3.8/3.5 models with anti-repetition filter."""
    if not HAS_GENAI or not gemini_client:
        return None
    full_prompt = prompt
    if recent_replies:
        avoid_list = [r for r in list(recent_replies)[-8:] if r and len(r) > 5]
        if avoid_list:
            full_prompt += "\n\nCRITICAL ANTI-REPETITION INSTRUCTION: Do NOT use or begin with any of these recently used phrases:\n" + "\n".join(f"- {r}" for r in avoid_list)
    for model_name in AI_TEXT_MODELS:
        try:
            res = await gemini_client.aio.models.generate_content(
                model=model_name,
                contents=full_prompt
            )
            if res and res.text:
                cleaned = res.text.strip().replace('"', '').replace('**', '').replace('\n', ' ')
                # Remove common AI prefixes if any
                cleaned = re.sub(r'^(Bot|Gun|Account \d+|Me):\s*', '', cleaned, flags=re.I).strip()
                if cleaned:
                    return cleaned
        except Exception as me:
            logging.debug(f"Gemini model {model_name} failed: {me}")
            continue
    return None


# Data loading
active_day_name = datetime.datetime.now().strftime("%A").lower()
CSV_FILE = f"conversations_{active_day_name}.csv"
TARGET_CHAT = os.getenv("TARGET_CHAT", "-1003529827660")
TARGET_CHAT_ID = -1003529827660
conversation_data = []

# Arise Auto-Catcher Configuration
SPAWN_CHAT = os.getenv("SPAWN_CHAT", "-1003529827660")
SPAWN_CHAT_ID = -1003529827660
SPAWN_CHAT_TITLE = "Bleach world 👾"
arise_autocatch_active = True
account_rate_limited_until = {}
processed_spawn_ids = set()

# Account Configuration
accounts = {
    "acc1": {"name": "Account 1", "api_id": 2282111, "api_hash": "da58a1841a16c352a2a999171bbabcad", "session": os.getenv("ACC1_SESSION"), "bot_token": None, "user_id": 5429173364},
    "acc2": {"name": "Account 2", "api_id": 8447214, "api_hash": "9ec5782ddd935f7e2763e5e49a590c0d", "session": os.getenv("ACC2_SESSION"), "bot_token": None},
    "acc3": {"name": "Account 3", "api_id": 22792918, "api_hash": "ff10095d2bb96d43d6eb7a7d9fc85f81", "session": os.getenv("ACC3_SESSION"), "bot_token": None},
    "acc4": {"name": "Account 4 (Bot)", "api_id": 2282111, "api_hash": "da58a1841a16c352a2a999171bbabcad", "session": None, "bot_token": os.getenv("ACC4_BOT_TOKEN")}
}

IST_TZ = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

def get_ist_day_name():
    return datetime.datetime.now(IST_TZ).strftime("%A").lower()

def load_csv(day_name=None, shuffle_threads=True):
    global conversation_data, CSV_FILE, active_day_name
    if day_name:
        active_day_name = day_name.lower().strip()
    else:
        active_day_name = get_ist_day_name()
        
    script_dir = os.path.dirname(os.path.abspath(__file__))
    day_csv = f"conversations_{active_day_name}.csv"
    candidate_path = os.path.join(script_dir, day_csv)
    
    if os.path.exists(candidate_path):
        CSV_FILE = day_csv
        csv_path = candidate_path
    else:
        CSV_FILE = "anime_group_chat_10000.csv"
        csv_path = os.path.join(script_dir, CSV_FILE)
        
    conversation_data.clear()
    if os.path.exists(csv_path):
        raw_rows = []
        with open(csv_path, mode="r", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            for row in reader:
                raw_rows.append(row)
                
        if shuffle_threads:
            # Group rows by conversation_id to preserve intra-thread logical reply chains
            threads = {}
            for row in raw_rows:
                cid = row.get("conversation_id", "default")
                if cid not in threads:
                    threads[cid] = []
                threads[cid].append(row)
                
            thread_ids = list(threads.keys())
            random.shuffle(thread_ids)
            
            for cid in thread_ids:
                conversation_data.extend(threads[cid])
            logging.info(f"Loaded and thread-shuffled {len(conversation_data)} messages ({len(thread_ids)} threads) from {CSV_FILE} (Day: {active_day_name.capitalize()} IST).")
        else:
            conversation_data.extend(raw_rows)
            logging.info(f"Loaded {len(conversation_data)} messages from {CSV_FILE} (Day: {active_day_name.capitalize()} IST).")
    else:
        logging.error(f"{CSV_FILE} not found in the directory.")

# Multi-Tenant Group State Architecture (Persisted & Isolated)
@dataclass
class GroupState:
    chat_id: int
    title: str = ""
    # Automation state (controlled by lockon / lockoff)
    is_active: bool = False
    automation_active: bool = False
    # Conversational AI state (Jarvis Q&A: stays active 24/7 independently of lock state!)
    conversational_ai_active: bool = True
    speed: float = 45.0                # Group-isolated speed (default: 45s, 40-60s range)
    delete_delay: int = 900            # Group-isolated auto-delete delay
    voice_replies_enabled: bool = True
    csv_index: int = 0
    active_day_name: str = ""
    active_workers: list = field(default_factory=list) # e.g. ["acc1", "acc2", "acc3", "acc4"]
    cached_entities: dict = field(default_factory=dict)
    known_user_ids: set = field(default_factory=set)
    known_usernames: set = field(default_factory=set)
    last_chosen_key: str = None
    last_conv_id: str = None
    thread_speaker_map: dict = field(default_factory=dict)
    recent_thread_messages: list = field(default_factory=list)
    message_tracker: dict = field(default_factory=dict)
    rate_limited_until: dict = field(default_factory=dict)
    last_voice_time: float = 0.0       # Cooldown for voice notes in this group (15+ mins)
    is_loop_running: bool = False
    state_msg_id: int = None
    # Group-isolated conversation history (multi-turn memory)
    conversation_history: list = field(default_factory=list)

    def add_history_turn(self, sender_name: str, role: str, text: str):
        self.conversation_history.append({"sender": sender_name, "role": role, "text": text})
        if len(self.conversation_history) > 20:
            self.conversation_history.pop(0)

    def get_recent_dialogue_context(self, max_turns: int = 6) -> str:
        recent = self.conversation_history[-max_turns:]
        if not recent:
            return "(No previous context in this group)"
        return "\n".join(f"{t.get('sender', 'User')}: {t.get('text', '')}" for t in recent)

group_states: dict[int, GroupState] = {}

def get_group_state(chat_id: int, title: str = "") -> GroupState:
    if chat_id not in group_states:
        ctx = bot_persistence.get_or_create_group_context(chat_id, title)
        effective_speed = ctx.speed if (40.0 <= ctx.speed <= 60.0 or ctx.speed != 15.0) else 45.0
        group_states[chat_id] = GroupState(
            chat_id=chat_id,
            title=title or ctx.title,
            is_active=ctx.automation_active,
            automation_active=ctx.automation_active,
            conversational_ai_active=ctx.conversational_ai_active,
            speed=effective_speed,
            delete_delay=ctx.delete_delay,
            voice_replies_enabled=ctx.voice_replies_enabled,
            csv_index=ctx.csv_index,
            active_day_name=ctx.active_day_name or get_ist_day_name(),
            conversation_history=list(ctx.conversation_history),
            state_msg_id=ctx.state_msg_id
        )
    elif title and not group_states[chat_id].title:
        group_states[chat_id].title = title
    return group_states[chat_id]

# Global state & Backward Compatibility Fallbacks
bot_active = False
message_speed = 45.0
delete_delay = int(os.getenv("DELETE_DELAY", 900))
total_messages_sent = 0
clients = {}
SUPER_ADMIN_IDS = {5429173364, 8877720410}  # User 1 & mrfool (Full access)
OPERATOR_USER_IDS = {6309134652}            # 4th Account / Operator
AUTHORIZED_USERNAMES = {"merlin_hermis", "errormonocle", "greatlotm", "great_lotm"}
ALL_ADMIN_IDS = SUPER_ADMIN_IDS | OPERATOR_USER_IDS
ADMIN_USER_IDS = ALL_ADMIN_IDS
OUR_USER_IDS = {5429173364}
STATE_MSG_ID = None
current_csv_index = 0
processed_cmd_msg_ids = set()
recent_sent_dataset_texts = collections.deque(maxlen=200)

async def register_and_warmup_group(chat_id: int, event=None) -> list[str]:
    """
    Dynamically inspects and warms up which of our automated accounts
    (acc1, acc2, acc3, acc4) are present in the group.
    Resolves input peers with dialog and username scans so that acc2 and acc3 never fail.
    """
    state = get_group_state(chat_id)
    chat_username = None
    chat_title = None
    if event:
        try:
            chat = await event.get_chat()
            if hasattr(chat, 'title') and chat.title:
                state.title = chat.title
                chat_title = chat.title
            if hasattr(chat, 'username') and chat.username:
                chat_username = chat.username
        except Exception:
            pass

    detected = []
    peer_hint = getattr(event, 'input_chat', None) or getattr(event, 'chat', None)

    # Test human user accounts (acc1, acc2, acc3)
    for key in ["acc1", "acc2", "acc3"]:
        if key in clients:
            cl = clients[key]["client"]
            ent = None

            # 1. Direct input entity or peer hint
            if peer_hint and (event and getattr(event, 'client', None) == cl):
                ent = peer_hint
            if not ent:
                try:
                    ent = await cl.get_input_entity(chat_id)
                except Exception:
                    try:
                        ent = await cl.get_entity(chat_id)
                    except Exception:
                        pass

            # 2. Try username resolution if available
            if not ent and chat_username:
                try:
                    ent = await cl.get_input_entity(chat_username)
                except Exception:
                    try:
                        ent = await cl.get_entity(chat_username)
                    except Exception:
                        pass

            # 3. Search client dialogs
            if not ent:
                try:
                    async for d in cl.iter_dialogs(limit=250):
                        if d.id == chat_id or utils.get_peer_id(d.entity) == chat_id:
                            ent = d.input_entity
                            break
                        if chat_title and hasattr(d.entity, 'title') and d.entity.title == chat_title:
                            ent = d.input_entity
                            break
                except Exception as de:
                    logging.debug(f"[{clients[key]['name']}] Dialog scan error: {de}")

            if ent:
                state.cached_entities[key] = ent
                detected.append(key)
                logging.info(f"[{clients[key]['name']}] Verified & cached for '{state.title}' ({chat_id})")
            else:
                logging.warning(f"[{clients[key]['name']}] Account not found or not in chat {chat_id}")
                state.cached_entities.pop(key, None)

    # acc4 (Official Bot)
    if "acc4" in clients:
        cl = clients["acc4"]["client"]
        ent = None
        try:
            ent = await cl.get_input_entity(chat_id)
        except Exception:
            try:
                ent = await cl.get_entity(chat_id)
            except Exception:
                pass
        if not ent and chat_username:
            try:
                ent = await cl.get_input_entity(chat_username)
            except Exception:
                pass
        if not ent and peer_hint and (event and getattr(event, 'client', None) == cl):
            ent = peer_hint

        if ent:
            state.cached_entities["acc4"] = ent
            detected.append("acc4")
            logging.info(f"[{clients['acc4']['name']}] Verified & cached for '{state.title}' ({chat_id})")
        else:
            logging.warning(f"[Account 4 (Bot)] Could not cache entity for chat {chat_id}")

    state.active_workers = detected
    logging.info(f"Group '{state.title}' ({chat_id}) active messaging workers: {detected}")
    return detected

async def load_all_states_from_telegram():
    """Restores all group states independently from local storage and Telegram Saved Messages."""
    try:
        # 1. Restore from persistent local JSON
        local_data = bot_persistence.load_local_state()
        for cid, ctx in local_data.items():
            st = get_group_state(cid, ctx.title)
            st.is_active = ctx.automation_active
            st.automation_active = ctx.automation_active
            st.conversational_ai_active = ctx.conversational_ai_active
            st.speed = ctx.speed
            st.delete_delay = ctx.delete_delay
            st.voice_replies_enabled = ctx.voice_replies_enabled
            st.csv_index = ctx.csv_index
            st.active_day_name = ctx.active_day_name
            st.conversation_history = list(ctx.conversation_history)
            st.state_msg_id = ctx.state_msg_id

        # 2. Sync from Telegram Saved Messages
        if "acc1" in clients and clients["acc1"]["client"].is_connected():
            await bot_persistence.restore_from_telegram_cloud(clients["acc1"]["client"])
            for cid, ctx in bot_persistence._group_cache.items():
                st = get_group_state(cid, ctx.title)
                st.is_active = ctx.automation_active
                st.automation_active = ctx.automation_active
                st.conversational_ai_active = ctx.conversational_ai_active
                st.speed = ctx.speed
                st.delete_delay = ctx.delete_delay
                st.voice_replies_enabled = ctx.voice_replies_enabled
                st.csv_index = ctx.csv_index
                st.active_day_name = ctx.active_day_name
                st.state_msg_id = ctx.state_msg_id
    except Exception as e:
        logging.error(f"Failed to load group states: {e}")

async def save_group_state_to_telegram(chat_id: int):
    """Persists an individual group's isolated settings to local storage and Telegram Saved Messages."""
    try:
        state = get_group_state(chat_id)
        ctx = bot_persistence.get_or_create_group_context(chat_id, state.title)
        ctx.automation_active = state.is_active
        ctx.conversational_ai_active = state.conversational_ai_active
        ctx.speed = state.speed
        ctx.delete_delay = state.delete_delay
        ctx.voice_replies_enabled = state.voice_replies_enabled
        ctx.csv_index = state.csv_index
        ctx.active_day_name = state.active_day_name or get_ist_day_name()
        ctx.title = state.title
        ctx.conversation_history = list(state.conversation_history)
        bot_persistence.save_local_state()

        if "acc1" in clients and clients["acc1"]["client"].is_connected():
            await bot_persistence.sync_group_to_telegram_cloud(clients["acc1"]["client"], chat_id)
    except Exception as e:
        logging.warning(f"Failed to save state for group {chat_id}: {e}")

async def load_state_from_telegram():
    await load_all_states_from_telegram()
    return 0

async def save_state_to_telegram(csv_idx=None):
    pass

def format_seconds_to_readable(seconds):
    if seconds <= 0:
        return "Disabled (0s)"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if days > 0: parts.append(f"{days}d")
    if hours > 0: parts.append(f"{hours}h")
    if minutes > 0: parts.append(f"{minutes}m")
    if secs > 0 or not parts: parts.append(f"{secs}s")
    return " ".join(parts)

def parse_time_to_seconds(time_str):
    if not time_str: return None
    time_str = time_str.lower().strip().replace(" ", "")
    if time_str in ("0", "off", "disable", "none", "stop"):
        return 0
    try:
        m = re.match(r'^(\d+(?:\.\d+)?)(w|week|weeks|d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs|second|seconds)?$', time_str)
        if not m:
            return None
        val = float(m.group(1))
        unit = m.group(2) or "s"
        if unit.startswith("w"):
            return int(val * 604800)
        elif unit.startswith("d"):
            return int(val * 86400)
        elif unit.startswith("h"):
            return int(val * 3600)
        elif unit.startswith("m"):
            return int(val * 60)
        elif unit.startswith("s"):
            return int(val)
        return int(val)
    except:
        return None

async def delete_message_later(client, chat_id, message_id, delay):
    if delay <= 0: return
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, [message_id])
    except:
        pass

async def delete_other_message(message, delay):
    if delay <= 0: return
    # Protect images and videos from being auto-deleted
    if message.photo or message.video:
        return
        
    await asyncio.sleep(delay)
    try:
        await message.delete()
        logging.info(f"Deleted a group member's message after {delay} seconds.")
    except Exception as e:
        pass


async def history_sweeper(client, chat_entity, delay_seconds):
    try:
        logging.info(f"Starting background history sweeper for all messages older than {delay_seconds}s...")
        cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=delay_seconds)
        
        messages_to_delete = []
        async for msg in client.iter_messages(chat_entity, offset_date=cutoff_date):
            # Protect images and videos from being swept
            if msg.photo or msg.video:
                continue
                
            messages_to_delete.append(msg.id)
                
            if len(messages_to_delete) >= 100:
                await client.delete_messages(chat_entity, messages_to_delete)
                logging.info("Sweeper deleted 100 historical messages...")
                messages_to_delete.clear()
                await asyncio.sleep(2.0)
                
        if messages_to_delete:
            await client.delete_messages(chat_entity, messages_to_delete)
            logging.info(f"Sweeper deleted final {len(messages_to_delete)} historical messages.")
            
        logging.info("History sweeper finished successfully.")
    except Exception as e:
        logging.error(f"Error in history sweeper: {e}")

async def periodic_history_sweeper():
    while True:
        await asyncio.sleep(900)  # Run sweep every 15 minutes
        try:
            if "acc1" in clients and delete_delay > 0:
                acc1_client = clients["acc1"]["client"]
                target = TARGET_CHAT_ID or TARGET_CHAT
                if isinstance(target, str) and (target.startswith("-100") or target.lstrip('-').isdigit()):
                    target = int(target)
                entity = await acc1_client.get_entity(target)
                await history_sweeper(acc1_client, entity, delete_delay)
        except Exception as e:
            logging.error(f"Periodic sweeper error: {e}")

async def simulate_typing(client, entity, text, group_speed=15.0):
    if group_speed <= 1.0:
        return
    if group_speed <= 5.0:
        max_type = min(max(group_speed * 0.15, 0.3), 0.8)
        typing_time = min(max(len(text) * 0.015, 0.25), max_type)
    else:
        max_type = min(max(group_speed * 0.25, 0.5), 2.5)
        typing_time = min(max(len(text) * 0.025, 0.4), max_type)
    try:
        async with client.action(entity, 'typing'):
            await asyncio.sleep(typing_time)
    except:
        await asyncio.sleep(typing_time)

async def send_dynamic_reply(client, entity, target_msg, text):
    global total_messages_sent
    await simulate_typing(client, entity, text)
    try:
        sent_msg = await client.send_message(entity, text, reply_to=target_msg)
        total_messages_sent += 1
        if delete_delay > 0:
            asyncio.create_task(delete_message_later(client, entity, sent_msg.id, delete_delay))
        logging.info(f"Sent dynamic reply: {text}")
    except Exception as e:
        logging.error(f"Failed to send dynamic reply: {e}")

# ==========================================
# ARISE AUTO-CATCHER MODULE (AI VISION)
# ==========================================

async def handle_spawn_message(event):
    """Processes gate spawn messages and catches the character using Account 1 (with Acc 2/3 fallback)."""
    global account_rate_limited_until, processed_spawn_ids, SPAWN_CHAT_ID, SPAWN_CHAT_TITLE
    if not arise_autocatch_active:
        return
        
    # STRICT FILTER: ONLY collect in the target group (Prisoner world)
    chat_title = ""
    try:
        chat = await event.get_chat()
        chat_title = (getattr(chat, 'title', '') or '').strip()
    except Exception:
        pass

    # If this message is from Prisoner world, ALWAYS ACCEPT and lock onto it!
    if "prisoner" in chat_title.lower():
        SPAWN_CHAT_ID = event.chat_id
        SPAWN_CHAT_TITLE = chat_title or "Prisoner world"
    elif SPAWN_CHAT_ID and event.chat_id == SPAWN_CHAT_ID:
        pass
    elif TARGET_CHAT_ID and event.chat_id == TARGET_CHAT_ID:
        pass
    else:
        # Ignore main group and any unrelated group!
        return

    if event.id in processed_spawn_ids:
        return
    processed_spawn_ids.add(event.id)
    if len(processed_spawn_ids) > 500:
        processed_spawn_ids.pop()
        
    text = (event.raw_text or "").upper()
    is_spawn = (
        ("THE GATE WAS SPAWNED" in text) or
        ("ADD THIS CHARACTER TO YOUR ARMY" in text) or
        ("/ARISE" in text and "ARMY" in text) or
        ("GATE" in text and "SPAWN" in text)
    )
    if not is_spawn:
        return
        
    logging.info(f"⚡ [Auto-Catcher] Gate spawn keyword detected in '{SPAWN_CHAT_TITLE}' ({event.chat_id})! Checking media...")
    if not event.media:
        logging.warning("[Auto-Catcher] Gate spawn message has no media attached. Skipping.")
        return
        
    logging.info(f"[Auto-Catcher] Gate spawn with media detected in '{SPAWN_CHAT_TITLE}' ({event.chat_id})! Downloading image in-memory...")
    
    photo_bytes = io.BytesIO()
    try:
        await event.message.download_media(file=photo_bytes)
        photo_bytes.seek(0)
        if photo_bytes.getbuffer().nbytes == 0:
            raw = await event.message.download_media(file=bytes)
            if raw:
                photo_bytes = io.BytesIO(raw)
    except Exception as e:
        logging.error(f"[Auto-Catcher] Failed to read spawn photo: {e}")
        return
        
    char_name = None
    if HAS_GENAI and gemini_client:
        try:
            photo_bytes.seek(0)
            img = Image.open(photo_bytes)
            prompt = (
                "Identify this anime or video game character shown in the image. "
                "Respond ONLY with the character's exact canonical English name (for example 'Lain Iwakura', 'Toph Beifong', 'Ruan Mei', 'Naruto Uzumaki', 'Lumine'). "
                "Do NOT include anime title, commentary, markdown, or punctuation. ONLY the character name."
            )
            for m_vision in AI_VISION_MODELS:
                try:
                    res = await gemini_client.aio.models.generate_content(
                        model=m_vision,
                        contents=[img, prompt]
                    )
                    if res and res.text:
                        break
                except Exception:
                    try:
                        res = gemini_client.models.generate_content(
                            model=m_vision,
                            contents=[img, prompt]
                        )
                        if res and res.text:
                            break
                    except Exception:
                        continue
            if res and res.text:
                char_name = res.text.strip().replace('\n', '').strip('".*')
                logging.info(f"🎯 [Auto-Catcher] GEMINI VISION IDENTIFIED: '{char_name}'")
        except Exception as ge:
            logging.error(f"[Auto-Catcher] Gemini Vision identification failed: {ge}")
            
    if not char_name:
        logging.warning("[Auto-Catcher] Could not identify character name via Gemini Vision. Skipping.")
        return
        
    logging.info(f"🏆 [Auto-Catcher] Target Locked: '{char_name}'. Preparing to catch in {SPAWN_CHAT_TITLE}...")
    
    # Fast natural reaction delay (0.15s to 0.35s) so Account 1 catches BEFORE anyone else in group
    await asyncio.sleep(random.uniform(0.15, 0.35))
    
    order = ["acc1", "acc2", "acc3"]
    current_time = time.time()
    
    for acc_key in order:
        if acc_key not in clients:
            continue
            
        if account_rate_limited_until.get(acc_key, 0) > current_time:
            cooldown_left = int(account_rate_limited_until[acc_key] - current_time)
            logging.info(f"[Auto-Catcher] {clients[acc_key]['name']} is on cooldown ({cooldown_left}s remaining). Trying next account...")
            continue
            
        catcher_client = clients[acc_key]["client"]
        catcher_name = clients[acc_key]["name"]
        
        try:
            catch_cmd = f"/arise {char_name}"
            # Ensure entity is resolved for this client
            try:
                target_entity = await catcher_client.get_input_entity(event.chat_id)
            except Exception:
                target_entity = event.chat_id
                
            try:
                await catcher_client.send_message(target_entity, catch_cmd, reply_to=event.message.id)
            except Exception as reply_err:
                logging.warning(f"[Auto-Catcher] Reply-to failed ({reply_err}), sending without reply...")
                await catcher_client.send_message(target_entity, catch_cmd)
                
            logging.info(f"🏆 [Auto-Catcher] {catcher_name} SENT: '{catch_cmd}' in {SPAWN_CHAT_TITLE} ({event.chat_id})")
            return
        except FloodWaitError as fe:
            logging.warning(f"[Auto-Catcher] {catcher_name} got rate-limited for {fe.seconds}s! Failing over to next account...")
            account_rate_limited_until[acc_key] = current_time + fe.seconds
            continue
        except Exception as e:
            logging.error(f"[Auto-Catcher] {catcher_name} error sending catch command: {e}")
            continue
            
    logging.error("[Auto-Catcher] All accounts were unable to catch the character!")

def setup_commands(bot_client):
    is_acc4 = (bot_client == clients.get("acc4", {}).get("client"))

    def should_skip_cmd(event):
        if not is_acc4 and event.is_private:
            return True
        msg_id = getattr(event.message, 'id', None)
        if not msg_id:
            return False
        if msg_id in processed_cmd_msg_ids:
            return True
        processed_cmd_msg_ids.add(msg_id)
        if len(processed_cmd_msg_ids) > 1000:
            processed_cmd_msg_ids.clear()
            processed_cmd_msg_ids.add(msg_id)
        return False

    async def send_bot_reply(event, text, file=None):
        acc4_client = clients.get("acc4", {}).get("client")
        # Try sending through acc4 (the Bot)
        if acc4_client and acc4_client.is_connected():
            try:
                # If bot has the entity or can send directly
                target = getattr(event, 'input_chat', None) or event.chat_id
                if file:
                    return await acc4_client.send_message(target, text, file=file, reply_to=event.message.id)
                else:
                    return await acc4_client.send_message(target, text, reply_to=event.message.id)
            except Exception as e:
                logging.debug(f"acc4 direct send failed ({e}), falling back to event reply")
        # Reliable fallback: event.reply always succeeds
        try:
            if file:
                return await event.reply(text, file=file)
            else:
                return await event.reply(text)
        except Exception as e2:
            logging.error(f"send_bot_reply all fallbacks failed: {e2}")

    def get_sender_id(event):
        s_id = getattr(event, 'sender_id', None)
        if not s_id:
            s = getattr(event, 'message', None)
            s_id = getattr(getattr(s, 'from_id', None), 'user_id', None)
        return s_id

    async def get_sender_identity(event):
        s_id = get_sender_id(event)
        sender_obj = None
        try:
            sender_obj = await event.get_sender()
        except:
            pass
        username = (getattr(sender_obj, 'username', '') or '').lower().lstrip('@')
        return s_id, username

    async def are_primary_accounts_in_group(client, chat_id: int) -> bool:
        try:
            state = get_group_state(chat_id)
            has_owner = (5429173364 in state.known_user_ids) or any(u in state.known_usernames for u in ("merlin_hermis", "errormonocle"))
            has_greatlotm = (8877720410 in state.known_user_ids) or any(u in state.known_usernames for u in ("greatlotm", "great_lotm"))
            if has_owner and has_greatlotm:
                return True

            participants = await client.get_participants(chat_id, limit=300)
            p_ids = set()
            p_users = set()
            for p in participants:
                if getattr(p, 'id', None):
                    p_ids.add(p.id)
                    state.known_user_ids.add(p.id)
                u = (getattr(p, 'username', '') or '').lower().lstrip('@')
                if u:
                    p_users.add(u)
                    state.known_usernames.add(u)

            has_owner = (5429173364 in p_ids) or any(u in p_users for u in ("merlin_hermis", "errormonocle"))
            has_greatlotm = (8877720410 in p_ids) or any(u in p_users for u in ("greatlotm", "great_lotm"))
            return (has_owner and has_greatlotm)
        except Exception as e:
            logging.debug(f"Could not check participants for {chat_id}: {e}")
            state = get_group_state(chat_id)
            return (("merlin_hermis" in state.known_usernames or "errormonocle" in state.known_usernames or 5429173364 in state.known_user_ids) and 
                    ("greatlotm" in state.known_usernames or "great_lotm" in state.known_usernames or 8877720410 in state.known_user_ids))

    async def check_command_auth(event, cmd_name: str) -> tuple[bool, str]:
        s_id, username = await get_sender_identity(event)

        is_owner = (s_id in SUPER_ADMIN_IDS) or (username in ("merlin_hermis", "errormonocle"))
        is_greatlotm = (s_id == 8877720410) or (username in ("greatlotm", "great_lotm"))
        is_operator = (s_id in OPERATOR_USER_IDS)

        # If not authorized at all, ignore
        if not (is_owner or is_greatlotm or is_operator):
            return False, "Unauthorized account."

        if event.is_private:
            if is_owner or is_greatlotm:
                return True, ""
            if is_operator:
                if cmd_name in ["lockon", "lockoff"]:
                    return True, ""
                return False, "Operator role is restricted strictly to lockon and lockoff only."
            return False, "Unauthorized."

        chat_id = event.chat_id
        probe_client = clients.get("acc1", {}).get("client") or event.client
        primaries_present = await are_primary_accounts_in_group(probe_client, chat_id)

        if is_owner or is_greatlotm:
            return True, ""

        if is_operator:
            if cmd_name in ["lockon", "lockoff"]:
                return True, ""
            return False, "The fourth account is restricted to lockon and lockoff only."

        return False, "Unauthorized."

        chat_id = event.chat_id
        probe_client = clients.get("acc1", {}).get("client") or event.client
        primaries_present = await are_primary_accounts_in_group(probe_client, chat_id)
        
        if is_owner or is_greatlotm:
            return True, ""
            
        if is_operator:
            if cmd_name in ["lockon", "lockoff"]:
                return True, ""
            return False, "The fourth account is restricted to lockon and lockoff only."
            
        return False, "Unauthorized."

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?stats(?:@genzetabot)?$'))
    async def stats_handler(event):
        if should_skip_cmd(event): return
        try:
            allowed, _ = await check_command_auth(event, "stats")
            if not allowed: return
            chat_id = event.chat_id
            state = get_group_state(chat_id)
            status = "🟢 ONLINE" if state.is_active else "🔴 OFFLINE"
            del_str = format_seconds_to_readable(state.delete_delay)
            catch_target = f"{SPAWN_CHAT_TITLE} (`{SPAWN_CHAT_ID}`)" if SPAWN_CHAT_ID else (SPAWN_CHAT_TITLE or "Not Set")
            catch_status = f"🟢 ONLINE (Chat: {catch_target})" if arise_autocatch_active else "🔴 OFFLINE"
            day_cap = (state.active_day_name or active_day_name).capitalize()
            worker_names = [clients[w]["name"] for w in state.active_workers if w in clients]
            workers_str = ", ".join(worker_names) if worker_names else "Detecting..."
            
            await send_bot_reply(event, 
                f"📊 **GunYamazaki Stats — {state.title}**\n\n"
                f"• Group Status: {status}\n"
                f"• Group Speed: **{state.speed}s** (Isolated to this group)\n"
                f"• Active Workers: {workers_str}\n"
                f"• Auto-Delete: {del_str}\n"
                f"• Auto-Catch: {catch_status}\n"
                f"• Active Day: 📅 **{day_cap}** (`{CSV_FILE}`)\n"
                f"• CSV Progress: {state.csv_index}/{len(conversation_data)} msgs\n"
                f"• Adult Boy Voice Notes: 🎙 ONLINE (3 Distinct Voices)\n"
                f"• Live Web Intel: 🟢 ONLINE (Anime, Gaming & Sports RSS)\n"
                f"• Meme Engine: 🟢 ONLINE (12+ Custom Meme Cards)\n"
                f"• Total Active Groups: {len([s for s in group_states.values() if s.is_active])}"
            )
        except Exception as e:
            logging.error(f"Error in stats_handler: {e}")

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?(?:day|dayinfo)(?:@genzetabot)?$'))
    async def day_handler(event):
        if should_skip_cmd(event): return
        try:
            allowed, _ = await check_command_auth(event, "day")
            if not allowed: return
            state = get_group_state(event.chat_id)
            day_cap = (state.active_day_name or active_day_name).capitalize()
            total_msgs = len(conversation_data)
            await send_bot_reply(event, 
                f"📅 **Active Daily Dataset Info — {state.title}**\n\n"
                f"• **Current Day:** {day_cap}\n"
                f"• **Active CSV:** `{CSV_FILE}`\n"
                f"• **Loaded Messages:** {total_msgs:,} Hinglish messages\n"
                f"• **Current Index:** {state.csv_index} / {total_msgs}\n"
                f"• **Auto-Midnight Rollover:** 🟢 ACTIVE (00:00:00 IST)\n\n"
                f"💡 *To switch day manually, send:* `setday monday`, `setday friday`, etc."
            )
        except: pass

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?setday(?:@genzetabot)?(?:\s+(.+))?$'))
    async def setday_handler(event):
        if should_skip_cmd(event): return
        try:
            allowed, reason = await check_command_auth(event, "setday")
            if not allowed:
                if reason: await send_bot_reply(event, f"❌ {reason}")
                return
            state = get_group_state(event.chat_id)
            arg = event.pattern_match.group(1)
            valid_days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            if not arg or arg.strip().lower() not in valid_days:
                days_list = ", ".join(f"`{d}`" for d in valid_days)
                await send_bot_reply(event, f"❌ Please specify a valid day!\nAvailable days: {days_list}\nExample: `setday friday`")
                return
            target_day = arg.strip().lower()
            state.active_day_name = target_day
            state.csv_index = 0
            load_csv(target_day)
            await save_group_state_to_telegram(event.chat_id)
            await send_bot_reply(event, 
                f"✅ **Active Day Switched for {state.title}!**\n\n"
                f"• **New Day:** {target_day.capitalize()}\n"
                f"• **Loaded CSV:** `{CSV_FILE}`\n"
                f"• **Conversation Index:** Reset to 0"
            )
            logging.info(f"Day switched to {target_day.capitalize()} for group {event.chat_id}")
        except Exception as e:
            logging.error(f"Error in setday_handler: {e}")

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?ariseon(?:@genzetabot)?$'))
    async def ariseon_handler(event):
        if should_skip_cmd(event): return
        global arise_autocatch_active
        try:
            allowed, _ = await check_command_auth(event, "ariseon")
            if not allowed: return
            arise_autocatch_active = True
            await send_bot_reply(event, f"✅ Arise Auto-Catcher is now **ONLINE**!\nLocked strictly to: **{SPAWN_CHAT_TITLE}** (`{SPAWN_CHAT_ID}`)")
        except: pass

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?ariseoff(?:@genzetabot)?$'))
    async def ariseoff_handler(event):
        if should_skip_cmd(event): return
        global arise_autocatch_active
        try:
            allowed, _ = await check_command_auth(event, "ariseoff")
            if not allowed: return
            arise_autocatch_active = False
            await send_bot_reply(event, "🛑 Arise Auto-Catcher is now **OFFLINE**.")
        except: pass

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?(?:arisehere|lockarise)(?:@genzetabot)?$'))
    async def arisehere_handler(event):
        if should_skip_cmd(event): return
        global SPAWN_CHAT_ID, SPAWN_CHAT_TITLE, arise_autocatch_active
        try:
            allowed, _ = await check_command_auth(event, "arisehere")
            if not allowed: return
            SPAWN_CHAT_ID = event.chat_id
            arise_autocatch_active = True
            try:
                chat = await event.get_chat()
                SPAWN_CHAT_TITLE = getattr(chat, 'title', 'Current Group')
            except: pass
            await send_bot_reply(event, 
                f"🎯 **Arise Auto-Catcher LOCKED!**\n\n"
                f"Group: **{SPAWN_CHAT_TITLE}** (`{SPAWN_CHAT_ID}`)\n"
                f"Status: 🟢 **ONLINE**\n\n"
                f"The bot will **ONLY** catch character gates inside this group!"
            )
            logging.info(f"Arise Auto-Catcher strictly locked to chat {SPAWN_CHAT_ID} ('{SPAWN_CHAT_TITLE}')")
        except: pass

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?lockon(?:@genzetabot)?$'))
    async def lockon_handler(event):
        if should_skip_cmd(event): return
        try:
            allowed, _ = await check_command_auth(event, "lockon")
            if not allowed: return
            chat_id = event.chat_id
            state = get_group_state(chat_id)
            try:
                chat = await event.get_chat()
                state.title = getattr(chat, 'title', state.title or f"Chat {chat_id}")
            except: pass

            workers = await register_and_warmup_group(chat_id, event)
            state.is_active = True
            state.automation_active = True
            asyncio.create_task(run_group_chat_loop(chat_id))
            await save_group_state_to_telegram(chat_id)

            worker_names = [clients[w]["name"] for w in workers if w in clients]
            workers_str = ", ".join(worker_names) if worker_names else "Account 1, Bot"
            await send_bot_reply(event, 
                f"🚀 **Automation Locked On to {state.title}!**\n\n"
                f"  **Group Automated Interval:** {state.speed}s (Default: 40–60s)\n"
                f"  **Active Workers in Group:** {workers_str}\n"
                f"  **Conversational AI (Jarvis):** 🟢 ONLINE (Text & Voice Q&A)\n"
                f"  **Auto-Delete:** {format_seconds_to_readable(state.delete_delay)}\n\n"
                f"💡 *This group runs completely independently. Other groups are unaffected.*"
            )
            logging.info(f"System LOCKED ON to {chat_id} ('{state.title}') with workers: {workers}")
        except Exception as e:
            logging.error(f"Error in lockon_handler: {e}")

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?lockoff(?:@genzetabot)?$'))
    async def lockoff_handler(event):
        if should_skip_cmd(event): return
        try:
            allowed, _ = await check_command_auth(event, "lockoff")
            if not allowed: return
            chat_id = event.chat_id
            state = get_group_state(chat_id)
            state.is_active = False
            state.automation_active = False
            await save_group_state_to_telegram(chat_id)
            await send_bot_reply(event, 
                f"🛑 **Automation Locked Off.**\n"
                f"Automated background messaging is now paused in `{state.title}`.\n"
                f"🤖 **GenzetaBot Conversational AI (Jarvis):** 🟢 ONLINE — Ready to chat and answer text & voice questions anytime!"
            )
            logging.info(f"System LOCKED OFF in {chat_id} ('{state.title}')")
        except Exception as e:
            logging.error(f"Error in lockoff_handler: {e}")

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?resetgroup(?:@genzetabot)?$'))
    async def resetgroup_handler(event):
        if should_skip_cmd(event): return
        try:
            allowed, _ = await check_command_auth(event, "resetgroup")
            if not allowed: return
            s_id, username = await get_sender_identity(event)
            is_owner = (s_id in SUPER_ADMIN_IDS) or (username in ("merlin_hermis", "errormonocle"))
            if not is_owner:
                await send_bot_reply(event, "⚠️ Only the primary owner can perform a full group configuration reset.")
                return
            chat_id = event.chat_id
            bot_persistence.reset_group_state(chat_id)
            st = get_group_state(chat_id)
            st.is_active = False
            st.automation_active = False
            st.speed = 45.0
            st.conversational_ai_active = True
            await send_bot_reply(event, f"🔄 **Group Configuration Reset.**\n`{st.title}` has been restored to default settings:\n- Automation: PAUSED\n- Conversational AI: ONLINE\n- Interval: 45s\n- Memory: Cleared")
        except Exception as e:
            logging.error(f"Error in resetgroup_handler: {e}")

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?(?:setspeed|speed)(?:@genzetabot)?(?:\s+(.+))?$'))
    async def setspeed_handler(event):
        if should_skip_cmd(event): return
        try:
            allowed, _ = await check_command_auth(event, "setspeed")
            if not allowed: return
            chat_id = event.chat_id
            state = get_group_state(chat_id)
            arg = (event.pattern_match.group(1) or "").strip()
            if not arg:
                await send_bot_reply(event, f"⏱ **Group Automated Speed:** {state.speed}s\nDefault interval is 45s (40–60s range). Use `setspeed 50` to change.")
                return
            new_speed = float(arg)
            if new_speed < 1.0 or new_speed > 300.0:
                await send_bot_reply(event, "⚠️ Speed must be between 1 and 300 seconds.")
                return
            state.speed = new_speed
            await save_group_state_to_telegram(chat_id)
            await send_bot_reply(event, f"⚡ **Group Speed Updated!**\n`{state.title}` is now set to **{new_speed}s** interval.\nOther groups remain unaffected.")
        except Exception as e:
            logging.error(f"Error in setspeed_handler: {e}")

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?(?:setdelete|autodelete|setdel|delete)(?:@genzetabot)?(?:\s+(.+))?$'))
    async def setdelete_handler(event):
        if should_skip_cmd(event): return
        try:
            allowed, reason = await check_command_auth(event, "setdelete")
            if not allowed:
                if reason: await send_bot_reply(event, f"❌ {reason}")
                return
            chat_id = event.chat_id
            state = get_group_state(chat_id)
            arg = event.pattern_match.group(1)
            if not arg or not arg.strip():
                readable = format_seconds_to_readable(state.delete_delay)
                await send_bot_reply(event, 
                    f"🗑 **Current Auto-Delete for {state.title}:** **{readable}** ({state.delete_delay}s)\n\n"
                    f"Examples: `setdelete 15m`, `setdelete 1h`, `setdelete 1d`, `setdelete 0`"
                )
                return
            del_val = parse_time_to_seconds(arg.strip())
            if del_val is not None:
                state.delete_delay = del_val
                readable = format_seconds_to_readable(state.delete_delay)
                await save_group_state_to_telegram(chat_id)
                await send_bot_reply(event, f"🗑 Auto-delete set to **{readable}** ({state.delete_delay}s) for **{state.title}** only!")
                try:
                    sweep_client = bot_client if bot_client.is_connected() else clients.get("acc1", {}).get("client")
                    entity = state.cached_entities.get("acc4") or await sweep_client.get_entity(chat_id)
                    asyncio.create_task(history_sweeper(sweep_client, entity, state.delete_delay))
                except: pass
            else:
                await send_bot_reply(event, "❌ Invalid time format! Example: `setdelete 15m`, `setdelete 1h`, or `setdelete 0`.")
        except Exception as e:
            logging.error(f"Error in setdelete_handler: {e}")

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?(?:meme|memes)(?:@genzetabot)?(?:\s+(.+))?$'))
    async def meme_cmd_handler(event):
        if should_skip_cmd(event): return
        try:
            fpath, meme_info = meme_engine.get_random_meme()
            meme_title = meme_info.get("title", "Meme")
            punchline = meme_info.get("punchline", "")
            
            prompt_caption = (
                f"You are Gun Yamazaki (@genzetabot). A friend asked for a meme in Telegram. "
                f"Meme title: '{meme_title}'. Punchline context: '{punchline}'. "
                f"Write 1 short, hilarious, natural Hinglish caption or roast for this meme (e.g. 'ye lo bhai ek fresh meme 😂', 'literally us in every match 💀'). "
                f"1 short line. No hashtags."
            )
            caption = await generate_gemini_text(prompt_caption, recent_replies=recent_ai_replies)
            if not caption:
                caption = f"⚡ {meme_title} ⚡\n{punchline}"
                
            sent_msg = await send_bot_reply(event, caption, file=fpath)
            state = get_group_state(event.chat_id)
            if state.delete_delay > 0 and not event.is_private:
                target_del_client = clients.get("acc4", {}).get("client") or bot_client
                asyncio.create_task(delete_message_later(target_del_client, event.chat_id, sent_msg.id, state.delete_delay))
        except Exception as e:
            logging.error(f"Error in meme_cmd_handler: {e}")

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/?(?:news|intel|breaking)(?:@genzetabot)?$'))
    async def news_cmd_handler(event):
        if should_skip_cmd(event): return
        try:
            intel = await fetch_live_web_intel()
            headline = intel.get("title", "")
            cat = intel.get("category", "general")
            
            prompt_news = (
                f"You are Gun Yamazaki (@genzetabot). A friend asked for live breaking news. "
                f"Latest real-time headline: '{headline}' (Category: {cat}). "
                f"Give a casual, witty, spicy 1-2 sentence Hinglish breakdown of this news to the group. "
                f"Keep it authentic and natural. No hashtags."
            )
            response = await generate_gemini_text(prompt_news, recent_replies=recent_ai_replies)
            if not response:
                response = f"🌐 **Live {cat.capitalize()} News:**\n{headline}"
                
            sent_msg = await send_bot_reply(event, response)
            state = get_group_state(event.chat_id)
            if state.delete_delay > 0 and not event.is_private:
                target_del_client = clients.get("acc4", {}).get("client") or bot_client
                asyncio.create_task(delete_message_later(target_del_client, event.chat_id, sent_msg.id, state.delete_delay))
        except Exception as e:
            logging.error(f"Error in news_cmd_handler: {e}")

    @bot_client.on(events.NewMessage())
    async def auto_delete_handler(event):
        global BOT_ENTITY
        
            # Skip outgoing messages from this bot
        if getattr(event, 'out', False):
            return

        # Skip admin commands so they are processed exclusively by their dedicated command handlers
        if event.raw_text and event.raw_text.strip().lower().startswith((
            "/lockon", "lockon", "/lockoff", "lockoff",
            "/setdelete", "setdelete", "/autodelete", "autodelete", "/setdel", "setdel", "/delete", "delete",
            "/setspeed", "setspeed", "/speed", "speed",
            "/stats", "stats", "/arise", "arise", "/day", "day", "/setday", "setday",
            "/ariseon", "ariseon", "/ariseoff", "ariseoff", "/arisehere", "arisehere", "/lockarise", "lockarise",
            "/meme", "meme", "/news", "news", "/intel", "intel"
        )):
            return

        is_group_msg = (event.is_group or event.is_channel)
        is_private_msg = event.is_private

        # CRITICAL: User accounts (acc1, acc2, acc3) must NEVER touch or auto-reply to private DMs!
        # Private DMs must be handled strictly and exclusively by acc4 (the official Bot).
        if not is_acc4 and is_private_msg:
            return

        if not is_group_msg and not is_private_msg:
            return

        if is_group_msg:
            state = get_group_state(event.chat_id)
            s_id = event.sender_id
            if s_id:
                state.known_user_ids.add(s_id)
            try:
                s_ent = await event.get_sender()
                u_str = (getattr(s_ent, 'username', '') or '').lower().lstrip('@')
                if u_str:
                    state.known_usernames.add(u_str)
            except: pass
            
            # If this group is locked off, do not participate in human chat
            if not state.is_active:
                return
            BOT_ENTITY = event.input_chat
            
        try:
            sender_id = event.sender_id
            if not sender_id:
                s = getattr(event, 'message', None)
                sender_id = getattr(getattr(s, 'from_id', None), 'user_id', None)
            if not sender_id:
                return

            raw_text = (event.raw_text or "").strip()
            msg_text = raw_text.lower()
            if not raw_text:
                return

            # -----------------------------------------------------------------
            # 1. IF ONE OF OUR AUTOMATED BOTS SPEAKS IN GROUP (Dataset Loop)
            # -----------------------------------------------------------------
            if sender_id in OUR_USER_IDS:
                recent_chat_history.append(f"Friend: {raw_text}")
                if random.random() < 0.15:
                    try:
                        emoji = random.choice(["👍", "😂", "❤️", "🔥", "🤔", "👀", "👌", "✨"])
                        reactors = [c for k, c in clients.items() if k != "acc4" and c.get("user_id") != sender_id]
                        if reactors:
                            reactor_acc = random.choice(reactors)
                            await reactor_acc["client"](SendReactionRequest(
                                peer=event.input_chat,
                                msg_id=event.message.id,
                                reaction=[ReactionEmoji(emoticon=emoji)]
                            ))
                    except: pass
                return

            # -----------------------------------------------------------------
            # 2. REAL HUMAN GROUP MEMBER (OR PRIVATE DM)
            # -----------------------------------------------------------------
            # Message deduplication across clients
            msg_id = getattr(event.message, 'id', None)
            if not msg_id or msg_id in processed_human_msg_ids:
                return
            processed_human_msg_ids.add(msg_id)
            if len(processed_human_msg_ids) > 2000:
                processed_human_msg_ids.clear()
                processed_human_msg_ids.add(msg_id)

            # Auto-delete human message if timer active (and user is not an admin)
            if delete_delay > 0 and sender_id not in ADMIN_USER_IDS:
                asyncio.create_task(delete_other_message(event.message, delete_delay))

            # Fetch sender name for natural conversational addressing
            sender_name = "User"
            try:
                sender_ent = await event.get_sender()
                sender_name = getattr(sender_ent, 'first_name', '') or getattr(sender_ent, 'username', '') or "User"
            except:
                pass

            recent_chat_history.append(f"{sender_name}: {raw_text}")

            # CRITICAL: User accounts (acc1, acc2, acc3) must NEVER generate or send AI replies to humans!
            # All replies to real humans in groups and DMs MUST come strictly and exclusively through acc4 (the Bot)!
            if not is_acc4:
                return

            # Check if this message is addressing a specific account or gun
            is_reply_to_our_bot = False
            replied_acc_key = None
            if event.message.is_reply:
                try:
                    reply_msg = await event.message.get_reply_message()
                    if reply_msg:
                        for acc_k, acc_v in clients.items():
                            if reply_msg.sender_id == acc_v.get("user_id"):
                                is_reply_to_our_bot = True
                                replied_acc_key = acc_k
                                break
                        if not is_reply_to_our_bot and (reply_msg.sender_id in OUR_USER_IDS or reply_msg.sender_id == getattr(bot_client, '_self_id', None)):
                            is_reply_to_our_bot = True
                except:
                    pass

            is_gun_mention = bool(re.search(r'(?i)(@genzetabot|\bgun\b|\byamazaki\b|gunyamazaki)', msg_text))

            # Pause scripted dataset playback for 20s so real conversation can flow naturally
            globals()['csv_paused_until'] = time.time() + 20.0

            # Debounce quick consecutive messages from same human
            now = time.time()
            if not is_private_msg and (now - last_human_reply_time) < 1.5:
                return
            globals()['last_human_reply_time'] = now

            # All dynamic AI replies to humans MUST come exclusively through acc4 (Gun Yamazaki Bot)
            acc4_cfg = clients.get("acc4")
            if not acc4_cfg or not acc4_cfg["client"].is_connected():
                return
            chosen_client_cfg = acc4_cfg
            speaker_client = acc4_cfg["client"]
            speaker_name = acc4_cfg["name"]

            # Detect language mode
            lang_mode = detect_language_mode([raw_text] + list(recent_chat_history))
            lang_instruction = (
                "in natural, witty, chill Hinglish (Roman Hindi + casual English texting slang, e.g. 'arre bhai', 'sahi bol raha h tu', 'mast h', 'kya scene h'). Do NOT use formal bookish Hindi."
                if lang_mode in ('hinglish', 'hindi_roman')
                else "in natural, casual, chill conversational English"
            )

            context_lines = list(recent_chat_history)[-6:]
            context_str = "\n".join(context_lines) if context_lines else "(No previous context)"

            prompt = (
                f"You are {speaker_name}, a real friend hanging out in an active Telegram group chat.\n"
                f"Recent conversation in the group:\n{context_str}\n\n"
                f"A real group member ({sender_name}) just said: '{raw_text}'\n\n"
                f"TASK: Reply directly to {sender_name} {lang_instruction}.\n"
                f"STRICT RULES:\n"
                f"1. 1 or 2 short sentences maximum. Text casually like someone texting on their phone.\n"
                f"2. If they asked a question (anime recommendation, who is stronger, gaming, what's up), give a genuine, fun answer!\n"
                f"3. If they ask 'are you a bot?' or 'bot ho kya?': Laugh it off like a real human ('abe bot kyu bol raha h bhai lol, zinda insaan hu').\n"
                f"4. Never say 'As an AI...', 'How can I assist you?', or sound like an assistant. Be a real bro.\n"
                f"5. No hashtags, no quotes around your response, no markdown bold headings.\n"
                f"Your reply:"
            )

            reply_clean = await generate_gemini_text(prompt, recent_replies=recent_ai_replies)
            if not reply_clean:
                reply_clean = get_dynamic_fallback(lang_mode)

            recent_ai_replies.append(reply_clean)
            recent_chat_history.append(f"{speaker_name}: {reply_clean}")

            if is_private_msg:
                acc4_client = clients.get("acc4", {}).get("client") or bot_client
                await simulate_typing(acc4_client, event.chat_id, reply_clean)
                await acc4_client.send_message(event.chat_id, reply_clean)
            else:
                target_chat_peer = event.input_chat
                asyncio.create_task(send_dynamic_reply(speaker_client, target_chat_peer, event.message, reply_clean))

                # 15% chance to also react with an emoji
                if random.random() < 0.15:
                    try:
                        emoji = "👍"
                        if any(w in msg_text for w in ["lol", "lmao", "haha", "xd", "funny"]): emoji = "😂"
                        elif any(w in msg_text for w in ["love", "best", "great", "mast"]): emoji = "❤️"
                        elif any(w in msg_text for w in ["fire", "insane", "crazy", "lit"]): emoji = "🔥"
                        elif any(w in msg_text for w in ["sad", "cry", "rip", "dard"]): emoji = "😢"
                        reactors = [c for k, c in clients.items() if c.get("user_id") != chosen_client_cfg.get("user_id")]
                        if reactors:
                            await random.choice(reactors)["client"](SendReactionRequest(
                                peer=event.input_chat,
                                msg_id=event.message.id,
                                reaction=[ReactionEmoji(emoticon=emoji)]
                            ))
                    except:
                        pass
        except Exception as e:
            logging.error(f"Error in auto_delete_handler: {e}")

async def trigger_anime_news_event(entity):
    global total_messages_sent
    if not HAS_GENAI or "acc4" not in clients: return
    try:
        logging.info("Triggering Live Real-Time Web Intelligence Event...")
        intel = await fetch_live_web_intel()
        topic_title = intel.get("title", "")
        topic_type = intel.get("category", "anime")
        
        if not topic_title:
            topic_title, topic_type = fetch_trending_topic()

        cat_desc = "live real-time gaming news" if topic_type == "gaming" else ("live Indian sports/cricket update" if topic_type == "sports" else "breaking seasonal anime news")

        prompt_news = (
            f"You are Gun Yamazaki (@genzetabot), chilling in a Telegram group with your 3 close Indian friends. "
            f"You just saw this {cat_desc}: '{topic_title}'. "
            f"Drop this news naturally into the chat in casual, witty Hinglish (Roman Hindi + English slang, e.g. 'bhai abhi news dekhi: {topic_title}, ye kya chal raha h 😂', 'suno be: {topic_title}'). "
            f"Write 1 short sentence maximum. No hashtags, no quotes around your reply."
        )
        news_text = await generate_gemini_text(prompt_news, recent_replies=recent_ai_replies)
        if not news_text:
            news_text = f"bhai abhi news dekhi: {topic_title}... crazy scene chal raha h 😂"
            
        recent_ai_replies.append(news_text)
        recent_chat_history.append(f"Gun Yamazaki: {news_text}")

        acc4 = clients["acc4"]["client"]
        acc4_entity = entity
        await simulate_typing(acc4, acc4_entity, news_text)
        
        news_msg = await acc4.send_message(acc4_entity, news_text)
        logging.info(f"[Account 4] LIVE WEB INTEL ({topic_type.upper()}): {news_text}")
        total_messages_sent += 1
        if delete_delay > 0:
            asyncio.create_task(delete_message_later(acc4, entity, news_msg.id, delete_delay))
            
        await asyncio.sleep(random.uniform(3.0, 6.0))
        
        active_accs = [c for k, c in clients.items() if k != "acc4"]
        random.shuffle(active_accs)
        
        for acc in active_accs[:2]:
            if random.random() < 0.6:
                try:
                    emoji = random.choice(["🔥", "👀", "💯", "😂", "💀", "🤯"])
                    await acc["client"](SendReactionRequest(peer=entity, msg_id=news_msg.id, reaction=[ReactionEmoji(emoticon=emoji)]))
                except: pass
                
            prompt_reply = (
                f"You are {acc['name']}, an Indian friend replying to Gun Yamazaki who just dropped this news: '{news_text}'. "
                f"Give a short 1-sentence reply in natural casual Hinglish (e.g. 'sahi me? mai bhi dekh raha tha', 'ruk link bhej zara', 'haha ye toh hona hi tha')."
            )
            reply_text = await generate_gemini_text(prompt_reply, recent_replies=recent_ai_replies)
            if not reply_text:
                reply_text = random.choice(["sahi me? mast news h ye toh", "ruk link check karta hu", "haha ye toh expected tha"])
                
            recent_ai_replies.append(reply_text)
            recent_chat_history.append(f"{acc['name']}: {reply_text}")

            acc_entity = entity
            await simulate_typing(acc["client"], acc_entity, reply_text)
                
            reply_msg = await acc["client"].send_message(acc_entity, reply_text, reply_to=news_msg.id)
            logging.info(f"[{acc['name']}] REACTS TO NEWS: {reply_text}")
            total_messages_sent += 1
            if delete_delay > 0:
                asyncio.create_task(delete_message_later(acc["client"], entity, reply_msg.id, delete_delay))
                
            await asyncio.sleep(random.uniform(2.5, 5.0))
            
    except Exception as e:
        logging.error(f"Live Web Intel Event Failed: {e}")

async def trigger_meme_event(entity):
    global total_messages_sent
    if not clients: return
    try:
        logging.info("Triggering Autonomous Anime & Gaming Meme Event...")
        fpath, meme_info = meme_engine.get_random_meme()
        if not fpath or not os.path.exists(fpath):
            return

        sharer_key = random.choice(list(clients.keys()))
        sharer_client = clients[sharer_key]["client"]
        sharer_name = clients[sharer_key]["name"]

        meme_title = meme_info.get("title", "Meme")
        punchline = meme_info.get("punchline", "")

        prompt_caption = (
            f"You are {sharer_name}, dropping this funny anime/gaming meme in your Telegram friend group. "
            f"Meme title: '{meme_title}'. Punchline context: '{punchline}'. "
            f"Write 1 short, hilarious, natural Hinglish caption or roast (Roman Hindi + English, e.g. 'bhai ye meme dekh ke bilkul tum logo ki yaad aa gayi 💀', 'literally us in every match 😂'). "
            f"Keep it 1 short punchy line. No hashtags."
        )
        caption_text = await generate_gemini_text(prompt_caption, recent_replies=recent_ai_replies)
        if not caption_text:
            caption_text = f"bhai ye meme dekh ke hassi nhi ruk rahi meri 😂"

        recent_ai_replies.append(caption_text)
        recent_chat_history.append(f"{sharer_name}: [Shared Meme] {caption_text}")

        sharer_entity = entity
        await simulate_typing(sharer_client, sharer_entity, "photo")

        meme_msg = await sharer_client.send_message(sharer_entity, caption_text, file=fpath)
        logging.info(f"[{sharer_name}] SENT MEME: {meme_title} -> {caption_text}")
        total_messages_sent += 1

        if delete_delay > 0:
            asyncio.create_task(delete_message_later(sharer_client, entity, meme_msg.id, delete_delay))

        # Friends react with laughter emojis and follow-up roast
        await asyncio.sleep(random.uniform(2.5, 5.0))
        reactor_keys = [k for k in clients.keys() if k != sharer_key]
        random.shuffle(reactor_keys)

        for r_key in reactor_keys[:2]:
            r_client = clients[r_key]["client"]
            r_name = clients[r_key]["name"]

            if random.random() < 0.7:
                try:
                    emoji = random.choice(["😂", "💀", "🤣", "🔥"])
                    await r_client(SendReactionRequest(peer=entity, msg_id=meme_msg.id, reaction=[ReactionEmoji(emoticon=emoji)]))
                except: pass

            prompt_reaction = (
                f"You are {r_name}, replying to your friend {sharer_name} who just sent this funny meme: '{caption_text}'. "
                f"Give 1 short natural laughing comeback or roast in casual Hinglish (e.g. 'bhai sach me 💀', 'tu chup kar tera hi haal h ye 😂', 'dead fr')."
            )
            reaction_text = await generate_gemini_text(prompt_reaction, recent_replies=recent_ai_replies)
            if not reaction_text:
                reaction_text = random.choice(["bhai dead 💀😂", "sahi me yaar haha", "tera hi photo lag raha h ye 💀"])

            recent_ai_replies.append(reaction_text)
            recent_chat_history.append(f"{r_name}: {reaction_text}")

            r_entity = entity
            await simulate_typing(r_client, r_entity, reaction_text)
            r_msg = await r_client.send_message(r_entity, reaction_text, reply_to=meme_msg.id)
            total_messages_sent += 1
            if delete_delay > 0:
                asyncio.create_task(delete_message_later(r_client, entity, r_msg.id, delete_delay))
            await asyncio.sleep(random.uniform(2.0, 4.0))

    except Exception as me_err:
        logging.error(f"Error in trigger_meme_event: {me_err}")

async def trigger_poll_event(entity):
    global total_messages_sent
    if not HAS_GENAI or "acc4" not in clients: return
    try:
        logging.info("Triggering Hinglish Poll Event...")
        prompt = (
            "Create a fun, casual anime or gaming poll for an Indian group chat in Hinglish. "
            "Format exactly: Question | Option 1 | Option 2 | Option 3"
        )
        text = await generate_gemini_text(prompt)
                
        if not text or '|' not in text:
            text = "Sabse tagda animation kiska h? | Bleach TYBW | Jujutsu Kaisen | Demon Slayer"
        
        parts = [p.strip() for p in text.split('|') if p.strip()]
        if len(parts) < 3:
            parts = ["Sabse tagda animation kiska h?", "Bleach TYBW", "Jujutsu Kaisen", "Demon Slayer"]
            
        question = parts[0][:255]
        answers = [PollAnswer(text=opt[:100], option=str(i).encode('utf-8')) for i, opt in enumerate(parts[1:11])]
        
        poll_media = InputMediaPoll(
            poll=Poll(
                id=random.getrandbits(62),
                question=question,
                answers=answers
            )
        )
        
        acc4 = clients["acc4"]["client"]
        acc4_entity = entity
        await simulate_typing(acc4, acc4_entity, question)
        poll_msg = await acc4.send_message(acc4_entity, file=poll_media)
        logging.info(f"[Account 4] POLL: {question}")
        total_messages_sent += 1
        
        if delete_delay > 0:
            asyncio.create_task(delete_message_later(acc4, entity, poll_msg.id, max(delete_delay, 120)))
            
    except Exception as e:
        logging.error(f"Poll Event Failed: {e}")

async def trigger_acc4_ai_reaction(target_entity, reply_to_msg_id, thread_context, topic_name):
    global total_messages_sent
    if not HAS_GENAI or "acc4" not in clients:
        return
    try:
        lang_mode = detect_language_mode(thread_context)
        ai_prompt = get_account4_system_prompt(topic_name, thread_context, lang_mode)
        ai_text = await generate_gemini_text(ai_prompt, recent_replies=recent_ai_replies)
        if ai_text:
            recent_ai_replies.append(ai_text)
            recent_chat_history.append(f"Account 4: {ai_text}")
            acc4_client = clients["acc4"]["client"]
            acc4_entity = target_entity
            await simulate_typing(acc4_client, acc4_entity, ai_text)
            ai_sent_msg = await acc4_client.send_message(acc4_entity, ai_text, reply_to=reply_to_msg_id)
            logging.info(f"[Account 4 (Bot)] AI Joined ({lang_mode}): {ai_text}")
            total_messages_sent += 1
            thread_context.append(f"Account 4: {ai_text}")
            if delete_delay > 0:
                asyncio.create_task(delete_message_later(acc4_client, target_entity, ai_sent_msg.id, delete_delay))
    except Exception as ai_e:
        logging.warning(f"Account 4 AI participation error: {ai_e}")

async def run_group_chat_loop(chat_id: int):
    """
    Independent conversational chat loop for a single group.
    Runs concurrently with other groups at its own isolated speed.
    Includes Adult Boy Voice Note engine (3 distinct male voices, natural spacing).
    """
    state = get_group_state(chat_id)
    if state.is_loop_running:
        return
    state.is_loop_running = True
    logging.info(f"🚀 Started independent chat loop for '{state.title}' ({chat_id}) at speed {state.speed}s")
    
    if not conversation_data:
        load_csv()

    while state.is_active and state.automation_active:
        current_time = time.time()
        
        if not conversation_data:
            await asyncio.sleep(2)
            continue
            
        available_workers = [
            w for w in state.active_workers 
            if state.rate_limited_until.get(w, 0) < current_time and w in clients
        ]
        
        if not available_workers:
            await register_and_warmup_group(chat_id)
            await asyncio.sleep(3)
            continue
            
        if current_time < csv_paused_until:
            await asyncio.sleep(1.5)
            continue

        loop_start = time.time()
        msg_data = conversation_data[state.csv_index]
        
        sender_str = msg_data.get("sender", "").strip()
        conv_id = msg_data.get("conversation_id", "").strip()
        msg_text = msg_data.get("message", "...")
        csv_id = msg_data.get("id", "").strip()
        reply_to_csv = msg_data.get("reply_to", "").strip()
        topic = msg_data.get("topic", "general")
        
        clean_text = msg_text.strip().lower()
        if clean_text and clean_text in recent_sent_dataset_texts and len(clean_text) > 4:
            state.csv_index = (state.csv_index + 1) % len(conversation_data)
            continue
        recent_sent_dataset_texts.append(clean_text)
        
        # Map thread roles dynamically across ALL available accounts (acc1, acc2, acc3, acc4)
        # so that the Bot (acc4) and user accounts talk completely equally like friends!
        if conv_id and conv_id != state.last_conv_id:
            state.recent_thread_messages.clear()
            thread_pause = min(random.uniform(2.0, 5.0), state.speed * 0.7)
            await asyncio.sleep(thread_pause)
            if available_workers:
                shuffled = random.sample(available_workers, len(available_workers))
                csv_roles = ["acc1", "acc2", "acc3"]
                state.thread_speaker_map = {
                    role: shuffled[i % len(shuffled)]
                    for i, role in enumerate(csv_roles)
                }
        state.last_conv_id = conv_id

        if not state.thread_speaker_map and available_workers:
            shuffled = random.sample(available_workers, len(available_workers))
            csv_roles = ["acc1", "acc2", "acc3"]
            state.thread_speaker_map = {
                role: shuffled[i % len(shuffled)]
                for i, role in enumerate(csv_roles)
            }

        chosen_key = state.thread_speaker_map.get(sender_str)
        if not chosen_key or chosen_key not in available_workers:
            chosen_key = random.choice(available_workers)

        # Prevent the exact same worker from replying to themselves when multiple workers exist
        if chosen_key == state.last_chosen_key and len(available_workers) > 1 and reply_to_csv:
            alt_workers = [w for w in available_workers if w != state.last_chosen_key]
            if alt_workers:
                chosen_key = random.choice(alt_workers)
            
        is_same_speaker = (chosen_key == state.last_chosen_key)
        state.last_chosen_key = chosen_key
        
        client = clients[chosen_key]["client"]
        name = clients[chosen_key]["name"]
        
        try:
            if chosen_key not in state.cached_entities:
                state.cached_entities[chosen_key] = await client.get_entity(chat_id)
            entity = state.cached_entities[chosen_key]
            
            reply_msg_id = state.message_tracker.get(reply_to_csv)
            
            # =========================================================================
            # VOICE NOTE ENGINE INTEGRATION (Realistic Adult Male Voice Notes)
            # =========================================================================
            # Distinct voices for each boy:
            # - acc1: Natural adult guy (hi-IN-MadhurNeural, +4% rate)
            # - acc2: Deeper chill guy (hi-IN-MadhurNeural, -5Hz pitch, -3% rate)
            # - acc3: Energetic guy (hi-IN-MadhurNeural, +6Hz pitch, +8% rate)
            # Minimum 15-minute cooldown per group, natural 2.5% chance
            voice_sent = False
            if (chosen_key in ["acc1", "acc2", "acc3", "acc4"] and 
                (current_time - state.last_voice_time > 900) and 
                random.random() < 0.025):
                try:
                    vn_path, vn_text = await voice_engine.generate_voice_note(
                        account_key=chosen_key,
                        context_text=msg_text,
                        category=topic
                    )
                    if vn_path and os.path.exists(vn_path):
                        await simulate_typing(client, entity, "voice", group_speed=state.speed)
                        try:
                            sent_vn = await client.send_file(
                                entity,
                                vn_path,
                                voice_note=True,
                                reply_to=reply_msg_id
                            )
                        except Exception:
                            sent_vn = await client.send_file(
                                entity,
                                vn_path,
                                voice_note=True
                            )
                        state.last_voice_time = time.time()
                        voice_sent = True
                        logging.info(f"🎙 [{name}] Sent Realistic Adult Boy Voice Note in '{state.title}': '{vn_text}'")
                        if state.delete_delay > 0:
                            asyncio.create_task(delete_message_later(client, entity, sent_vn.id, state.delete_delay))
                        try: os.remove(vn_path)
                        except: pass
                except Exception as ve:
                    logging.warning(f"Voice note send error in '{state.title}': {ve}")
                    
            if not voice_sent:
                await simulate_typing(client, entity, msg_text, group_speed=state.speed)
                try:
                    sent_msg = await client.send_message(entity, msg_text, reply_to=reply_msg_id)
                except Exception:
                    sent_msg = await client.send_message(entity, msg_text)
                    
                if csv_id:
                    state.message_tracker[csv_id] = sent_msg.id
                    if len(state.message_tracker) > 500:
                        state.message_tracker.pop(next(iter(state.message_tracker)))
                        
                if state.delete_delay > 0:
                    asyncio.create_task(delete_message_later(client, entity, sent_msg.id, state.delete_delay))
                    
                state.recent_thread_messages.append(f"{name}: {msg_text}")
                if len(state.recent_thread_messages) > 6:
                    state.recent_thread_messages.pop(0)

            # Advance index for this group
            state.csv_index = (state.csv_index + 1) % len(conversation_data)
            
            if state.csv_index % 10 == 0:
                asyncio.create_task(save_group_state_to_telegram(chat_id))

        except FloodWaitError as fe:
            state.cached_entities.pop(chosen_key, None)
            state.rate_limited_until[chosen_key] = current_time + fe.seconds
            logging.warning(f"[{name}] Rate limited in '{state.title}' for {fe.seconds}s")
            await asyncio.sleep(2)
            continue
        except Exception as e:
            state.cached_entities.pop(chosen_key, None)
            logging.error(f"Error in chat loop for '{state.title}': {e}")
            await asyncio.sleep(3)
            
        elapsed = time.time() - loop_start
        if is_same_speaker:
            burst_target = min(state.speed * 0.4, 2.0)
            sleep_duration = max(0.3, burst_target - elapsed)
        else:
            target_interval = state.speed * random.uniform(0.95, 1.05)
            sleep_duration = max(0.2, target_interval - elapsed)
            
        await asyncio.sleep(sleep_duration)
        
    state.is_loop_running = False
    logging.info(f"🛑 Chat loop ended for '{state.title}' ({chat_id})")

async def chat_loop_supervisor():
    """
    Multi-tenant group supervisor: monitors active groups, handles midnight day rollover,
    and runs independent conversation loops for all active groups concurrently.
    """
    logging.info("Multi-tenant chat supervisor started. Monitoring active groups...")
    last_checked_day = get_ist_day_name()
    while True:
        try:
            now_day = get_ist_day_name()
            if now_day != last_checked_day:
                logging.info(f"🕛 [Midnight Rollover - IST] Day changed to {now_day}! Hot-reloading dataset...")
                load_csv(now_day, shuffle_threads=True)
                last_checked_day = now_day
                for cid, st in list(group_states.items()):
                    st.csv_index = 0
                    st.active_day_name = now_day
                    asyncio.create_task(save_group_state_to_telegram(cid))
                    
            # Check all active groups and ensure their loop is running
            for cid, st in list(group_states.items()):
                if st.is_active and st.automation_active and not st.is_loop_running:
                    logging.info(f"Supervisor starting loop for active group '{st.title}' ({cid})")
                    asyncio.create_task(run_group_chat_loop(cid))
        except Exception as e:
            logging.error(f"Supervisor error: {e}")
        await asyncio.sleep(10)

async def dummy_server():
    try:
        async def hello(request):
            return web.Response(text="Bot is running live on Render!")
        app = web.Application()
        app.add_routes([web.get('/', hello)])
        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.environ.get("PORT", 8080))
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        logging.info(f"Advanced Render health-check server started on port {port}")
    except Exception as e:
        logging.error(f"Failed to start web server: {e}")

async def background_reconnect_account(key, cfg, wait_seconds):
    try:
        logging.info(f"⏳ [{cfg['name']}] Background reconnect task waiting {wait_seconds}s before attempting login...")
        await asyncio.sleep(wait_seconds + 2)
        bot_token = cfg.get("bot_token")
        session_str = cfg.get("session")
        api_id = cfg["api_id"]
        api_hash = cfg["api_hash"]
        client = None
        for attempt in range(1, 6):
            try:
                if session_str:
                    client = TelegramClient(StringSession(session_str), api_id, api_hash)
                    await client.start()
                elif bot_token and key == "acc4":
                    client = TelegramClient(StringSession(), api_id, api_hash)
                    await client.start(bot_token=bot_token)
                break
            except FloodWaitError as fe:
                logging.warning(f"[{cfg['name']}] Still rate limited, waiting {fe.seconds}s...")
                await asyncio.sleep(fe.seconds + 2)
            except Exception as ce:
                logging.warning(f"[{cfg['name']}] Reconnect attempt {attempt} failed: {ce}. Retrying in 10s...")
                await asyncio.sleep(10)

        if not client or not client.is_connected():
            logging.error(f"[{cfg['name']}] Background reconnect failed to establish connection.")
            return

        try:
            me = await client.get_me()
            uid = me.id if me else cfg.get("user_id")
        except Exception:
            uid = cfg.get("user_id")
            
        if uid:
            OUR_USER_IDS.add(uid)
            
        clients[key] = {"client": client, "name": cfg["name"], "user_id": uid}
        logging.info(f"🎉 [{cfg['name']}] Background reconnect successful! Account is now ONLINE.")
        if key in ("acc4", "acc1"):
            setup_commands(client)
        asyncio.create_task(client.run_until_disconnected())
    except Exception as e:
        logging.error(f"[{cfg['name']}] Background reconnect failed: {e}")

async def main():
    load_csv()
    
    # Start web server for Render
    await dummy_server()
    
    for key, cfg in accounts.items():
        session_str = cfg.get("session")
        bot_token = cfg.get("bot_token")
        api_id = cfg["api_id"]
        api_hash = cfg["api_hash"]
        
        if not session_str and not bot_token:
            continue
            
        connected = False
        for attempt in range(1, 6):
            try:
                if session_str:
                    client = TelegramClient(StringSession(session_str), api_id, api_hash)
                    await client.start()
                    try:
                        me = await client.get_me()
                        uid = me.id if me else cfg.get("user_id")
                    except Exception:
                        uid = cfg.get("user_id")
                    if uid:
                        OUR_USER_IDS.add(uid)
                    clients[key] = {"client": client, "name": cfg["name"], "user_id": uid}
                    logging.info(f"Connected {cfg['name']} (ID: {uid}) via Session String.")
                    connected = True
                    break
                elif bot_token and key == "acc4":
                    client = TelegramClient(StringSession(), api_id, api_hash)
                    await client.start(bot_token=bot_token)
                    try:
                        me = await client.get_me()
                        uid = me.id if me else None
                    except Exception:
                        uid = None
                    if uid:
                        OUR_USER_IDS.add(uid)
                    clients[key] = {"client": client, "name": cfg["name"], "user_id": uid}
                    logging.info(f"Connected {cfg['name']} (ID: {uid}) via Bot Token.")
                    connected = True
                    break
            except FloodWaitError as e:
                if e.seconds > 60:
                    logging.warning(f"⚠️ Telegram Rate Limit! {cfg['name']} has FloodWait of {e.seconds}s (~{e.seconds // 60}m). Launching background reconnect so startup is NOT blocked!")
                    asyncio.create_task(background_reconnect_account(key, cfg, e.seconds))
                    break
                else:
                    logging.warning(f"Telegram Rate Limit! {cfg['name']} must wait {e.seconds}s before logging in. Sleeping...")
                    await asyncio.sleep(e.seconds + 2)
            except Exception as e:
                logging.warning(f"[{cfg['name']}] Connection attempt {attempt}/5 failed ({e}). Telegram servers may have temporary issues. Retrying in 5 seconds...")
                await asyncio.sleep(5)
                
        if not connected and not any(k == key for k in clients):
            logging.error(f"[{cfg['name']}] Skipped or queued in background. Continuing startup with other accounts.")
            
    global TARGET_CHAT_ID, TARGET_INPUT_PEER, BOT_ENTITY, SPAWN_CHAT_ID, SPAWN_CHAT_TITLE
    BOT_ENTITY = None
    TARGET_INPUT_PEER = None
    if "acc1" in clients:
        acc1_client = clients["acc1"]["client"]
        target_resolved = False
        
        # Step 1: Pre-fetch dialogs so Telethon caches all groups and channels
        dialogs = []
        try:
            dialogs = await acc1_client.get_dialogs(limit=100)
            # Check if any dialog matches the target chat ID (-1003529827660)
            for d in dialogs:
                if d.is_group or d.is_channel:
                    d_peer_id = utils.get_peer_id(d.entity)
                    if d.id == -1003529827660 or d_peer_id == -1003529827660 or "3529827660" in str(d.id):
                        entity = d.entity
                        TARGET_CHAT_ID = d_peer_id
                        SPAWN_CHAT_ID = d_peer_id
                        SPAWN_CHAT_TITLE = getattr(d, 'title', '') or SPAWN_CHAT_TITLE
                        if hasattr(entity, 'access_hash'):
                            from telethon.tl.types import InputPeerChannel
                            TARGET_INPUT_PEER = InputPeerChannel(entity.id, entity.access_hash)
                        logging.info(f"🎯 [Target Chat] Directly resolved from dialogs: '{d.title}' (ID: {TARGET_CHAT_ID})")
                        target_resolved = True
                        break
        except Exception as de:
            logging.warning(f"Dialog pre-fetch warning: {de}")

        # Step 2: If not resolved yet, try numeric TARGET_CHAT or non-invite username
        if not target_resolved:
            try:
                target_str = str(TARGET_CHAT).strip()
                if target_str.startswith("-100") or target_str.lstrip('-').isdigit():
                    entity = await acc1_client.get_entity(int(target_str))
                    TARGET_CHAT_ID = utils.get_peer_id(entity)
                    if hasattr(entity, 'access_hash'):
                        from telethon.tl.types import InputPeerChannel
                        TARGET_INPUT_PEER = InputPeerChannel(entity.id, entity.access_hash)
                    logging.info(f"🎯 Resolved TARGET_CHAT numeric entity: {TARGET_CHAT_ID}")
                    target_resolved = True
                elif not any(prefix in target_str for prefix in ["http://", "https://", "t.me/", "+", "joinchat"]):
                    entity = await acc1_client.get_entity(target_str)
                    TARGET_CHAT_ID = utils.get_peer_id(entity)
                    target_resolved = True
            except Exception as te:
                logging.warning(f"Could not resolve TARGET_CHAT string: {te}")

        # Step 3: Title-based search in dialogs fallback
        if not target_resolved and dialogs:
            try:
                for d in dialogs:
                    if d.is_group or d.is_channel:
                        title = (getattr(d, 'title', '') or "").lower()
                        if any(term in title for term in ["bleach", "prisoner", "world", "mafia", "tarot", "anime", "limited", "club"]):
                            entity = d.entity
                            TARGET_CHAT_ID = utils.get_peer_id(d.entity)
                            SPAWN_CHAT_ID = TARGET_CHAT_ID
                            SPAWN_CHAT_TITLE = d.title or SPAWN_CHAT_TITLE
                            if hasattr(entity, 'access_hash'):
                                from telethon.tl.types import InputPeerChannel
                                TARGET_INPUT_PEER = InputPeerChannel(entity.id, entity.access_hash)
                            logging.info(f"🎯 Auto-discovered target group from dialogs by title: '{d.title}' (ID: {TARGET_CHAT_ID})")
                            target_resolved = True
                            break
            except Exception as dialog_err:
                logging.error(f"Dialog title search fallback error: {dialog_err}")
                
        if not target_resolved and TARGET_CHAT_ID:
            logging.info(f"Using default fallback TARGET_CHAT_ID: {TARGET_CHAT_ID}")

    if "acc4" in clients:
        logging.info("Registering official admin commands on Account 4 (Bot).")
        setup_commands(clients["acc4"]["client"])
    if "acc1" in clients:
        logging.info("Registering slash-free command listener on Account 1.")
        setup_commands(clients["acc1"]["client"])

    # Warm up human accounts entity cache safely
    for key, c in clients.items():
        if key != "acc4":
            try:
                await c["client"].get_dialogs(limit=30)
                if TARGET_CHAT_ID and isinstance(TARGET_CHAT_ID, int):
                    try:
                        await c["client"].get_entity(TARGET_CHAT_ID)
                    except: pass
                logging.info(f"Warmed up entity cache for {c['name']}")
            except Exception as e:
                logging.error(f"Failed to warm up cache for {c['name']}: {e}")
        
    logging.info("All accounts connected! Waiting for /lockon command...")
    
    # Auto-start history sweeper on boot using Account 1
    if "acc1" in clients and delete_delay > 0:
        try:
            target = TARGET_CHAT_ID or TARGET_CHAT
            if isinstance(target, str) and (target.startswith("-100") or target.lstrip('-').isdigit()):
                target = int(target)
            entity = await clients["acc1"]["client"].get_entity(target)
            asyncio.create_task(history_sweeper(clients["acc1"]["client"], entity, delete_delay))
        except Exception as e:
            logging.error(f"Auto-sweeper start failed: {e}")
            
    # Launch 15-minute periodic sweeper for long intervals (e.g. 4 days)
    asyncio.create_task(periodic_history_sweeper())
    

    if "acc1" in clients:
        # Step 1: If SPAWN_CHAT_ID is known, fetch its title directly
        if SPAWN_CHAT_ID and isinstance(SPAWN_CHAT_ID, int):
            try:
                spawn_ent = await clients["acc1"]["client"].get_entity(SPAWN_CHAT_ID)
                if hasattr(spawn_ent, 'title') and spawn_ent.title:
                    SPAWN_CHAT_TITLE = spawn_ent.title
                logging.info(f"🎯 Auto-Catcher target group resolved: '{SPAWN_CHAT_TITLE}' (ID: {SPAWN_CHAT_ID})")
            except Exception as e:
                logging.warning(f"Could not fetch entity for SPAWN_CHAT_ID {SPAWN_CHAT_ID}: {e}")

        # Step 2: Fallback if not resolved
        if not SPAWN_CHAT_ID and SPAWN_CHAT:
            try:
                if isinstance(SPAWN_CHAT, str) and (SPAWN_CHAT.startswith("-100") or SPAWN_CHAT.lstrip('-').isdigit()):
                    spawn_ent = await clients["acc1"]["client"].get_entity(int(SPAWN_CHAT))
                else:
                    spawn_ent = await clients["acc1"]["client"].get_entity(SPAWN_CHAT)
                SPAWN_CHAT_ID = utils.get_peer_id(spawn_ent)
                if hasattr(spawn_ent, 'title') and spawn_ent.title:
                    SPAWN_CHAT_TITLE = spawn_ent.title
                logging.info(f"Resolved SPAWN_CHAT to ID: {SPAWN_CHAT_ID} ('{SPAWN_CHAT_TITLE}')")
            except Exception as e:
                logging.warning(f"Could not resolve SPAWN_CHAT via link ({e}). Auto-catcher will lock when /lockon or /arisehere is used.")

        # Step 3: Default to TARGET_CHAT_ID if set
        if not SPAWN_CHAT_ID and TARGET_CHAT_ID:
            SPAWN_CHAT_ID = TARGET_CHAT_ID

    # Warm up entity cache for SPAWN_CHAT_ID on all accounts
    if SPAWN_CHAT_ID and isinstance(SPAWN_CHAT_ID, int):
        for key, c in clients.items():
            if key != "acc4":
                try:
                    await c["client"].get_entity(SPAWN_CHAT_ID)
                except Exception:
                    pass

    # Register Arise Gate spawn listener
    for key in ["acc1", "acc2", "acc3"]:
        if key in clients:
            c_client = clients[key]["client"]
            @c_client.on(events.NewMessage())
            async def spawn_watcher(event):
                if not event.is_group and not event.is_channel:
                    return
                # STRICT GROUP FILTER: ONLY collect in the target group (Prisoner world)!
                chat_title = ""
                try:
                    chat = await event.get_chat()
                    chat_title = (getattr(chat, 'title', '') or '').strip()
                except Exception:
                    pass

                # If from Bleach world or Prisoner world, ALWAYS process and lock onto it!
                if any(term in chat_title.lower() for term in ["bleach", "prisoner"]):
                    globals()['SPAWN_CHAT_ID'] = event.chat_id
                    globals()['SPAWN_CHAT_TITLE'] = chat_title or "Bleach world 👾"
                elif SPAWN_CHAT_ID and event.chat_id == SPAWN_CHAT_ID:
                    pass
                elif TARGET_CHAT_ID and event.chat_id == TARGET_CHAT_ID:
                    pass
                else:
                    return

                await handle_spawn_message(event)
    logging.info(f"Arise Auto-Catcher listener registered! Locked to: '{SPAWN_CHAT_TITLE}' (ID: {SPAWN_CHAT_ID})")
    # Restore per-group isolated states & launch multi-group chat supervisor!
    await load_all_states_from_telegram()
    
    # If no groups were previously saved as active, initialize TARGET_CHAT_ID so bot starts talking!
    active_count = len([s for s in group_states.values() if s.is_active])
    if active_count == 0 and TARGET_CHAT_ID:
        default_state = get_group_state(TARGET_CHAT_ID, SPAWN_CHAT_TITLE)
        default_state.is_active = True
        default_state.speed = message_speed
        logging.info(f"Default group '{default_state.title}' ({TARGET_CHAT_ID}) activated at speed {default_state.speed}s.")
        asyncio.create_task(register_and_warmup_group(TARGET_CHAT_ID))
        asyncio.create_task(run_group_chat_loop(TARGET_CHAT_ID))

    asyncio.create_task(chat_loop_supervisor())
    
    # 3. Keep all account connections alive
    while True:
        try:
            await asyncio.gather(*[c["client"].run_until_disconnected() for c in clients.values()])
        except Exception as e:
            logging.error(f"Telethon protocol crash ignored: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
            for c in clients.values():
                if not c["client"].is_connected():
                    await c["client"].connect()

if __name__ == "__main__":
    asyncio.run(main())
