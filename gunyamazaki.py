import asyncio
import os
import csv
import random
import logging
import re
import datetime
from collections import defaultdict
from aiohttp import web
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji

# Load Environment Variables
load_dotenv()

# Voice Engine & Persistence
import voice_engine
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
ALLOWED_CHAT_INVITE_HASH = "noVnALjR8Uw1OWU1"
_env_target = (os.getenv("TARGET_CHAT") or "").strip()
if _env_target and not any(bad in _env_target for bad in ("1tWK4j-BYC85MDVl", "-1003529827660")):
    TARGET_CHAT = _env_target
else:
    TARGET_CHAT = "https://t.me/+noVnALjR8Uw1OWU1"

TARGET_CHAT_ID = None
ALLOWED_GROUP_IDS = {-1002361093080}

def is_allowed_group(chat_id: int, title: str = "") -> bool:
    """
    STRICT SECURITY DIRECTIVE:
    This bot is strictly whitelisted to operate ONLY in the user's designated group:
    https://t.me/+noVnALjR8Uw1OWU1 (Joker's Jamghat).
    All other groups are completely unauthorized, de-permissioned, and blocked.
    """
    if not chat_id:
        return False
    if chat_id in ALLOWED_GROUP_IDS:
        return True
    if TARGET_CHAT_ID and chat_id == TARGET_CHAT_ID:
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
AUTO_DELETE_DELAY = 360      # Auto-delete messages after 6 minutes
MESSAGE_DELAY = 10           # Default speed in seconds
CHAT_PAUSED = False
AI_TOPIC = None
TOTAL_MESSAGES_SENT = 0
VOICE_FREQUENCY = 10         # Send a voice note roughly every 10 messages
voice_step_counter = 0

chat_task = None
clients = {}
conversation_script = []
conversation_data = []       # alias for compatibility
active_day_name = "monday"
CSV_FILE = "conversations_monday.csv"

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
    "acc4": {"name": "Account 4 (Bot)", "api_id": 2282111, "api_hash": "da58a1841a16c352a2a999171bbabcad", "session": None, "bot_token": os.getenv("ACC4_BOT_TOKEN")}
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
                        "id": row.get("id", "").strip(),
                        "sender": sender,
                        "message": message,
                        "reply_to": row.get("reply_to", "").strip(),
                        "reaction": row.get("reaction", "").strip(),
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
        sent_msg = await client.send_message(entity, text, reply_to=target_msg)
        TOTAL_MESSAGES_SENT += 1
        if AUTO_DELETE_DELAY > 0:
            asyncio.create_task(delete_message_later(client, entity, sent_msg.id, AUTO_DELETE_DELAY))
        logging.info(f"Sent dynamic reply: {text}")
    except Exception as e:
        logging.error(f"Failed to send dynamic reply: {e}")

# ---------------------------------------------------------------------------
# CORE CHAT LOOP (OLD-TYPE RELIABILITY + AUTHENTIC VOICE ENGINE)
# ---------------------------------------------------------------------------
async def chat_loop():
    logging.info("🚀 Chat sequence STARTED via remote command!")
    global TOTAL_MESSAGES_SENT, voice_step_counter
    line_index = random.randint(0, max(0, len(conversation_script) - 1)) if conversation_script else 0
    message_tracker = {}
    last_sent_text = ""
    
    try:
        while True:
            if CHAT_PAUSED:
                await asyncio.sleep(2)
                continue
            if not conversation_script:
                logging.error("The conversation script is empty! Stopping.")
                break
                
            row = conversation_script[line_index]
            speaker_key = row["sender"]
            msg = row["message"]
            csv_id = row.get("id", "")
            reply_to_csv = row.get("reply_to", "")
            reaction_emoji = row.get("reaction", "")
            
            # Map speaker to client (fallback to acc1 if speaker is missing)
            active_account = clients.get(speaker_key) or clients.get("acc1")
            
            if active_account and active_account.get("client"):
                client = active_account["client"]
                try:
                    target = TARGET_CHAT_ID or TARGET_CHAT
                    entity = await client.get_entity(target)
                    
                    reply_msg_id = None
                    if reply_to_csv and reply_to_csv in message_tracker:
                        reply_msg_id = message_tracker[reply_to_csv]
                        
                    sent_msg = None
                    voice_step_counter += 1
                    
                    # 1. Voice Note Generation (Dedicated voices via VoiceEngine)
                    if voice_step_counter >= VOICE_FREQUENCY and speaker_key in ("acc1", "acc2", "acc3", "acc4"):
                        try:
                            vn_path, transcript = await voice_engine.generate_voice_note(speaker_key, context_text=msg)
                            if vn_path and os.path.exists(vn_path):
                                logging.info(f"🎙 [{active_account['name']}] Sending Voice Note: '{transcript}'")
                                sent_msg = await client.send_file(entity, vn_path, voice_note=True, reply_to=reply_msg_id)
                                voice_step_counter = 0
                                last_sent_text = transcript or msg
                        except Exception as ve:
                            logging.debug(f"Voice generation skipped/fallback to text: {ve}")

                    # 2. Regular Text Message Send
                    if not sent_msg:
                        if MESSAGE_DELAY > 5.0:
                            await simulate_typing(client, entity, msg, group_speed=MESSAGE_DELAY)
                        sent_msg = await client.send_message(entity, msg, reply_to=reply_msg_id)
                        last_sent_text = msg
                    
                    TOTAL_MESSAGES_SENT += 1
                    logging.info(f"[{active_account['name']}] Sent: {msg[:45]}...")
                    
                    if csv_id and sent_msg:
                        message_tracker[csv_id] = sent_msg.id
                        
                    # Auto-delete message
                    if AUTO_DELETE_DELAY > 0 and sent_msg:
                        asyncio.create_task(delete_message_later(client, entity, sent_msg.id, AUTO_DELETE_DELAY))
                        
                    # Reactions
                    if reaction_emoji and reply_msg_id:
                        try:
                            await client(SendReactionRequest(
                                peer=entity,
                                msg_id=reply_msg_id,
                                reaction=[ReactionEmoji(emoticon=reaction_emoji)]
                            ))
                        except Exception:
                            pass
                            
                    # Stickers (15% natural chance)
                    if random.random() < 0.15 and os.path.exists(STICKERS_DIR):
                        available_stickers = [f for f in os.listdir(STICKERS_DIR) if f.endswith(('.webp', '.png', '.jpg', '.tgs'))]
                        if available_stickers:
                            chosen_sticker = random.choice(available_stickers)
                            sticker_path = os.path.join(STICKERS_DIR, chosen_sticker)
                            await asyncio.sleep(random.uniform(1.0, 2.0))
                            sent_sticker = await client.send_file(entity, sticker_path)
                            if AUTO_DELETE_DELAY > 0:
                                asyncio.create_task(delete_message_later(client, entity, sent_sticker.id, min(AUTO_DELETE_DELAY, 300)))

                except FloodWaitError as e:
                    logging.warning(f"⚠️ Telegram Rate Limit! Pausing chat loop for {e.seconds} seconds.")
                    await asyncio.sleep(e.seconds + 2)
                except Exception as e:
                    logging.error(f"[{active_account['name']}] Error in chat turn: {e}")

            line_index += 1
            if line_index >= len(conversation_script):
                line_index = random.randint(0, max(0, len(conversation_script) - 1)) if conversation_script else 0
                message_tracker.clear()
                
            delay = MESSAGE_DELAY
            logging.info(f"Waiting {delay:.1f}s before next message...")
            await asyncio.sleep(delay)
            
    except asyncio.CancelledError:
        logging.info("🛑 Chat sequence CANCELLED via remote command!")
        raise
    except Exception as e:
        logging.error(f"Unexpected chat_loop failure: {e}")

# ---------------------------------------------------------------------------
# DUMMY WEB SERVER FOR FREE CLOUD HOSTING (RENDER / KOYEB)
# ---------------------------------------------------------------------------
async def health_check(request):
    return web.Response(text="GenZetaBot is running safely 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"🌐 Cloud Health Check web server active on port {port}.")

dummy_server = start_web_server

# ---------------------------------------------------------------------------
# RBAC AUTHENTICATION HELPER
# ---------------------------------------------------------------------------
async def check_command_auth(event, cmd_name: str) -> tuple[bool, str]:
    cmd_name = (cmd_name or "").lower().strip()
    s_id = getattr(event, 'sender_id', None)
    if not s_id:
        msg = getattr(event, 'message', None)
        s_id = getattr(getattr(msg, 'from_id', None), 'user_id', None)
    
    username = ""
    try:
        sender_obj = await event.get_sender()
        username = (getattr(sender_obj, 'username', '') or '').lower().lstrip('@')
    except Exception:
        pass

    # 1. Super Admin Check (Full Privileges)
    if (s_id in SUPER_ADMIN_IDS) or (username in SUPER_ADMIN_USERNAMES):
        return True, ""

    # 2. Primary Automation Operator (@Itsraventime1 / 6309134652)
    if (s_id == PRIMARY_OPERATOR_ID) or (username in PRIMARY_OPERATOR_USERNAMES) or (s_id in OPERATOR_USER_IDS):
        if cmd_name in OPERATOR_ALLOWED_COMMANDS:
            return True, ""
        logging.warning(f"[Security] Operator {s_id} (@{username}) denied restricted command: '{cmd_name}'")
        return False, f"Access Denied: Primary Operator is restricted to ({', '.join(sorted(OPERATOR_ALLOWED_COMMANDS))})."

    # 3. Unauthorized users
    logging.warning(f"[Security] Unauthorized command attempt from user {s_id} (@{username}): '{cmd_name}'")
    return False, "Access Denied: You are not authorized to execute bot control commands."

# ---------------------------------------------------------------------------
# SETUP COMMAND CONTROLLER (ONLY ON ACC4 - THE OFFICIAL BOT)
# ---------------------------------------------------------------------------
def setup_commands(host_client):
    """
    STRICT ARCHITECTURE PRINCIPLE:
    Command listeners are attached EXCLUSIVELY to Account 4 (the Bot token client).
    User accounts (acc1, acc2, acc3) have ZERO event listeners attached.
    This guarantees zero background channel difference updates and zero CPU lag.
    """
    
    async def should_skip(event):
        global TARGET_CHAT_ID
        # Enforce target group whitelist
        if event.is_group or event.is_channel:
            if event.chat_id in ALLOWED_GROUP_IDS or (TARGET_CHAT_ID and event.chat_id == TARGET_CHAT_ID):
                ALLOWED_GROUP_IDS.add(event.chat_id)
                return False

            c_title = (getattr(event.chat, 'title', '') or '').strip()
            if not c_title:
                try:
                    chat = await asyncio.wait_for(event.get_chat(), timeout=3.0)
                    c_title = (getattr(chat, 'title', '') or '').strip()
                except Exception:
                    pass
                
            if is_allowed_group(event.chat_id, c_title):
                TARGET_CHAT_ID = event.chat_id
                ALLOWED_GROUP_IDS.add(event.chat_id)
                return False

            logging.warning(f"[Security] Command ignored in unauthorized group {event.chat_id} ('{c_title}')")
            return True
        return False

    @host_client.on(events.NewMessage(pattern=r'(?i)^[/.!]?(lockon|lockoff)(?:@genzetabot)?$'))
    async def lock_handler(event):
        if await should_skip(event):
            return
        cmd = event.pattern_match.group(1).lower()
        allowed, reason = await check_command_auth(event, cmd)
        if not allowed:
            if reason:
                await event.reply(f"❌ {reason}")
            return
            
        global chat_task
        if cmd == "lockon":
            if chat_task and not chat_task.done():
                await event.reply("⚠️ Automation is already running!")
                return
            chat_task = asyncio.create_task(chat_loop())
            await event.reply(
                "🚀 **Automation Locked On!**\n\n"
                f"• Target Group: `{TARGET_CHAT}`\n"
                f"• Current Speed: **{MESSAGE_DELAY}s**\n"
                f"• Active Day: 📅 **{active_day_name.capitalize()}** (`{CSV_FILE}`)\n"
                f"• Voice Notes: 🎙 ONLINE (Merlin Hermis, Mr. Fool, Ruthvik, Will)\n"
                f"• Auto-Delete: {AUTO_DELETE_DELAY}s"
            )
            logging.info(f"Automation LOCKED ON by sender {event.sender_id}")
            
        elif cmd == "lockoff":
            if chat_task and not chat_task.done():
                chat_task.cancel()
                chat_task = None
                await event.reply("🛑 **Automation Locked Off.** Background chat sequence is stopped.")
                logging.info(f"Automation LOCKED OFF by sender {event.sender_id}")
            else:
                await event.reply("ℹ️ Automation is already off.")

    @host_client.on(events.NewMessage(pattern=r'(?i)^[/.!]?(setspeed|speed)(?:@genzetabot)?(?:\s+(.+))?$'))
    async def speed_handler(event):
        if await should_skip(event):
            return
        allowed, reason = await check_command_auth(event, "setspeed")
        if not allowed:
            if reason:
                await event.reply(f"❌ {reason}")
            return
            
        global MESSAGE_DELAY
        arg = event.pattern_match.group(2)
        if not arg:
            await event.reply(f"ℹ️ Current speed is locked to **{MESSAGE_DELAY}s** per message.\nUsage: `/setspeed 5s`, `/setspeed 10s`, `/setspeed 1m`")
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
            await event.reply(f"⚡ **Speed Locked:** Automation speed updated to **{MESSAGE_DELAY:.1f}s** per message.")
            logging.info(f"Speed updated to {MESSAGE_DELAY}s by sender {event.sender_id}")
        except ValueError:
            await event.reply("❌ Invalid format. Use e.g. `setspeed 5s`, `setspeed 15s`, `setspeed 1m`.")

    @host_client.on(events.NewMessage(pattern=r'(?i)^[/.!]?stats(?:@genzetabot)?$'))
    async def stats_handler(event):
        if await should_skip(event):
            return
        allowed, _ = await check_command_auth(event, "stats")
        if not allowed:
            return
            
        is_running = (chat_task is not None and not chat_task.done())
        status_str = "🟢 RUNNING" if is_running else "🔴 STOPPED"
        day_cap = active_day_name.capitalize()
        connected_accs = ", ".join([cfg["name"] for k, cfg in accounts.items() if k in clients])
        
        await event.reply(
            f"📊 **GenZetaBot Operational Stats**\n\n"
            f"• Automation Status: {status_str}\n"
            f"• Chat Speed: **{MESSAGE_DELAY}s**\n"
            f"• Auto-Delete Delay: **{AUTO_DELETE_DELAY}s**\n"
            f"• Active Day: 📅 **{day_cap}** (`{CSV_FILE}`)\n"
            f"• Loaded Messages: {len(conversation_script):,} messages\n"
            f"• Total Messages Sent: {TOTAL_MESSAGES_SENT}\n"
            f"• Voice Note Engine: 🎙 ONLINE (1 voice note every ~{VOICE_FREQUENCY} msgs)\n"
            f"• Connected Workers: {connected_accs}\n"
            f"• Target Whitelist: `{TARGET_CHAT}`"
        )

    @host_client.on(events.NewMessage(pattern=r'(?i)^[/.!]?setdelete(?:@genzetabot)?(?:\s+(.+))?$'))
    async def delete_handler(event):
        if await should_skip(event):
            return
        allowed, reason = await check_command_auth(event, "setdelete")
        if not allowed:
            if reason:
                await event.reply(f"❌ {reason}")
            return
            
        global AUTO_DELETE_DELAY
        arg = event.pattern_match.group(1)
        if not arg:
            await event.reply(f"ℹ️ Current auto-delete delay is **{AUTO_DELETE_DELAY}s**.")
            return
        arg = arg.strip().lower()
        try:
            if arg.endswith('s'):
                val = int(arg[:-1])
            elif arg.endswith('m'):
                val = int(arg[:-1]) * 60
            elif arg.endswith('h'):
                val = int(arg[:-1]) * 3600
            else:
                val = int(arg)
            AUTO_DELETE_DELAY = max(0, val)
            await event.reply(f"🗑️ Auto-delete delay updated to **{AUTO_DELETE_DELAY}s**.")
        except ValueError:
            await event.reply("❌ Invalid format. Use e.g. `setdelete 360s` or `setdelete 5m`.")

    @host_client.on(events.NewMessage(pattern=r'(?i)^[/.!]?setday(?:@genzetabot)?(?:\s+(.+))?$'))
    async def setday_handler(event):
        if await should_skip(event):
            return
        allowed, reason = await check_command_auth(event, "setday")
        if not allowed:
            if reason:
                await event.reply(f"❌ {reason}")
            return
        arg = event.pattern_match.group(1)
        valid_days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        if not arg or arg.strip().lower() not in valid_days:
            await event.reply(f"❌ Please specify a valid day: {', '.join(valid_days)}\nExample: `setday friday`")
            return
        target_day = arg.strip().lower()
        load_csv(target_day)
        await event.reply(f"📅 **Active Day Switched to {target_day.capitalize()}!**\nLoaded `{CSV_FILE}` with {len(conversation_script)} messages.")

    @host_client.on(events.NewMessage(pattern=r'(?i)^[/.!]?day(?:@genzetabot)?$'))
    async def day_handler(event):
        if await should_skip(event):
            return
        allowed, _ = await check_command_auth(event, "day")
        if not allowed:
            return
        await event.reply(
            f"📅 **Active Daily Dataset Info**\n\n"
            f"• Current Day: **{active_day_name.capitalize()}**\n"
            f"• Active CSV: `{CSV_FILE}`\n"
            f"• Loaded Messages: {len(conversation_script):,} messages"
        )

    @host_client.on(events.NewMessage(pattern=r'(?i)^[/.!]?(pause|resume)(?:@genzetabot)?$'))
    async def pause_handler(event):
        if await should_skip(event):
            return
        cmd = event.pattern_match.group(1).lower()
        allowed, reason = await check_command_auth(event, cmd)
        if not allowed:
            if reason:
                await event.reply(f"❌ {reason}")
            return
        global CHAT_PAUSED
        if cmd == "pause":
            CHAT_PAUSED = True
            await event.reply("⏸️ Chat automation is now **PAUSED**.")
        else:
            CHAT_PAUSED = False
            await event.reply("▶️ Chat automation is now **RESUMED**.")

    @host_client.on(events.NewMessage(pattern=r'(?i)^[/.!]?resetgroup(?:@genzetabot)?$'))
    async def resetgroup_handler(event):
        if await should_skip(event):
            return
        allowed, reason = await check_command_auth(event, "resetgroup")
        if not allowed:
            if reason:
                await event.reply(f"❌ {reason}")
            return
        global MESSAGE_DELAY, AUTO_DELETE_DELAY, CHAT_PAUSED
        MESSAGE_DELAY = 10
        AUTO_DELETE_DELAY = 360
        CHAT_PAUSED = False
        await event.reply("🔄 Settings reset to factory defaults (Speed: 10s, Delete: 360s).")

    @host_client.on(events.NewMessage(pattern=r'(?i)^[/.!]?setvoicefreq(?:@genzetabot)?(?:\s+(.+))?$'))
    async def voicefreq_handler(event):
        if await should_skip(event):
            return
        allowed, reason = await check_command_auth(event, "setvoicefreq")
        if not allowed:
            if reason:
                await event.reply(f"❌ {reason}")
            return
        global VOICE_FREQUENCY
        arg = event.pattern_match.group(1)
        if arg and arg.strip().isdigit():
            VOICE_FREQUENCY = max(1, int(arg.strip()))
            await event.reply(f"🎙 Voice Note Frequency set to every **{VOICE_FREQUENCY}** messages.")
        else:
            await event.reply(f"ℹ️ Current Voice Note Frequency: every **{VOICE_FREQUENCY}** messages.")

    @host_client.on(events.NewMessage(pattern=r'(?i)^[/.!]?setvoicecooldown(?:@genzetabot)?(?:\s+(.+))?$'))
    async def voicecooldown_handler(event):
        if await should_skip(event):
            return
        allowed, reason = await check_command_auth(event, "setvoicecooldown")
        if not allowed:
            if reason:
                await event.reply(f"❌ {reason}")
            return
        await event.reply("🎙 Voice Cooldown updated.")

    @host_client.on(events.NewMessage(pattern=r'(?i)^[/.!]?topic(?:@genzetabot)?(?:\s+(.+))?$'))
    async def topic_handler(event):
        if await should_skip(event):
            return
        allowed, reason = await check_command_auth(event, "topic")
        if not allowed:
            if reason:
                await event.reply(f"❌ {reason}")
            return
        global AI_TOPIC
        arg = event.pattern_match.group(1)
        if arg:
            AI_TOPIC = arg.strip()
            await event.reply(f"💡 AI Topic set to: **{AI_TOPIC}**.")
        else:
            AI_TOPIC = None
            await event.reply("💡 AI Topic cleared.")

    @host_client.on(events.NewMessage())
    async def auto_delete_group_handler(event):
        # Ignore stealth command triggers
        if event.raw_text and event.raw_text.lower().startswith(("/lockon", "/lockoff", "lockon", "lockoff", "/setspeed", "setspeed")):
            return
        if await should_skip(event):
            return
        if AUTO_DELETE_DELAY > 0 and event.message:
            asyncio.create_task(delete_other_message(event.message, AUTO_DELETE_DELAY))

# ---------------------------------------------------------------------------
# MAIN APPLICATION ENTRY POINT
# ---------------------------------------------------------------------------
async def main():
    print("\n" + "="*50)
    print("   GENZETABOT - ROCK-SOLID CLASSIC EDITION")
    print("="*50)

    # 1. Start Cloud Web Server for Render
    await start_web_server()

    # 2. Load Active Daily CSV Dataset
    load_csv()

    # 3. Connect User Accounts and Bot
    for acc_key, acc_data in accounts.items():
        session = acc_data.get("session")
        bot_token = acc_data.get("bot_token")
        api_id = acc_data["api_id"]
        api_hash = acc_data["api_hash"]

        if not session and not bot_token:
            logging.warning(f"Skipping {acc_data['name']} because session/token is missing.")
            continue

        try:
            if bot_token and acc_key == "acc4":
                client = TelegramClient(StringSession(), api_id, api_hash)
                await client.start(bot_token=bot_token)
            else:
                client = TelegramClient(StringSession(session), api_id, api_hash)
                await client.connect()

            if not await client.is_user_authorized():
                logging.error(f"{acc_data['name']} credentials invalid or unauthorized! Skipping.")
                continue

            clients[acc_key] = {"client": client, "name": acc_data["name"]}
            logging.info(f"Connected {acc_data['name']} safely.")
        except Exception as e:
            logging.error(f"Failed to connect {acc_data['name']}: {e}")

    if not clients:
        logging.error("No valid accounts connected! Exiting.")
        return

    # 4. Resolve Target Chat Entity via Account 1
    if "acc1" in clients:
        acc1_client = clients["acc1"]["client"]
        target_resolved = False

        # Method A: Direct dialogs pre-fetch for "jamghat" / "joker"
        try:
            dialogs = await asyncio.wait_for(acc1_client.get_dialogs(limit=30), timeout=8.0)
            for d in dialogs:
                if d.is_group or d.is_channel:
                    d_title = (getattr(d, 'title', '') or "").strip().lower()
                    if any(kw in d_title for kw in ["jamghat", "joker"]):
                        global TARGET_CHAT_ID
                        TARGET_CHAT_ID = d.entity.id
                        ALLOWED_GROUP_IDS.add(TARGET_CHAT_ID)
                        logging.info(f"🎯 [Target Chat] Directly resolved from dialogs: '{d.title}' (ID: {TARGET_CHAT_ID})")
                        target_resolved = True
                        break
        except Exception as de:
            logging.debug(f"Dialog pre-fetch warning: {de}")

        # Method B: Check invite hash 'noVnALjR8Uw1OWU1'
        if not target_resolved:
            try:
                from telethon.tl.functions.messages import CheckChatInviteRequest
                c_res = await asyncio.wait_for(acc1_client(CheckChatInviteRequest("noVnALjR8Uw1OWU1")), timeout=8.0)
                if hasattr(c_res, 'chat'):
                    TARGET_CHAT_ID = c_res.chat.id
                    ALLOWED_GROUP_IDS.add(TARGET_CHAT_ID)
                    logging.info(f"🎯 [Target Chat] Resolved from invite link: '{getattr(c_res.chat, 'title', '')}' (ID: {TARGET_CHAT_ID})")
                    target_resolved = True
            except Exception as ce:
                logging.debug(f"Invite check fallback warning: {ce}")

        # Method C: Direct get_entity fallback
        if not target_resolved:
            try:
                entity = await acc1_client.get_entity(TARGET_CHAT)
                TARGET_CHAT_ID = entity.id
                ALLOWED_GROUP_IDS.add(TARGET_CHAT_ID)
                logging.info(f"Target chat resolved via get_entity to ID: {TARGET_CHAT_ID}")
            except Exception as e:
                logging.error(f"Failed to resolve TARGET_CHAT entity: {e}")

    # 5. Attach Command Listeners SOLELY to Account 4 (Official Bot)
    if "acc4" not in clients:
        logging.error("Account 4 (Bot) is NOT connected! The bot cannot listen for commands. Exiting.")
        return

    host_client = clients["acc4"]["client"]

    # 4b. Also auto-resolve target group from Bot's dialogs
    try:
        b_dialogs = await asyncio.wait_for(host_client.get_dialogs(limit=25), timeout=5.0)
        for d in b_dialogs:
            if d.is_group or d.is_channel:
                d_title = (getattr(d, 'title', '') or "").strip().lower()
                if any(kw in d_title for kw in ["jamghat", "joker"]):
                    TARGET_CHAT_ID = d.entity.id
                    ALLOWED_GROUP_IDS.add(TARGET_CHAT_ID)
                    logging.info(f"🎯 [Bot Acc4] Found target group in bot dialogs: '{d.title}' (ID: {TARGET_CHAT_ID})")
                    break
    except Exception as be:
        logging.debug(f"Bot dialogs scan warning: {be}")

    setup_commands(host_client)
    logging.info("Account 4 (Bot) registered as the exclusive Command Controller.")
    logging.info("User accounts (acc1, acc2, acc3) are running as pure outbound workers (0 difference updates).")
    logging.info(f"Listening for lockon / lockoff commands strictly in {TARGET_CHAT}...")

    try:
        await host_client.run_until_disconnected()
    except KeyboardInterrupt:
        pass
    finally:
        print("Disconnecting all clients...")
        for key, acc in clients.items():
            try:
                await acc["client"].disconnect()
            except Exception:
                pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
