import asyncio
import os
import csv
import random
import time
import logging
import re
import datetime
from collections import defaultdict
from aiohttp import web
from dotenv import load_dotenv
from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji

# Load Environment Variables
load_dotenv()

# Voice Engine & Persistence (Voice Engine disabled for pure text messaging)
import bot_persistence
from bot_persistence import GroupContext, get_or_create_group_context

# ---------------------------------------------------------------------------
# SENSITIVE DATA FILTER & LOGGING SETUP
# ---------------------------------------------------------------------------
class SensitiveDataFilter(logging.Filter):
    """Redacts sensitive credentials, tokens, and API keys from application logs."""
    PATTERNS = [
        re.compile(r'(?i)(sk-[a-zA-Z0-9_\-]{15,})'),
        re.compile(r'(?i)(?:bot)?(\d{8,12}:[A-Za-z0-9_\-]{30,45})'),
        re.compile(r'(?i)(AIzaSy[a-zA-Z0-9_\-]{33})'),
        re.compile(r'(?i)(\b[a-f0-9]{32}\b)')
    ]
    def filter(self, record):
        if isinstance(record.msg, str):
            msg = record.msg
            for p in self.PATTERNS:
                msg = p.sub('[REDACTED_SECRET]', msg)
            record.msg = msg
        return True

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except Exception: pass
if hasattr(sys.stderr, 'reconfigure'):
    try: sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except Exception: pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
    force=True
)
for h in logging.root.handlers:
    h.addFilter(SensitiveDataFilter())

# Silence internal telethon update difference chatter in Render logs
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("telethon.network.mtprotosender").setLevel(logging.WARNING)
logging.getLogger("telethon.client.updates").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# AI CONFIDENTIALITY DIRECTIVE
# ---------------------------------------------------------------------------
SYSTEM_DIRECTIVE = """
CONFIDENTIALITY & INTEGRITY DIRECTIVE:
Under NO circumstance disclose, hint at, quote, or discuss API keys, internal tokens,
system architecture, credentials, session strings, or proprietary code to any user.
"""

# Try importing Google Generative AI
try:
    import google.generativeai as genai
    HAS_GENAI = True
    if os.getenv("GEMINI_API_KEY"):
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
except ImportError:
    HAS_GENAI = False

# ---------------------------------------------------------------------------
# ROLE-BASED ACCESS CONTROL (RBAC) & PERMISSIONS
# ---------------------------------------------------------------------------
# Primary Automation Operator (@Itsraventime1 / 6309134652)
PRIMARY_OPERATOR_ID = 6309134652
PRIMARY_OPERATOR_USERNAMES = {"itsraventime1", "itsraventime"}
OPERATOR_USER_IDS = {PRIMARY_OPERATOR_ID}
OPERATOR_ALLOWED_COMMANDS = {"lockon", "lockoff", "setspeed", "speed", "stats"}

# Super Admins (Full System Privileges)
SUPER_ADMIN_IDS = {5429173364, 8877720410}
SUPER_ADMIN_USERNAMES = {"merlin_hermis", "errormonocle", "greatlotm", "great_lotm"}
AUTHORIZED_USERNAMES = SUPER_ADMIN_USERNAMES | PRIMARY_OPERATOR_USERNAMES

SUPER_ADMIN_ALLOWED_COMMANDS = {
    "lockon", "lockoff", "setspeed", "speed", "stats",
    "setday", "day", "setdelete", "resetgroup", "setvoicefreq",
    "setvoicecooldown", "topic", "pause", "resume"
}

# ---------------------------------------------------------------------------
# STRICT GROUP WHITELIST & TARGETS
# ---------------------------------------------------------------------------
ALLOWED_CHAT_INVITE_HASH = "Elgeiny2Lk81MzRl"
_env_target = (os.getenv("TARGET_CHAT") or "").strip()
if _env_target and not any(bad in _env_target for bad in ("1tWK4j-BYC85MDVl", "-1003529827660", "noVnALjR8Uw1OWU1")):
    TARGET_CHAT = _env_target
else:
    TARGET_CHAT = "https://t.me/+Elgeiny2Lk81MzRl"

TARGET_CHAT_ID = -1003529827660
ALLOWED_GROUP_IDS = {-1002361093080, -1003529827660, 3529827660}

def is_allowed_group(chat_id: int, title: str = "") -> bool:
    """
    STRICT SECURITY DIRECTIVE:
    This bot is strictly whitelisted to operate ONLY in the user's designated group:
    https://t.me/+Elgeiny2Lk81MzRl (Joker's Jamghat).
    All other groups are completely unauthorized, de-permissioned, and blocked.
    """
    if not chat_id:
        return False
    if chat_id in ALLOWED_GROUP_IDS:
        return True
    if TARGET_CHAT_ID and chat_id == TARGET_CHAT_ID:
        ALLOWED_GROUP_IDS.add(chat_id)
        return True
    # Match with or without Telegram's -100 prefix
    raw_s = str(abs(chat_id))
    if raw_s.startswith("100"):
        raw_s = raw_s[3:]
    for allowed in list(ALLOWED_GROUP_IDS):
        a_s = str(abs(allowed))
        if a_s.startswith("100"):
            a_s = a_s[3:]
        if raw_s == a_s:
            ALLOWED_GROUP_IDS.add(chat_id)
            return True
    if title:
        t_clean = title.strip().lower()
        if any(kw in t_clean for kw in ["jamghat", "joker"]):
            ALLOWED_GROUP_IDS.add(chat_id)
            logging.info(f"🛡️ [Group Whitelist] Authorized target group '{title}' (ID: {chat_id})")
            return True
    return False

# ---------------------------------------------------------------------------
# GROUP STATE DEFINITION (COMPATIBILITY)
# ---------------------------------------------------------------------------
class GroupState:
    def __init__(self, chat_id: int, title: str = "", is_active: bool = False,
                 automation_active: bool = False, conversational_ai_active: bool = True,
                 speed: float = 10.0, delete_delay: int = 360, voice_replies_enabled: bool = True,
                 voice_cooldown: int = 15, voice_probability: float = 0.25, csv_index: int = 0,
                 active_day_name: str = "monday", conversation_history: list = None,
                 state_msg_id: int = None):
        self.chat_id = chat_id
        self.title = title
        self.is_active = is_active
        self.automation_active = automation_active
        self.conversational_ai_active = conversational_ai_active
        self.speed = speed
        self.delete_delay = delete_delay
        self.voice_replies_enabled = voice_replies_enabled
        self.voice_cooldown = voice_cooldown
        self.voice_probability = voice_probability
        self.csv_index = csv_index
        self.active_day_name = active_day_name
        self.conversation_history = conversation_history or []
        self.state_msg_id = state_msg_id

group_states = {}

def get_group_state(chat_id: int, title: str = "") -> GroupState:
    if chat_id not in group_states:
        ctx = bot_persistence.get_or_create_group_context(chat_id, title)
        group_states[chat_id] = GroupState(
            chat_id=chat_id,
            title=title or ctx.title,
            is_active=ctx.automation_active,
            automation_active=ctx.automation_active,
            speed=ctx.speed if ctx.speed else 10.0,
            delete_delay=ctx.delete_delay,
            voice_replies_enabled=ctx.voice_replies_enabled,
            voice_cooldown=ctx.voice_cooldown,
            voice_probability=ctx.voice_probability,
            csv_index=ctx.csv_index,
            active_day_name=ctx.active_day_name or "monday"
        )
    elif title and not group_states[chat_id].title:
        group_states[chat_id].title = title
    return group_states[chat_id]

# ---------------------------------------------------------------------------
# GLOBAL AUTOMATION SETTINGS (OLD-TYPE SIMPLICITY)
# ---------------------------------------------------------------------------
AUTO_DELETE_DELAY = 777600    # Default auto-delete: 9 days (9 * 86400s)
MESSAGE_DELAY = 15.0          # Default speed: 15.0 seconds (classic stability)
CHAT_PAUSED = False
AI_TOPIC = None
TOTAL_MESSAGES_SENT = 0
VOICE_FREQUENCY = 10         # Legacy compatibility placeholder
voice_step_counter = 0

def format_seconds_to_readable(seconds: int) -> str:
    if seconds <= 0:
        return "Disabled (0s)"
    if seconds >= 86400:
        days = seconds // 86400
        rem = seconds % 86400
        return f"{days} day{'s' if days != 1 else ''}" + (f" {rem // 3600}h" if rem >= 3600 else "")
    if seconds >= 3600:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if seconds >= 60:
        minutes = seconds // 60
        return f"{minutes} min{'s' if minutes != 1 else ''}"
    return f"{seconds}s"

bot_active = False           # Master switch toggled by /lockon & /lockoff
chat_task = None
active_chat_tasks = set()
clients = {}
conversation_script = []
conversation_data = []       # alias for compatibility
active_day_name = "monday"
CSV_FILE = "conversations_monday.csv"
worker_rate_limited_until = {}
processed_cmd_msg_ids = set()
processed_human_msg_ids = set()
cached_entities = {}
OUR_USER_IDS = {5429173364, 8877720410}

# Initialize Google GenAI Client
gemini_client = None
if os.getenv("GEMINI_API_KEY"):
    try:
        from google import genai
        gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    except Exception as ge:
        logging.warning(f"Could not initialize google.genai: {ge}")

async def generate_ai_reply_to_human(msg_text: str) -> str:
    """
    Uses Gemini to generate a natural, casual, short (1-2 sentences) Hinglish/English reply.
    """
    if gemini_client:
        try:
            prompt = (
                f"You are a friendly, casual anime and gaming fan chatting with friends in a Telegram group.\n"
                f"A member said: '{msg_text}'\n"
                f"Rules:\n"
                f"- Reply in 1 very short sentence (maximum 2 short sentences).\n"
                f"- Use casual, natural Hinglish or Indian English (like 'bhai bilkul', 'sahi baat h', 'arre haan lol').\n"
                f"- Never say you are an AI or bot. You are just a group member.\n"
                f"- Don't use too many emojis (0 or 1 natural emoji max).\n"
            )
            if AI_TOPIC:
                prompt += f"- Naturally steer towards: {AI_TOPIC}\n"
            
            res = await asyncio.wait_for(
                gemini_client.aio.models.generate_content(model="gemini-3.5-flash-lite", contents=prompt),
                timeout=8.0
            )
            if res and res.text:
                return res.text.strip()
        except Exception as ge:
            logging.debug(f"Gemini reply error: {ge}")

    # Fallback casual replies if API is slow or missing
    fallbacks = [
        "sahi baat h bhai bilkul 😂",
        "arre haan maine bhi suna tha ye",
        "100% agreed bhai haha",
        "kya scene h bhai iska?",
        "hn bhai ye toh check karna padega",
        "arre bilkul bhai, exactly!",
        "wait check karke batata hu ruk",
        "haha true that!"
    ]
    return random.choice(fallbacks)

async def get_client_entity(client_key: str):
    """
    Retrieves and caches the target supergroup entity for a specific client.
    Ensures that access_hash is present in the client's session database.
    """
    global TARGET_CHAT_ID
    if client_key in cached_entities and cached_entities[client_key] is not None:
        return cached_entities[client_key]

    acc = clients.get(client_key)
    if not acc or not acc.get("client") or not acc["client"].is_connected():
        return None
    cl = acc["client"]

    # 1. Dialogs pre-fetch (for human user accounts only; bot tokens cannot invoke get_dialogs)
    if client_key != "acc4" and not acc.get("bot_token"):
        try:
            dialogs = await asyncio.wait_for(cl.get_dialogs(limit=50), timeout=8.0)
            for d in dialogs:
                if d.is_group or d.is_channel:
                    d_id = getattr(d, 'id', None)
                    ent = getattr(d, 'entity', None)
                    ent_id = getattr(ent, 'id', None)
                    d_title = (getattr(d, 'title', '') or "").strip().lower()

                    is_target = (
                        d_id in ALLOWED_GROUP_IDS or
                        ent_id in ALLOWED_GROUP_IDS or
                        (TARGET_CHAT_ID and (d_id == TARGET_CHAT_ID or ent_id == TARGET_CHAT_ID)) or
                        any(kw in d_title for kw in ["jamghat", "joker"])
                    )
                    if is_target:
                        target_ent = ent if ent is not None else d
                        cached_entities[client_key] = target_ent
                        if d_id:
                            ALLOWED_GROUP_IDS.add(d_id)
                        if ent_id:
                            ALLOWED_GROUP_IDS.add(ent_id)
                        if not TARGET_CHAT_ID and (d_id or ent_id):
                            TARGET_CHAT_ID = d_id or ent_id
                        logging.info(f"🎯 [{acc.get('name', client_key)}] Pre-warmed group entity: '{getattr(d, 'title', '')}'")
                        return target_ent
        except Exception as de:
            logging.debug(f"Dialog fetch notice for {client_key}: {de}")

    # 2. Try direct get_entity with TARGET_CHAT_ID or TARGET_CHAT
    target_ref = TARGET_CHAT_ID or TARGET_CHAT
    if target_ref:
        try:
            ent = await asyncio.wait_for(cl.get_entity(target_ref), timeout=5.0)
            if ent:
                cached_entities[client_key] = ent
                return ent
        except Exception:
            pass

    return None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STICKERS_DIR = os.path.join(SCRIPT_DIR, "stickers")
if not os.path.exists(STICKERS_DIR):
    os.makedirs(STICKERS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# ACCOUNTS CONFIGURATION
# ---------------------------------------------------------------------------
accounts = {
    "acc1": {"name": "Account 1", "api_id": 2282111, "api_hash": "da58a1841a16c352a2a999171bbabcad", "session": os.getenv("ACC1_SESSION"), "bot_token": None, "user_id": 5429173364},
    "acc2": {"name": "Account 2", "api_id": 8447214, "api_hash": "9ec5782ddd935f7e2763e5e49a590c0d", "session": os.getenv("ACC2_SESSION"), "bot_token": None},
    "acc3": {"name": "Account 3", "api_id": 22792918, "api_hash": "ff10095d2bb96d43d6eb7a7d9fc85f81", "session": os.getenv("ACC3_SESSION"), "bot_token": None},
    "acc4": {
        "name": "Account 4 (Bot)",
        "api_id": 2282111,
        "api_hash": "da58a1841a16c352a2a999171bbabcad",
        "session": None,
        "bot_token": os.getenv("ACC4_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN"),
    }
}

IST_TZ = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

def get_ist_day_name():
    return datetime.datetime.now(IST_TZ).strftime("%A").lower()

def load_csv(day_name=None, shuffle_threads=True):
    global conversation_script, conversation_data, CSV_FILE, active_day_name
    if day_name:
        active_day_name = day_name.lower().strip()
    else:
        active_day_name = get_ist_day_name()
        
    day_csv = f"conversations_{active_day_name}.csv"
    candidate_path = os.path.join(SCRIPT_DIR, day_csv)
    
    if os.path.exists(candidate_path):
        CSV_FILE = day_csv
        csv_path = candidate_path
    else:
        CSV_FILE = "anime_group_chat_10000.csv"
        csv_path = os.path.join(SCRIPT_DIR, CSV_FILE)
        
    conversation_script.clear()
    if os.path.exists(csv_path):
        raw_rows = []
        with open(csv_path, mode="r", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            for row in reader:
                sender = row.get("sender", "").strip()
                message = row.get("message", "").strip()
                if sender and message:
                    raw_rows.append({
                        "id": (row.get("id") or row.get("\ufeffid") or "").strip(),
                        "sender": sender,
                        "message": message,
                        "reply_to": (row.get("reply_to") or "").strip(),
                        "reaction": (row.get("reaction") or "").strip(),
                        "conversation_id": row.get("conversation_id", "default")
                    })
                    
        if shuffle_threads:
            threads = defaultdict(list)
            for r in raw_rows:
                threads[r["conversation_id"]].append(r)
            thread_ids = list(threads.keys())
            random.shuffle(thread_ids)
            for tid in thread_ids:
                conversation_script.extend(threads[tid])
        else:
            conversation_script.extend(raw_rows)
            
        conversation_data.clear()
        conversation_data.extend(conversation_script)
        logging.info(f"Loaded {len(conversation_script)} messages from {CSV_FILE} (Day: {active_day_name.capitalize()}).")
    else:
        logging.error(f"CSV file not found: {csv_path}")

# ---------------------------------------------------------------------------
# MESSAGE DELETION HELPERS
# ---------------------------------------------------------------------------
async def delete_message_later(client, chat, message_id, delay):
    if not delay or delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat, message_id)
        logging.debug(f"Auto-deleted message {message_id} after {delay}s")
    except Exception as e:
        logging.debug(f"Failed to delete message: {e}")

async def delete_other_message(message, delay):
    if not delay or delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        await message.delete()
        logging.debug(f"Auto-deleted member message after {delay}s")
    except Exception as e:
        logging.debug(f"Failed to delete member message: {e}")

async def history_sweeper(client, chat_entity, delay_seconds):
    try:
        logging.info(f"Starting history sweeper for messages older than {delay_seconds}s...")
        cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=delay_seconds)
        messages_to_delete = []
        async for msg in client.iter_messages(chat_entity, offset_date=cutoff_date):
            messages_to_delete.append(msg.id)
            if len(messages_to_delete) >= 100:
                await client.delete_messages(chat_entity, messages_to_delete)
                messages_to_delete.clear()
                await asyncio.sleep(2.0)
        if messages_to_delete:
            await client.delete_messages(chat_entity, messages_to_delete)
        logging.info("History sweeper finished successfully.")
    except Exception as e:
        logging.error(f"Error in history sweeper: {e}")

async def simulate_typing(client, entity, text, group_speed=15.0):
    if group_speed <= 5.0:
        return
    max_type = min(max(group_speed * 0.25, 0.5), 2.5)
    typing_time = min(max(len(text) * 0.025, 0.4), max_type)
    try:
        async with client.action(entity, 'typing'):
            await asyncio.sleep(typing_time)
    except Exception:
        await asyncio.sleep(typing_time)

async def send_dynamic_reply(client, entity, target_msg, text):
    global TOTAL_MESSAGES_SENT
    await simulate_typing(client, entity, text, group_speed=MESSAGE_DELAY)
    try:
        sent_msg = await asyncio.wait_for(client.send_message(entity, text, reply_to=target_msg), timeout=12.0)
        TOTAL_MESSAGES_SENT += 1
        if AUTO_DELETE_DELAY > 0:
            asyncio.create_task(delete_message_later(client, entity, sent_msg.id, AUTO_DELETE_DELAY))
        logging.info(f"Sent dynamic reply: {text}")
    except Exception as e:
        logging.error(f"Failed to send dynamic reply: {e}")

# ---------------------------------------------------------------------------
# CORE CHAT LOOP (CLASSIC CONTINUOUS ENGINE - NEVER STOPS UNTIL LOCKOFF)
# ---------------------------------------------------------------------------
async def chat_loop():
    current_task = asyncio.current_task()
    if current_task:
        active_chat_tasks.add(current_task)
    logging.info("🚀 Chat sequence STARTED via remote command!")
    global TOTAL_MESSAGES_SENT, bot_active
    line_index = random.randint(0, max(0, len(conversation_script) - 1)) if conversation_script else 0
    message_tracker = {}
    
    try:
        while bot_active:
            if not bot_active:
                break
            if CHAT_PAUSED:
                await asyncio.sleep(1)
                continue
            if not conversation_script:
                logging.error("The conversation script is empty! Stopping.")
                break
                
            row = conversation_script[line_index]
            csv_speaker = row.get("sender", "acc1")
            msg = row.get("message", "...")
            csv_id = row.get("id", "")
            reply_to_csv = row.get("reply_to", "")
            reaction_emoji = row.get("reaction", "")
            
            now = time.time()
            # 1. Determine all connected workers across all 4 accounts
            all_connected = [k for k in ("acc1", "acc2", "acc3", "acc4") if k in clients and clients[k]["client"].is_connected()]
            if not all_connected:
                all_connected = ["acc1"]

            # Filter out temporarily rate-limited workers
            active_workers = [k for k in all_connected if worker_rate_limited_until.get(k, 0) <= now]
            if not active_workers:
                # If all workers hit flood limits, rest for at most 15s before re-checking
                min_wait = min([max(1.0, worker_rate_limited_until.get(k, 0) - now) for k in all_connected])
                capped_sleep = min(min_wait, 15.0)
                logging.warning(f"All workers temporarily resting. Pausing for {capped_sleep:.1f}s...")
                await asyncio.sleep(capped_sleep)
                active_workers = all_connected

            # Pick preferred speaker if available, otherwise failover to an unblocked worker!
            chosen_key = csv_speaker if csv_speaker in active_workers else random.choice(active_workers)

            # 2. Resolve client and entity with guaranteed fallback to acc1
            entity = await get_client_entity(chosen_key)
            if not entity or chosen_key not in clients or not clients[chosen_key]["client"].is_connected():
                chosen_key = "acc1"
                entity = await get_client_entity("acc1")

            sender_client = clients.get(chosen_key, {}).get("client")
            sender_name = clients.get(chosen_key, {}).get("name", chosen_key)

            if not bot_active:
                break

            if sender_client and entity:
                reply_msg_id = message_tracker.get(reply_to_csv) if reply_to_csv else None
                sent_msg = None
                
                try:
                    if MESSAGE_DELAY > 5.0 and bot_active:
                        try:
                            await asyncio.wait_for(simulate_typing(sender_client, entity, msg, group_speed=MESSAGE_DELAY), timeout=4.0)
                        except Exception:
                            pass
                    
                    if not bot_active:
                        break

                    # Double-try send: first with reply_to, then without reply_to if that fails!
                    try:
                        sent_msg = await asyncio.wait_for(
                            sender_client.send_message(entity, msg, reply_to=reply_msg_id),
                            timeout=10.0
                        )
                    except Exception:
                        if not bot_active:
                            break
                        sent_msg = await asyncio.wait_for(
                            sender_client.send_message(entity, msg),
                            timeout=10.0
                        )
                        
                    if sent_msg:
                        TOTAL_MESSAGES_SENT += 1
                        logging.info(f"[{sender_name}] Sent: {msg[:45]}...")
                        if csv_id:
                            message_tracker[csv_id] = sent_msg.id
                            if len(message_tracker) > 500:
                                message_tracker.pop(next(iter(message_tracker)))

                        if AUTO_DELETE_DELAY > 0:
                            asyncio.create_task(delete_message_later(sender_client, entity, sent_msg.id, AUTO_DELETE_DELAY))

                        if reaction_emoji and reply_msg_id and bot_active:
                            try:
                                await asyncio.wait_for(sender_client(SendReactionRequest(
                                    peer=entity,
                                    msg_id=reply_msg_id,
                                    reaction=[ReactionEmoji(emoticon=reaction_emoji)]
                                )), timeout=5.0)
                            except Exception:
                                pass

                        if random.random() < 0.15 and os.path.exists(STICKERS_DIR) and bot_active:
                            available_stickers = [f for f in os.listdir(STICKERS_DIR) if f.endswith(('.webp', '.png', '.jpg', '.tgs'))]
                            if available_stickers:
                                chosen_sticker = random.choice(available_stickers)
                                sticker_path = os.path.join(STICKERS_DIR, chosen_sticker)
                                await asyncio.sleep(random.uniform(1.0, 2.0))
                                if bot_active:
                                    sent_sticker = await asyncio.wait_for(sender_client.send_file(entity, sticker_path), timeout=10.0)
                                    if AUTO_DELETE_DELAY > 0:
                                        asyncio.create_task(delete_message_later(sender_client, entity, sent_sticker.id, min(AUTO_DELETE_DELAY, 300)))

                except FloodWaitError as fe:
                    worker_rate_limited_until[chosen_key] = time.time() + fe.seconds
                    logging.warning(f"[{sender_name}] Rate limited for {fe.seconds}s. Failover to alternate worker...")
                    # Immediate failover to an alternate unblocked account for this turn!
                    backups = [k for k in all_connected if k != chosen_key and worker_rate_limited_until.get(k, 0) <= time.time()]
                    if backups and bot_active:
                        alt_key = random.choice(backups)
                        alt_client = clients.get(alt_key, {}).get("client")
                        alt_entity = await get_client_entity(alt_key)
                        alt_name = clients.get(alt_key, {}).get("name", alt_key)
                        if alt_client and alt_entity:
                            try:
                                sent_msg = await asyncio.wait_for(alt_client.send_message(alt_entity, msg), timeout=10.0)
                                if sent_msg:
                                    TOTAL_MESSAGES_SENT += 1
                                    logging.info(f"[{alt_name} FAILOVER] Sent: {msg[:45]}...")
                                    if csv_id:
                                        message_tracker[csv_id] = sent_msg.id
                                    if AUTO_DELETE_DELAY > 0:
                                        asyncio.create_task(delete_message_later(alt_client, alt_entity, sent_msg.id, AUTO_DELETE_DELAY))
                            except Exception as alt_err:
                                logging.debug(f"Alt worker send error: {alt_err}")
                except Exception as e:
                    logging.error(f"[{sender_name}] Error in chat turn: {e}")

            # 3. UNCONDITIONAL LINE ADVANCE: NEVER GETS STUCK!
            line_index += 1
            if line_index >= len(conversation_script):
                line_index = random.randint(0, max(0, len(conversation_script) - 1)) if conversation_script else 0
                message_tracker.clear()

            if not bot_active:
                break

            delay = max(1.0, float(MESSAGE_DELAY))
            logging.info(f"Waiting {delay:.1f}s before next message...")
            # Sleep in short increments to respond to lockoff instantly
            elapsed = 0.0
            while elapsed < delay and bot_active and not CHAT_PAUSED:
                step = min(0.5, delay - elapsed)
                await asyncio.sleep(step)
                elapsed += step

    except asyncio.CancelledError:
        logging.info("🛑 Chat sequence CANCELLED via remote command!")
    except Exception as e:
        logging.error(f"Unexpected chat_loop failure: {e}")
    finally:
        if current_task:
            active_chat_tasks.discard(current_task)
        logging.info("🛑 Chat loop stopped cleanly.")

# ---------------------------------------------------------------------------
# AUTO-RECOVERY WATCHDOG (PREVENTS SILENT FREEZES)
# ---------------------------------------------------------------------------
async def chat_loop_watchdog():
    """Monitors chat_loop and automatically revives it if it crashes while bot_active=True."""
    global chat_task, bot_active
    while True:
        await asyncio.sleep(5)
        if not bot_active:
            # When bot is inactive, ensure all background chat tasks are dead
            for t in list(active_chat_tasks):
                if not t.done():
                    t.cancel()
            active_chat_tasks.clear()
            chat_task = None
        else:
            living_tasks = [t for t in active_chat_tasks if not t.done()]
            if not living_tasks:
                logging.warning("⚠️ [Watchdog] Detected chat_loop stopped unexpectedly! Auto-recovering...")
                chat_task = asyncio.create_task(chat_loop())
                active_chat_tasks.add(chat_task)

# ---------------------------------------------------------------------------
# DUMMY WEB SERVER FOR FREE CLOUD HOSTING (RENDER / KOYEB)
# ---------------------------------------------------------------------------
async def health_check(request):
    return web.Response(text="GenZetaBot is running safely 24/7!")

async def keep_alive_pinger():
    """Periodically pings the Render web server to keep free-tier containers from sleeping."""
    await asyncio.sleep(60)  # Wait 1 min after startup
    port = int(os.environ.get("PORT", 8080))
    urls = [
        "https://genzetabot-1-puv4.onrender.com",
        f"http://127.0.0.1:{port}/"
    ]
    while True:
        try:
            import urllib.request
            for url in urls:
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'KeepAlivePinger/1.0'})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        pass
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(600)  # Ping every 10 minutes

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"🌐 Cloud Health Check web server active on port {port}.")
    asyncio.create_task(keep_alive_pinger())

dummy_server = start_web_server

# ---------------------------------------------------------------------------
# RBAC AUTHENTICATION HELPER
# ---------------------------------------------------------------------------
async def check_command_auth(event, cmd_name: str) -> tuple[bool, str]:
    cmd_name = (cmd_name or "").lower().strip()

    # Outgoing commands sent directly by our own connected account
    if getattr(event, 'out', False):
        return True, ""

    s_id = getattr(event, 'sender_id', None)
    if not s_id:
        msg = getattr(event, 'message', None)
        s_id = getattr(getattr(msg, 'from_id', None), 'user_id', None)

    # 1. Fast numeric ID check (0ms, no network latency)
    all_known_admins = SUPER_ADMIN_IDS | OUR_USER_IDS | {5429173364, 8877720410}
    if s_id and s_id in all_known_admins:
        return True, ""

    if s_id and (s_id == PRIMARY_OPERATOR_ID or s_id in OPERATOR_USER_IDS or s_id == 6309134652):
        if cmd_name in OPERATOR_ALLOWED_COMMANDS:
            return True, ""
        logging.warning(f"[Security] Operator {s_id} denied restricted command: '{cmd_name}'")
        return False, f"Access Denied: Primary Operator is restricted to ({', '.join(sorted(OPERATOR_ALLOWED_COMMANDS))})."

    # 2. Username check fallback
    username = ""
    try:
        sender_obj = await asyncio.wait_for(event.get_sender(), timeout=3.0)
        username = (getattr(sender_obj, 'username', '') or '').lower().lstrip('@')
    except Exception:
        pass

    if username in SUPER_ADMIN_USERNAMES:
        return True, ""

    if username in PRIMARY_OPERATOR_USERNAMES or username in {"itsraventime1", "itsraventime"}:
        if cmd_name in OPERATOR_ALLOWED_COMMANDS:
            return True, ""
        return False, f"Access Denied: Primary Operator is restricted to ({', '.join(sorted(OPERATOR_ALLOWED_COMMANDS))})."

    # 3. Group Admin fallback
    try:
        perms = await event.client.get_permissions(event.chat_id, s_id)
        if perms and perms.is_admin and cmd_name in OPERATOR_ALLOWED_COMMANDS:
            return True, ""
    except Exception:
        pass

    # 4. Unauthorized users
    logging.warning(f"[Security] Unauthorized command attempt from user {s_id} (@{username}): '{cmd_name}'")
    return False, "Access Denied: You are not authorized to execute bot control commands."

unauthorized_command_log_cooldown = {}

def check_group_authorized(chat_id: int, event_chat=None) -> bool:
    """
    Constant-time O(1) in-memory check without network calls.
    Validates whether chat_id is in ALLOWED_GROUP_IDS or TARGET_CHAT_ID.
    """
    if not chat_id:
        return False
    if chat_id in ALLOWED_GROUP_IDS or (TARGET_CHAT_ID and chat_id == TARGET_CHAT_ID):
        return True

    # Fast integer / canonical ID matching
    raw_s = str(abs(chat_id))
    if raw_s.startswith("100") and len(raw_s) > 3:
        pure_id = int(raw_s[3:])
        if pure_id in ALLOWED_GROUP_IDS or -pure_id in ALLOWED_GROUP_IDS:
            ALLOWED_GROUP_IDS.add(chat_id)
            return True
    else:
        supergroup_id = -int(f"100{raw_s}")
        if supergroup_id in ALLOWED_GROUP_IDS:
            ALLOWED_GROUP_IDS.add(chat_id)
            return True

    # Check title ONLY if already cached on event_chat without any network RPC
    if event_chat and hasattr(event_chat, 'title') and event_chat.title:
        t_clean = event_chat.title.strip().lower()
        if any(kw in t_clean for kw in ["jamghat", "joker"]):
            ALLOWED_GROUP_IDS.add(chat_id)
            return True

    return False

# ---------------------------------------------------------------------------
# SETUP COMMAND CONTROLLER (ATTACHED TO BOT AND ACC1 WITH STRICT GROUP FILTER)
# ---------------------------------------------------------------------------
def setup_commands(client_instance):
    """
    Registers command handlers on client_instance.
    Handles commands both WITH slash (/lockon) and WITHOUT slash (lockon).
    Deduplicates commands so only one account replies.
    """
    
    async def should_skip(event, cmd_name: str = None):
        global TARGET_CHAT_ID
        if event.is_group or event.is_channel:
            if check_group_authorized(event.chat_id, getattr(event, 'chat', None)):
                return False

            # Unauthorized group!
            # Only log a security warning if an explicit command was attempted,
            # and rate-limit to at most 1 warning per chat per 60 seconds.
            if cmd_name:
                now = time.time()
                if unauthorized_command_log_cooldown.get(event.chat_id, 0) < now:
                    unauthorized_command_log_cooldown[event.chat_id] = now + 60.0
                    if len(unauthorized_command_log_cooldown) > 200:
                        unauthorized_command_log_cooldown.clear()
                        unauthorized_command_log_cooldown[event.chat_id] = now + 60.0
                    c_title = (getattr(getattr(event, 'chat', None), 'title', '') or '').strip()
                    logging.warning(f"[Security] Command '{cmd_name}' ignored in unauthorized group {event.chat_id} ('{c_title}')")

            # Normal ambient chatter in other groups: drop silently with 0 network calls and 0 log spam
            return True
        return False

    async def reply_safely(event, text):
        # Prevent double reply if both bot and user account see the same command
        msg_id = getattr(event, 'id', None)
        if msg_id and msg_id in processed_cmd_msg_ids:
            return
        if msg_id:
            processed_cmd_msg_ids.add(msg_id)
            if len(processed_cmd_msg_ids) > 200:
                processed_cmd_msg_ids.clear()
                processed_cmd_msg_ids.add(msg_id)
        try:
            await event.reply(text)
        except Exception as re:
            logging.warning(f"event.reply failed: {re}, attempting direct send fallback...")
            try:
                cl = clients.get("acc1", {}).get("client") or clients.get("acc4", {}).get("client")
                if cl and cl.is_connected():
                    target_peer = getattr(event, 'input_chat', None) or event.chat_id
                    await cl.send_message(target_peer, text)
            except Exception as fe:
                logging.error(f"Fallback reply also failed: {fe}")

    @client_instance.on(events.NewMessage(pattern=r'(?i)^[/.!]?(lockon|lockoff)(?:@genzetabot)?$'))
    async def lock_handler(event):
        cmd = event.pattern_match.group(1).lower()
        if await should_skip(event, cmd):
            return
        allowed, reason = await check_command_auth(event, cmd)
        if not allowed:
            if reason:
                await reply_safely(event, f"❌ {reason}")
            return
            
        global chat_task, bot_active, CHAT_PAUSED
        if cmd == "lockon":
            CHAT_PAUSED = False
            bot_active = True
            # Cancel any previous tasks immediately
            for t in list(active_chat_tasks):
                if not t.done():
                    t.cancel()
            active_chat_tasks.clear()
            if chat_task and not chat_task.done():
                chat_task.cancel()
            chat_task = asyncio.create_task(chat_loop())
            active_chat_tasks.add(chat_task)
            readable_del = format_seconds_to_readable(AUTO_DELETE_DELAY)
            await reply_safely(event, 
                "🚀 **Automation Locked On!**\n\n"
                f"• Target Group: `{TARGET_CHAT}`\n"
                f"• Speed: **{MESSAGE_DELAY:.1f}s**\n"
                f"• Auto-Delete: **{readable_del}**\n"
                f"• Active Day: 📅 **{active_day_name.capitalize()}** (`{CSV_FILE}`)"
            )
            logging.info(f"Automation LOCKED ON by sender {event.sender_id}")
            
        elif cmd == "lockoff":
            bot_active = False
            for t in list(active_chat_tasks):
                if not t.done():
                    t.cancel()
            active_chat_tasks.clear()
            if chat_task and not chat_task.done():
                chat_task.cancel()
                chat_task = None
            await reply_safely(event, "🛑 **Automation Locked Off.** Background chat sequence is stopped immediately.")
            logging.info(f"Automation LOCKED OFF by sender {event.sender_id}")

    @client_instance.on(events.NewMessage(pattern=r'(?i)^[/.!]?(setspeed|speed)(?:@genzetabot)?(?:\s+(.+))?$'))
    async def speed_handler(event):
        if await should_skip(event, "setspeed"):
            return
        allowed, reason = await check_command_auth(event, "setspeed")
        if not allowed:
            if reason:
                await reply_safely(event, f"❌ {reason}")
            return
            
        global MESSAGE_DELAY
        arg = event.pattern_match.group(2)
        if not arg:
            await reply_safely(event, f"ℹ️ Current speed is locked to **{MESSAGE_DELAY:.1f}s** per message.\nUsage: `/setspeed 5s`, `/setspeed 10s`, `/setspeed 1m`")
            return
        arg = arg.strip().lower()
        try:
            if arg.endswith('s'):
                val = float(arg[:-1])
            elif arg.endswith('m'):
                val = float(arg[:-1]) * 60
            elif arg.endswith('h'):
                val = float(arg[:-1]) * 3600
            else:
                val = float(arg)
            MESSAGE_DELAY = max(1.0, val)
            await reply_safely(event, f"⚡ **Speed Locked:** Automation speed updated to **{MESSAGE_DELAY:.1f}s** per message.")
            logging.info(f"Speed updated to {MESSAGE_DELAY}s by sender {event.sender_id}")
        except ValueError:
            await reply_safely(event, "❌ Invalid format. Use e.g. `setspeed 5s`, `setspeed 15s`, `setspeed 1m`.")

    @client_instance.on(events.NewMessage(pattern=r'(?i)^[/.!]?stats(?:@genzetabot)?$'))
    async def stats_handler(event):
        if await should_skip(event, "stats"):
            return
        allowed, _ = await check_command_auth(event, "stats")
        if not allowed:
            return
            
        is_running = (bot_active and chat_task is not None and not chat_task.done())
        status_str = "🟢 RUNNING" if is_running else "🔴 STOPPED"
        day_cap = active_day_name.capitalize()
        connected_accs = ", ".join([cfg["name"] for k, cfg in accounts.items() if k in clients])
        readable_del = format_seconds_to_readable(AUTO_DELETE_DELAY)
        
        await reply_safely(event, 
            f"📊 **GenZetaBot Operational Stats**\n\n"
            f"• Automation Status: {status_str}\n"
            f"• Chat Speed: **{MESSAGE_DELAY:.1f}s**\n"
            f"• Auto-Delete Delay: **{readable_del}** ({AUTO_DELETE_DELAY}s)\n"
            f"• Active Day: 📅 **{day_cap}** (`{CSV_FILE}`)\n"
            f"• Loaded Messages: {len(conversation_script):,} messages\n"
            f"• Total Messages Sent: {TOTAL_MESSAGES_SENT}\n"
            f"• Connected Workers: {connected_accs}\n"
            f"• Target Whitelist: `{TARGET_CHAT}`"
        )

    @client_instance.on(events.NewMessage(pattern=r'(?i)^[/.!]?setdelete(?:@genzetabot)?(?:\s+(.+))?$'))
    async def delete_handler(event):
        if await should_skip(event, "setdelete"):
            return
        allowed, reason = await check_command_auth(event, "setdelete")
        if not allowed:
            if reason:
                await reply_safely(event, f"❌ {reason}")
            return
            
        global AUTO_DELETE_DELAY
        arg = event.pattern_match.group(1)
        if not arg:
            readable_del = format_seconds_to_readable(AUTO_DELETE_DELAY)
            await reply_safely(event, f"ℹ️ Current auto-delete delay is **{readable_del}** ({AUTO_DELETE_DELAY}s).")
            return
        arg = arg.strip().lower()
        try:
            if arg.endswith('days') or arg.endswith('day'):
                num = arg.replace('days', '').replace('day', '').strip()
                val = int(num) * 86400
            elif arg.endswith('d'):
                val = int(arg[:-1]) * 86400
            elif arg.endswith('h'):
                val = int(arg[:-1]) * 3600
            elif arg.endswith('m'):
                val = int(arg[:-1]) * 60
            elif arg.endswith('s'):
                val = int(arg[:-1])
            else:
                val = int(arg)
            AUTO_DELETE_DELAY = max(0, val)
            readable = format_seconds_to_readable(AUTO_DELETE_DELAY)
            await reply_safely(event, f"🗑️ Auto-delete delay updated to **{readable}** ({AUTO_DELETE_DELAY}s).")
        except ValueError:
            await reply_safely(event, "❌ Invalid format. Use e.g. `setdelete 9d`, `setdelete 5m`, `setdelete 360s`.")

    @client_instance.on(events.NewMessage(pattern=r'(?i)^[/.!]?setday(?:@genzetabot)?(?:\s+(.+))?$'))
    async def setday_handler(event):
        if await should_skip(event, "setday"):
            return
        allowed, reason = await check_command_auth(event, "setday")
        if not allowed:
            if reason:
                await reply_safely(event, f"❌ {reason}")
            return
        arg = event.pattern_match.group(1)
        valid_days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        if not arg or arg.strip().lower() not in valid_days:
            await reply_safely(event, f"❌ Please specify a valid day: {', '.join(valid_days)}\nExample: `setday friday`")
            return
        target_day = arg.strip().lower()
        load_csv(target_day)
        await reply_safely(event, f"📅 **Active Day Switched to {target_day.capitalize()}!**\nLoaded `{CSV_FILE}` with {len(conversation_script)} messages.")

    @client_instance.on(events.NewMessage(pattern=r'(?i)^[/.!]?day(?:@genzetabot)?$'))
    async def day_handler(event):
        if await should_skip(event, "day"):
            return
        allowed, _ = await check_command_auth(event, "day")
        if not allowed:
            return
        await reply_safely(event, 
            f"📅 **Active Daily Dataset Info**\n\n"
            f"• Current Day: **{active_day_name.capitalize()}**\n"
            f"• Active CSV: `{CSV_FILE}`\n"
            f"• Loaded Messages: {len(conversation_script):,} messages"
        )

    @client_instance.on(events.NewMessage(pattern=r'(?i)^[/.!]?(pause|resume)(?:@genzetabot)?$'))
    async def pause_handler(event):
        cmd = event.pattern_match.group(1).lower()
        if await should_skip(event, cmd):
            return
        allowed, reason = await check_command_auth(event, cmd)
        if not allowed:
            if reason:
                await reply_safely(event, f"❌ {reason}")
            return
        global CHAT_PAUSED
        if cmd == "pause":
            CHAT_PAUSED = True
            await reply_safely(event, "⏸️ Chat automation is now **PAUSED**.")
        else:
            CHAT_PAUSED = False
            await reply_safely(event, "▶️ Chat automation is now **RESUMED**.")

    @client_instance.on(events.NewMessage(pattern=r'(?i)^[/.!]?resetgroup(?:@genzetabot)?$'))
    async def resetgroup_handler(event):
        if await should_skip(event, "resetgroup"):
            return
        allowed, reason = await check_command_auth(event, "resetgroup")
        if not allowed:
            if reason:
                await reply_safely(event, f"❌ {reason}")
            return
        global MESSAGE_DELAY, AUTO_DELETE_DELAY, CHAT_PAUSED
        MESSAGE_DELAY = 10
        AUTO_DELETE_DELAY = 360
        CHAT_PAUSED = False
        await reply_safely(event, "🔄 Settings reset to factory defaults (Speed: 10s, Delete: 360s).")

    @client_instance.on(events.NewMessage(pattern=r'(?i)^[/.!]?topic(?:@genzetabot)?(?:\s+(.+))?$'))
    async def topic_handler(event):
        if await should_skip(event, "topic"):
            return
        allowed, reason = await check_command_auth(event, "topic")
        if not allowed:
            if reason:
                await reply_safely(event, f"❌ {reason}")
            return
        global AI_TOPIC
        arg = event.pattern_match.group(1)
        if arg:
            AI_TOPIC = arg.strip()
            await reply_safely(event, f"💡 AI Topic set to: **{AI_TOPIC}**.")
        else:
            AI_TOPIC = None
            await reply_safely(event, "💡 AI Topic cleared.")

    @client_instance.on(events.NewMessage())
    async def auto_delete_group_handler(event):
        raw = (event.raw_text or "").strip().lower()
        if any(raw.startswith(cmd) for cmd in (
            "/lockon", "lockon", "!lockon", ".lockon",
            "/lockoff", "lockoff", "!lockoff", ".lockoff",
            "/setspeed", "setspeed", "/speed", "speed",
            "/stats", "stats", "/day", "day", "/setday", "setday",
            "/setdelete", "setdelete", "/pause", "pause", "/resume", "resume",
            "/resetgroup", "resetgroup", "/topic", "topic"
        )):
            return
        if await should_skip(event):
            return
        if not bot_active:
            return

        s_id = getattr(event, 'sender_id', None)
        if not s_id:
            msg = getattr(event, 'message', None)
            s_id = getattr(getattr(msg, 'from_id', None), 'user_id', None)

        # Ignore messages sent by our own connected accounts to prevent loops
        if s_id and s_id in OUR_USER_IDS:
            return

        msg_id = getattr(event, 'id', None)

        # 1. Schedule auto-deletion for human message
        if AUTO_DELETE_DELAY > 0 and event.message:
            asyncio.create_task(delete_other_message(event.message, AUTO_DELETE_DELAY))

        msg_text = (event.raw_text or "").strip()
        if not msg_text:
            return

        # 2. Check deduplication so only one bot account replies
        if msg_id and msg_id in processed_human_msg_ids:
            return
        if msg_id:
            processed_human_msg_ids.add(msg_id)
            if len(processed_human_msg_ids) > 200:
                processed_human_msg_ids.clear()
                processed_human_msg_ids.add(msg_id)

        # 3. Contextual Emoji Reaction (20% natural chance)
        if random.random() < 0.20:
            emoji = "👍"
            low_t = msg_text.lower()
            if any(w in low_t for w in ["lol", "lmao", "haha", "xd", "funny"]): emoji = "😂"
            elif any(w in low_t for w in ["love", "amazing", "best", "great", "cute", "op"]): emoji = "❤️"
            elif any(w in low_t for w in ["fire", "insane", "crazy", "goat", "lit"]): emoji = "🔥"
            elif any(w in low_t for w in ["sad", "cry", "rip", "bad", "loss"]): emoji = "😢"
            try:
                rx_client = clients.get("acc1", {}).get("client") or clients.get("acc4", {}).get("client")
                rx_ent = await get_client_entity("acc1") or await get_client_entity("acc4")
                if rx_client and rx_ent:
                    await rx_client(SendReactionRequest(
                        peer=rx_ent,
                        msg_id=event.message.id,
                        reaction=[ReactionEmoji(emoticon=emoji)]
                    ))
            except Exception:
                pass

        # 4. Dynamic AI Reply to Humans
        is_reply_to_us = False
        if event.message and event.message.is_reply:
            try:
                reply_msg = await event.message.get_reply_message()
                if reply_msg and reply_msg.sender_id in OUR_USER_IDS:
                    is_reply_to_us = True
            except Exception:
                pass

        bot_mentioned = ("@genzetabot" in msg_text.lower() or "genzeta" in msg_text.lower())
        has_question = ("?" in msg_text)
        casual_chance = (random.random() < 0.35)

        should_reply = is_reply_to_us or bot_mentioned or has_question or casual_chance

        if should_reply:
            responder_key = "acc4" if ("acc4" in clients and clients["acc4"]["client"].is_connected()) else "acc1"
            if responder_key in clients and clients[responder_key]["client"].is_connected():
                reply_text = await generate_ai_reply_to_human(msg_text)
                resp_client = clients[responder_key]["client"]
                resp_entity = await get_client_entity(responder_key) or event.chat_id
                await send_dynamic_reply(resp_client, resp_entity, event.message, reply_text)

# ---------------------------------------------------------------------------
# MAIN APPLICATION ENTRY POINT (PERSISTENT RECONNECT SUPERVISOR)
# ---------------------------------------------------------------------------
async def main():
    print("\n" + "="*50)
    print("   GENZETABOT - ROCK-SOLID CLASSIC EDITION")
    print("="*50)

    # 1. Start Cloud Web Server for Render
    await start_web_server()

    # 2. Load Active Daily CSV Dataset
    load_csv()

    # 3. Persistent Connection & Self-Healing Loop
    watchdog_started = False
    configured_clients = set()
    
    while True:
        try:
            # Connect User Accounts and Bot
            for acc_key, acc_data in accounts.items():
                session = acc_data.get("session")
                bot_token = acc_data.get("bot_token")
                api_id = acc_data["api_id"]
                api_hash = acc_data["api_hash"]

                if not session and not bot_token:
                    continue

                if acc_key in clients and clients[acc_key]["client"].is_connected():
                    continue

                try:
                    if bot_token and acc_key == "acc4":
                        client = TelegramClient(StringSession(), api_id, api_hash)
                        await client.start(bot_token=bot_token)
                    else:
                        client = TelegramClient(StringSession(session), api_id, api_hash)
                        await client.connect()

                    if await client.is_user_authorized():
                        clients[acc_key] = {"client": client, "name": acc_data["name"]}
                        logging.info(f"Connected {acc_data['name']} safely.")
                        try:
                            me = await client.get_me()
                            if me and me.id:
                                OUR_USER_IDS.add(me.id)
                        except Exception:
                            pass
                except Exception as ce:
                    logging.error(f"Failed to connect {acc_data['name']}: {ce}")

            if "acc4" in clients and clients["acc4"]["client"].is_connected():
                host_client = clients["acc4"]["client"]
                logging.info("Account 4 (Bot) online as primary command host.")
            elif "acc1" in clients and clients["acc1"]["client"].is_connected():
                host_client = clients["acc1"]["client"]
                logging.info("Account 1 online as primary command host (Acc4 fallback).")
            else:
                logging.error("No active host client (acc1 or acc4) available! Retrying in 10s...")
                await asyncio.sleep(10)
                continue

            # Resolve Target Chat Entity via Account 1 or Bot
            if "acc1" in clients and clients["acc1"]["client"].is_connected():
                acc1_client = clients["acc1"]["client"]
                target_resolved = False

                # Method A: Dialogs pre-fetch
                try:
                    dialogs = await asyncio.wait_for(acc1_client.get_dialogs(limit=30), timeout=8.0)
                    for d in dialogs:
                        if d.is_group or d.is_channel:
                            d_title = (getattr(d, 'title', '') or "").strip().lower()
                            if any(kw in d_title for kw in ["jamghat", "joker"]):
                                global TARGET_CHAT_ID
                                TARGET_CHAT_ID = utils.get_peer_id(d.entity)
                                ALLOWED_GROUP_IDS.add(TARGET_CHAT_ID)
                                ALLOWED_GROUP_IDS.add(d.entity.id)
                                logging.info(f"🎯 [Target Chat] Directly resolved from dialogs: '{d.title}' (ID: {TARGET_CHAT_ID})")
                                target_resolved = True
                                break
                except Exception as de:
                    logging.debug(f"Dialog pre-fetch warning: {de}")

                # Method B: Check invite hash 'Elgeiny2Lk81MzRl'
                if not target_resolved:
                    try:
                        from telethon.tl.functions.messages import CheckChatInviteRequest
                        c_res = await asyncio.wait_for(acc1_client(CheckChatInviteRequest("Elgeiny2Lk81MzRl")), timeout=8.0)
                        if hasattr(c_res, 'chat'):
                            TARGET_CHAT_ID = utils.get_peer_id(c_res.chat)
                            ALLOWED_GROUP_IDS.add(TARGET_CHAT_ID)
                            ALLOWED_GROUP_IDS.add(c_res.chat.id)
                            logging.info(f"🎯 [Target Chat] Resolved from invite link: '{getattr(c_res.chat, 'title', '')}' (ID: {TARGET_CHAT_ID})")
                            target_resolved = True
                    except Exception as ce:
                        logging.debug(f"Invite check fallback warning: {ce}")

                # Method C: Direct get_entity fallback
                if not target_resolved:
                    try:
                        entity = await acc1_client.get_entity(TARGET_CHAT)
                        TARGET_CHAT_ID = utils.get_peer_id(entity)
                        ALLOWED_GROUP_IDS.add(TARGET_CHAT_ID)
                        ALLOWED_GROUP_IDS.add(entity.id)
                        logging.info(f"Target chat resolved via get_entity to ID: {TARGET_CHAT_ID}")
                    except Exception as e:
                        logging.error(f"Failed to resolve TARGET_CHAT entity: {e}")

            # If acc4 is connected, resolve TARGET_CHAT directly (not via get_dialogs)
            if "acc4" in clients and clients["acc4"]["client"].is_connected():
                try:
                    bot_c = clients["acc4"]["client"]
                    target_ref = TARGET_CHAT_ID or TARGET_CHAT
                    if target_ref:
                        b_ent = await asyncio.wait_for(bot_c.get_entity(target_ref), timeout=5.0)
                        if b_ent:
                            cached_entities["acc4"] = b_ent
                            logging.info(f"🎯 [Bot Acc4] Pre-cached target group entity.")
                except Exception as be:
                    logging.debug(f"Bot entity resolve notice: {be}")

            # Pre-warm target group entity across ALL connected accounts (acc1, acc2, acc3, acc4)
            for acc_key in ("acc1", "acc2", "acc3", "acc4"):
                if acc_key in clients and clients[acc_key]["client"].is_connected():
                    await get_client_entity(acc_key)

            # Register command listeners on BOTH Bot and Acc1 once (strictly scoped to target group)
            if host_client not in configured_clients:
                setup_commands(host_client)
                configured_clients.add(host_client)
            if "acc1" in clients and clients["acc1"]["client"].is_connected() and clients["acc1"]["client"] not in configured_clients:
                setup_commands(clients["acc1"]["client"])
                configured_clients.add(clients["acc1"]["client"])

            logging.info("Command Controllers active on Bot (@genzetabot) and Account 1.")
            logging.info(f"Listening for lockon / lockoff commands strictly in {TARGET_CHAT}...")

            # Start Auto-Recovery Watchdog
            if not watchdog_started:
                asyncio.create_task(chat_loop_watchdog())
                watchdog_started = True

            # Keep all connected clients alive simultaneously
            connected_clients = [c["client"] for c in clients.values() if c.get("client") and c["client"].is_connected()]
            await asyncio.gather(*[c.run_until_disconnected() for c in connected_clients], return_exceptions=True)

        except Exception as e:
            logging.error(f"Telegram connection dropped or interrupted: {e}. Auto-reconnecting in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
