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
from PIL import Image
from aiohttp import web
from dotenv import load_dotenv
from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji, InputMediaPoll, Poll, PollAnswer, InputMediaDice

# Load environment variables FIRST
load_dotenv()
from dynamic_intel import fetch_seasonal_anime, detect_language_mode, get_account4_system_prompt
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
    logging.info("Gemini AI Client initialized successfully for Auto-Catcher.")
except Exception as ge:
    logging.warning(f"Could not initialize Gemini AI: {ge}")

# Data loading
CSV_FILE = "anime_group_chat_10000.csv"
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

def load_csv():
    global conversation_data
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, CSV_FILE)
    conversation_data.clear()
    if os.path.exists(csv_path):
        with open(csv_path, mode="r", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            for row in reader:
                conversation_data.append(row)
        logging.info(f"Loaded {len(conversation_data)} messages from {CSV_FILE}.")
    else:
        logging.error(f"{CSV_FILE} not found in the directory.")

# Global state
bot_active = False
message_speed = 15
delete_delay = int(os.getenv("DELETE_DELAY", 900))  # Default 15 minutes (changeable anytime by User 1 via /setdelete)
total_messages_sent = 0
clients = {}
OUR_USER_IDS = {5429173364}
STATE_MSG_ID = None
current_csv_index = 0

async def load_state_from_telegram():
    global STATE_MSG_ID, current_csv_index, delete_delay, message_speed
    try:
        acc1 = clients["acc1"]["client"]
        async for msg in acc1.iter_messages("me", search="[GunYamazaki State]"):
            if "[GunYamazaki State]" in msg.text:
                STATE_MSG_ID = msg.id
                try:
                    parts = msg.text.split()
                    for p in parts:
                        if p.startswith("csv_index="):
                            current_csv_index = int(p.split("=")[1])
                        elif p.startswith("delete_delay="):
                            delete_delay = int(p.split("=")[1])
                            logging.info(f"Restored delete_delay from Telegram: {delete_delay}s ({format_seconds_to_readable(delete_delay)})")
                        elif p.startswith("message_speed="):
                            message_speed = int(p.split("=")[1])
                            logging.info(f"Restored message_speed from Telegram: {message_speed}s")
                    return current_csv_index
                except: pass
                break
    except Exception as e:
        logging.error(f"Failed to load state from telegram: {e}")
    return 0

async def save_state_to_telegram(csv_idx=None):
    global STATE_MSG_ID, current_csv_index
    if csv_idx is not None:
        current_csv_index = csv_idx
    try:
        acc1 = clients["acc1"]["client"]
        text = f"[GunYamazaki State] csv_index={current_csv_index} delete_delay={delete_delay} message_speed={message_speed}"
        if STATE_MSG_ID:
            await acc1.edit_message("me", STATE_MSG_ID, text)
        else:
            msg = await acc1.send_message("me", text)
            STATE_MSG_ID = msg.id
    except Exception as e:
        logging.error(f"Failed to save state to telegram: {e}")

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

async def simulate_typing(client, entity, text):
    if message_speed <= 1:
        return
    max_type = min(max(message_speed * 0.3, 0.5), 3.0)
    typing_time = min(max(len(text) * 0.03, 0.5), max_type)
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
            try:
                res = await gemini_client.aio.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=[img, prompt]
                )
            except Exception as aio_err:
                logging.warning(f"[Auto-Catcher] Async Gemini Vision failed ({aio_err}). Trying sync call...")
                res = gemini_client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=[img, prompt]
                )
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

    def should_skip():
        # If registered on Account 1 fallback, but Account 4 is connected, yield to Account 4
        return not is_acc4 and "acc4" in clients

    def is_admin(event):
        try:
            s_id = getattr(event, 'sender_id', None)
            if not s_id:
                s = getattr(event, 'message', None)
                s_id = getattr(getattr(s, 'from_id', None), 'user_id', None)
            if s_id == accounts["acc1"]["user_id"]:
                return True
            if event.is_private and (event.chat_id == accounts["acc1"]["user_id"] or event.chat_id == "me"):
                return True
        except: pass
        return False

    @bot_client.on(events.NewMessage(pattern='(?i)^/stats(?:@genzetabot)?$'))
    async def stats_handler(event):
        if should_skip(): return
        try:
            if is_admin(event):
                status = "🟢 ONLINE" if bot_active else "🔴 OFFLINE"
                del_str = format_seconds_to_readable(delete_delay)
                catch_target = f"{SPAWN_CHAT_TITLE} (`{SPAWN_CHAT_ID}`)" if SPAWN_CHAT_ID else (SPAWN_CHAT_TITLE or "Not Set")
                catch_status = f"🟢 ONLINE (Gemini AI Vision | Chat: {catch_target})" if arise_autocatch_active else "🔴 OFFLINE"
                await event.reply(f"📊 **GunYamazaki Stats**\n\nStatus: {status}\nSpeed: {message_speed}s\nAuto-Delete: {del_str}\nAuto-Catch: {catch_status}\nMessages Sent: {total_messages_sent}")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/ariseon(?:@genzetabot)?$'))
    async def ariseon_handler(event):
        if should_skip(): return
        global arise_autocatch_active
        try:
            if is_admin(event):
                arise_autocatch_active = True
                await event.reply(f"✅ Arise Auto-Catcher is now **ONLINE**!\nLocked strictly to: **{SPAWN_CHAT_TITLE}** (`{SPAWN_CHAT_ID}`)")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/ariseoff(?:@genzetabot)?$'))
    async def ariseoff_handler(event):
        if should_skip(): return
        global arise_autocatch_active
        try:
            if is_admin(event):
                arise_autocatch_active = False
                await event.reply("🛑 Arise Auto-Catcher is now **OFFLINE**.")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/(?:arisehere|lockarise)(?:@genzetabot)?$'))
    async def arisehere_handler(event):
        if should_skip(): return
        global SPAWN_CHAT_ID, SPAWN_CHAT_TITLE, arise_autocatch_active
        try:
            if is_admin(event):
                SPAWN_CHAT_ID = event.chat_id
                arise_autocatch_active = True
                try:
                    chat = await event.get_chat()
                    SPAWN_CHAT_TITLE = getattr(chat, 'title', 'Current Group')
                except: pass
                await event.reply(
                    f"🎯 **Arise Auto-Catcher LOCKED!**\n\n"
                    f"Group: **{SPAWN_CHAT_TITLE}** (`{SPAWN_CHAT_ID}`)\n"
                    f"Status: 🟢 **ONLINE**\n\n"
                    f"The bot will **ONLY** catch character gates inside this group and ignore all other groups!"
                )
                logging.info(f"Arise Auto-Catcher strictly locked to chat {SPAWN_CHAT_ID} ('{SPAWN_CHAT_TITLE}')")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/lockon(?:@genzetabot)?$'))
    async def lockon_handler(event):
        if should_skip(): return
        global bot_active, BOT_ENTITY, TARGET_CHAT_ID, SPAWN_CHAT_ID, SPAWN_CHAT_TITLE
        try:
            if is_admin(event):
                BOT_ENTITY = event.input_chat
                TARGET_CHAT_ID = event.chat_id
                SPAWN_CHAT_ID = event.chat_id
                try:
                    chat = await event.get_chat()
                    SPAWN_CHAT_TITLE = getattr(chat, 'title', 'Current Group')
                except: pass
                bot_active = True
                await event.reply(
                    f"✅ **GunYamazaki System & Auto-Catcher LOCKED ON!**\n\n"
                    f"Target Group: **{SPAWN_CHAT_TITLE}** (`{TARGET_CHAT_ID}`)\n"
                    f"Auto-Catch: 🟢 **ONLINE** (Strictly this group only)\n"
                    f"Conversation Loop: 🟢 **STARTED**"
                )
                logging.info(f"System & Arise Auto-Catcher LOCKED ON to {TARGET_CHAT_ID} ('{SPAWN_CHAT_TITLE}') by admin.")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/lockoff(?:@genzetabot)?$'))
    async def lockoff_handler(event):
        if should_skip(): return
        global bot_active
        try:
            if is_admin(event):
                bot_active = False
                await event.reply("🛑 GunYamazaki System Locked Off. Stopping conversation loop...")
                logging.info("System LOCKED OFF by admin.")
        except: pass

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/(?:setspeed|speed)(?:@genzetabot)?(?:\s+(.+))?$'))
    async def setspeed_handler(event):
        if should_skip(): return
        if not is_acc4 and event.is_private: return
        global message_speed
        try:
            if is_admin(event):
                arg = event.pattern_match.group(1)
                if not arg or not arg.strip():
                    await event.reply(
                        f"⚡ **Global Conversation Speed:** 1 message every **{message_speed}s**.\n\n"
                        f"All accounts (**Account 1, Account 2, Account 3**) follow this speed.\n"
                        f"To change, send: `/setspeed 5s`, `/setspeed 10s`, `/setspeed 15s`, or `/setspeed 30s`."
                    )
                    return
                speed_val = parse_time_to_seconds(arg.strip())
                if speed_val is not None and speed_val > 0:
                    message_speed = int(speed_val)
                    await save_state_to_telegram()
                    await event.reply(
                        f"⚡ **Speed Updated for ALL Accounts!**\n\n"
                        f"Every account (**Account 1, Account 2, Account 3**) will now send 1 message every **{message_speed} seconds**."
                    )
                else:
                    await event.reply("❌ Invalid speed! Example: `/setspeed 5s`, `/setspeed 10s`, or `/setspeed 15s`.")
        except Exception as e:
            logging.error(f"Error in setspeed_handler: {e}")

    @bot_client.on(events.NewMessage(pattern=r'(?i)^/(?:setdelete|autodelete|setdel|delete)(?:@genzetabot)?(?:\s+(.+))?$'))
    async def setdelete_handler(event):
        if should_skip(): return
        if not is_acc4 and event.is_private: return
        global delete_delay
        try:
            if is_admin(event):
                arg = event.pattern_match.group(1)
                if not arg or not arg.strip():
                    readable = format_seconds_to_readable(delete_delay)
                    await event.reply(
                        f"🗑 **Current Auto-Delete:** **{readable}** ({delete_delay}s)\n\n"
                        f"User 1 can set this to any duration anytime:\n"
                        f"• `/setdelete 15m` (15 minutes)\n"
                        f"• `/setdelete 1h` (1 hour)\n"
                        f"• `/setdelete 12h` (12 hours)\n"
                        f"• `/setdelete 1d` (1 day)\n"
                        f"• `/setdelete 7days` (7 days)\n"
                        f"• `/setdelete 0` (disable auto-delete)"
                    )
                    return
                raw_val = arg.strip()
                del_val = parse_time_to_seconds(raw_val)
                if del_val is not None:
                    delete_delay = del_val
                    readable = format_seconds_to_readable(delete_delay)
                    await save_state_to_telegram()
                    await event.reply(f"🗑 Auto-delete set to **{readable}** ({delete_delay}s) by User 1! Starting sweep...")
                    try:
                        sweep_client = bot_client if bot_client.is_connected() else clients.get("acc1", {}).get("client")
                        target = TARGET_CHAT_ID or TARGET_CHAT
                        if isinstance(target, str) and (target.startswith("-100") or target.lstrip('-').isdigit()):
                            target = int(target)
                        entity = await sweep_client.get_entity(target)
                        asyncio.create_task(history_sweeper(sweep_client, entity, delete_delay))
                    except: pass
                else:
                    await event.reply("❌ Invalid time format! You can use: `/setdelete 15m`, `/setdelete 1h`, `/setdelete 1d`, `/setdelete 7days`, `/setdelete 30s`, or `/setdelete 0`.")
        except Exception as e:
            logging.error(f"Error in setdelete_handler: {e}")

    @bot_client.on(events.NewMessage())
    async def auto_delete_handler(event):
        if should_skip(): return
        global BOT_ENTITY
        if not event.is_group and not event.is_channel:
            return
        if TARGET_CHAT_ID and isinstance(TARGET_CHAT_ID, int) and event.chat_id != TARGET_CHAT_ID:
            return
        BOT_ENTITY = event.input_chat
        if event.raw_text and event.raw_text.lower().startswith(("/lockon", "/lockoff", "/setdelete", "/autodelete", "/setdel", "/delete", "/setspeed", "/speed", "/stats", "/arise")):
            return
            
        try:
            sender_id = event.sender_id
            if not sender_id: return
            
            # If one of our bots/accounts speaks
            if sender_id in OUR_USER_IDS:
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
                
            # If a human speaks
            if delete_delay > 0:
                asyncio.create_task(delete_other_message(event.message, delete_delay))
                
            msg_text = event.raw_text.lower() if event.raw_text else ""
            if not msg_text: return
            
            entity = event.input_chat

            # Emoji Reaction (20% chance)
            if random.random() < 0.2:
                emoji = "👍"
                if any(word in msg_text for word in ["lol", "lmao", "haha", "funny"]): emoji = "😂"
                elif any(word in msg_text for word in ["love", "amazing", "best", "great", "cute"]): emoji = "❤️"
                elif any(word in msg_text for word in ["fire", "insane", "crazy", "wow"]): emoji = "🔥"
                elif any(word in msg_text for word in ["sad", "cry", "rip", "bad"]): emoji = "😢"
                
                try:
                    reactors = [c for k, c in clients.items() if k != "acc4"]
                    if reactors:
                        reactor_acc = random.choice(reactors)
                        await reactor_acc["client"](SendReactionRequest(
                            peer=entity,
                            msg_id=event.message.id,
                            reaction=[ReactionEmoji(emoticon=emoji)]
                        ))
                except: pass
                    
            # AI Reply to Human
            is_reply_to_bot = False
            if event.message.is_reply:
                try:
                    reply_msg = await event.message.get_reply_message()
                    if reply_msg and reply_msg.sender_id in OUR_USER_IDS:
                        is_reply_to_bot = True
                except: pass
                        
                if is_reply_to_bot and HAS_GENAI:
                    try:
                        lang_mode = detect_language_mode([event.raw_text or ""])
                        lang_note = "in casual Hinglish (Roman Hindi + English, e.g. 'hn bhai kya hua', 'sahi h')" if lang_mode in ('hinglish', 'hindi_roman') else "in casual English"
                        prompt = f"You are chatting in a Telegram group with friends. A user replied to you: '{event.raw_text}'. Reply casually {lang_note} in 1 short sentence. No hashtags, no quotes."
                        response = None
                        for m_name in ["gemini-3.6-flash", "gemini-flash-lite-latest", "gemini-2.0-flash"]:
                            try:
                                response = await gemini_client.aio.models.generate_content(model=m_name, contents=prompt)
                                if response and response.text: break
                            except Exception: continue
                        if response and response.text:
                            asyncio.create_task(send_dynamic_reply(bot_client, entity, event.message, response.text.strip().replace('"', '')))
                            return
                    except: pass

                # Keyword Response
                keyword_replies = {
                    r'\b(hi|hello|hey|sup)\b': ["Hey there!", "Hi!", "Hello!"],
                    r'\b(bye|cya|gn)\b': ["See ya!", "Bye!"],
                    r'\b(anime|manga)\b': ["I love anime!", "Konsa anime dekh raha h abhi?"]
                }
                
                responded = False
                for pattern, replies in keyword_replies.items():
                    if re.search(pattern, msg_text):
                        reply_acc = random.choice([clients["acc1"], clients["acc2"], clients["acc3"]])
                        reply_text = random.choice(replies)
                        asyncio.create_task(send_dynamic_reply(reply_acc["client"], entity, event.message, reply_text))
                        responded = True
                        break
                        
                if not responded and HAS_GENAI:
                    # WAKE WORD: Only respond if the human mentions "gun"
                    if re.search(r'\bgun\b', msg_text):
                        try:
                            lang_mode = detect_language_mode([msg_text])
                            lang_note = "in casual Hinglish (Roman Hindi + English)" if lang_mode in ('hinglish', 'hindi_roman') else "in casual English"
                            prompt = f"You are Gun, a casual friend in a Telegram group. Keep your response very short (1 sentence), natural, lowercase {lang_note}. Reply to: {msg_text}"
                            response = None
                            for m_name in ["gemini-3.6-flash", "gemini-flash-lite-latest", "gemini-2.0-flash"]:
                                try:
                                    response = await gemini_client.aio.models.generate_content(model=m_name, contents=prompt)
                                    if response and response.text: break
                                except Exception: continue
                            if response and response.text:
                                if "acc4" in clients:
                                    reply_acc = clients["acc4"]
                                    acc4_entity = BOT_ENTITY or TARGET_INPUT_PEER or await reply_acc["client"].get_entity(TARGET_CHAT_ID or TARGET_CHAT)
                                    asyncio.create_task(send_dynamic_reply(reply_acc["client"], acc4_entity, event.message, response.text.strip().replace('"', '')))
                        except: pass
        except: pass

async def trigger_anime_news_event(entity):
    global total_messages_sent
    if not HAS_GENAI or "acc4" not in clients: return
    try:
        logging.info("Triggering Seasonal Anime / Gaming Event...")
        seasonal = await fetch_seasonal_anime()
        anime_title = random.choice(seasonal)["title"] if seasonal else "Bleach: Thousand-Year Blood War"
        
        prompt_news = (
            f"You are a casual Indian anime fan in a Telegram group chat with friends. "
            f"Mention something exciting about the currently airing or upcoming anime '{anime_title}'. "
            f"Write 1 short sentence in natural, casual Hinglish (Roman Hindi + English, e.g. 'bhai {anime_title} ka next episode kab aayega pata h kya?'). "
            f"Do not use hashtags or quotes."
        )
        news_text = None
        for m in ["gemini-3.6-flash", "gemini-flash-lite-latest", "gemini-2.0-flash"]:
            try:
                resp_news = await gemini_client.aio.models.generate_content(model=m, contents=prompt_news)
                if resp_news and resp_news.text:
                    news_text = resp_news.text.strip().replace('"', '')
                    break
            except Exception:
                continue
                
        if not news_text:
            news_text = f"bhai {anime_title} ka latest episode dekha kisine? animation mast chal raha h"
            
        acc4 = clients["acc4"]["client"]
        acc4_entity = BOT_ENTITY or TARGET_INPUT_PEER or await acc4.get_entity(TARGET_CHAT_ID or TARGET_CHAT)
        await simulate_typing(acc4, acc4_entity, news_text)
        
        news_msg = await acc4.send_message(acc4_entity, news_text)
        logging.info(f"[Account 4] SEASONAL HINGLISH: {news_text}")
        total_messages_sent += 1
        if delete_delay > 0:
            asyncio.create_task(delete_message_later(acc4, entity.id, news_msg.id, delete_delay))
            
        await asyncio.sleep(random.uniform(3.0, 6.0))
        
        active_accs = [c for k, c in clients.items() if k != "acc4"]
        random.shuffle(active_accs)
        
        for acc in active_accs[:2]:
            if random.random() < 0.5:
                try:
                    emoji = random.choice(["🔥", "👀", "💯", "😂"])
                    await acc["client"](SendReactionRequest(peer=entity, msg_id=news_msg.id, reaction=[ReactionEmoji(emoticon=emoji)]))
                except: pass
                
            prompt_reply = (
                f"You are an Indian friend replying to: '{news_text}'. "
                f"Give a short 1-sentence reply in natural casual Hinglish (e.g. 'hn kal hi dekha maine', 'ruk spoiler mat dena', 'sahi me')."
            )
            reply_text = None
            for m in ["gemini-3.6-flash", "gemini-flash-lite-latest", "gemini-2.0-flash"]:
                try:
                    resp_reply = await gemini_client.aio.models.generate_content(model=m, contents=prompt_reply)
                    if resp_reply and resp_reply.text:
                        reply_text = resp_reply.text.strip().replace('"', '')
                        break
                except Exception:
                    continue
            if not reply_text:
                reply_text = random.choice(["hn maine bhi dekha tha", "ruk spoiler mat de abhi", "aaj raat ko dekhunga"])
                
            acc_entity = await acc["client"].get_entity(TARGET_CHAT_ID or TARGET_CHAT)
            await simulate_typing(acc["client"], acc_entity, reply_text)
                
            reply_msg = await acc["client"].send_message(acc_entity, reply_text, reply_to=news_msg.id)
            logging.info(f"[{acc['name']}] REACTS: {reply_text}")
            total_messages_sent += 1
            if delete_delay > 0:
                asyncio.create_task(delete_message_later(acc["client"], entity.id, reply_msg.id, delete_delay))
                
            await asyncio.sleep(random.uniform(2.5, 5.0))
            
    except Exception as e:
        logging.error(f"Anime News Event Failed: {e}")

async def trigger_poll_event(entity):
    global total_messages_sent
    if not HAS_GENAI or "acc4" not in clients: return
    try:
        logging.info("Triggering Hinglish Poll Event...")
        prompt = (
            "Create a fun, casual anime or gaming poll for an Indian group chat in Hinglish. "
            "Format exactly: Question | Option 1 | Option 2 | Option 3"
        )
        text = None
        for m in ["gemini-3.6-flash", "gemini-flash-lite-latest", "gemini-2.0-flash"]:
            try:
                response = await gemini_client.aio.models.generate_content(model=m, contents=prompt)
                if response and response.text:
                    text = response.text.strip().replace('"', '')
                    break
            except Exception:
                continue
                
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
        acc4_entity = BOT_ENTITY or TARGET_INPUT_PEER or await acc4.get_entity(TARGET_CHAT_ID or TARGET_CHAT)
        await simulate_typing(acc4, acc4_entity, question)
        poll_msg = await acc4.send_message(acc4_entity, file=poll_media)
        logging.info(f"[Account 4] POLL: {question}")
        total_messages_sent += 1
        
        if delete_delay > 0:
            asyncio.create_task(delete_message_later(acc4, entity.id, poll_msg.id, max(delete_delay, 120)))
            
    except Exception as e:
        logging.error(f"Poll Event Failed: {e}")

async def chat_loop():
    global bot_active, total_messages_sent
    
    csv_index = await load_state_from_telegram()
    logging.info(f"Resuming conversation from CSV index {csv_index}")
    active_keys = [k for k in clients.keys() if k != "acc4"]
    message_tracker = {}
    rate_limited_until = {}
    
    last_chosen_key = None
    last_conv_id = None
    recent_thread_messages = []
    
    while True:
        current_time = time.time()
        available_keys = [k for k in active_keys if rate_limited_until.get(k, 0) < current_time]
        
        if bot_active and conversation_data and available_keys:
            loop_start = time.time()
            msg_data = conversation_data[csv_index]
            
            sender_str = msg_data.get("sender", "").strip()
            conv_id = msg_data.get("conversation_id", "").strip()
            msg_text = msg_data.get("message", "...")
            csv_id = msg_data.get("id", "").strip()
            reply_to_csv = msg_data.get("reply_to", "").strip()
            topic = msg_data.get("topic", "general")
            
            # Natural pause when switching to a completely new conversation thread
            if last_conv_id and conv_id and conv_id != last_conv_id:
                recent_thread_messages.clear()
                thread_pause = random.uniform(10.0, 20.0)
                logging.info(f"Finished thread {last_conv_id}. Pausing {thread_pause:.1f}s before starting {conv_id}...")
                await asyncio.sleep(thread_pause)
            last_conv_id = conv_id
            
            # Allow non-linear speaker turns (e.g. acc1 sending 2 consecutive messages)
            if sender_str in available_keys:
                chosen_key = sender_str
            else:
                chosen_key = random.choice(available_keys)
                
            is_same_speaker = (chosen_key == last_chosen_key)
            last_chosen_key = chosen_key
                
            client = clients[chosen_key]["client"]
            name = clients[chosen_key]["name"]
            
            try:
                entity = await client.get_entity(TARGET_CHAT_ID or TARGET_CHAT)
                
                # 3% chance for Account 4 to trigger live Seasonal anime news
                if HAS_GENAI and random.random() < 0.03:
                    await trigger_anime_news_event(entity)
                    
                # 2% chance for interactive Poll
                if HAS_GENAI and random.random() < 0.02:
                    await trigger_poll_event(entity)
                    
                # 1.5% chance for animated sticker or dice
                if random.random() < 0.015:
                    emoji_sticker = random.choice(['🎲', '🎯', '🎳', '🔥', '😂', '👍'])
                    if emoji_sticker in ['🎲', '🎯', '🎳']:
                        await simulate_typing(client, entity, "sticker")
                        sent_sticker = await client.send_message(entity, file=InputMediaDice(emoticon=emoji_sticker))
                    else:
                        await simulate_typing(client, entity, emoji_sticker)
                        sent_sticker = await client.send_message(entity, emoji_sticker)
                    logging.info(f"[{name}] Sent Animated Sticker: {emoji_sticker}")
                    total_messages_sent += 1
                    if delete_delay > 0:
                        asyncio.create_task(delete_message_later(client, entity.id, sent_sticker.id, delete_delay))
                
                # Find reply_to message id in active group
                reply_msg_id = None
                if reply_to_csv and reply_to_csv in message_tracker:
                    reply_msg_id = message_tracker[reply_to_csv]
                
                if msg_text in ["[Photo]", "[Sticker]", "[Video]", "[GIF]"]:
                    msg_text = "✨"
                    
                await simulate_typing(client, entity, msg_text)
                
                sent_msg = await client.send_message(entity, msg_text, reply_to=reply_msg_id)
                logging.info(f"[{name}] ({topic}): {msg_text}")
                
                total_messages_sent += 1
                recent_thread_messages.append(f"{name}: {msg_text}")
                if len(recent_thread_messages) > 6:
                    recent_thread_messages.pop(0)
                
                if csv_id:
                    message_tracker[csv_id] = sent_msg.id
                    if len(message_tracker) > 1000:
                        message_tracker.pop(next(iter(message_tracker)))
                
                if delete_delay > 0:
                    asyncio.create_task(delete_message_later(client, entity.id, sent_msg.id, delete_delay))
                    
                # Account 4 AI Context-Aware Participation (5% chance, matching Hinglish/English tone)
                if HAS_GENAI and random.random() < 0.05 and "acc4" in clients and len(recent_thread_messages) >= 2:
                    try:
                        lang_mode = detect_language_mode(recent_thread_messages)
                        ai_prompt = get_account4_system_prompt(topic, recent_thread_messages, lang_mode)
                        ai_resp = None
                        for m_name in ["gemini-3.6-flash", "gemini-flash-lite-latest", "gemini-2.0-flash"]:
                            try:
                                ai_resp = await gemini_client.aio.models.generate_content(model=m_name, contents=ai_prompt)
                                if ai_resp and ai_resp.text:
                                    break
                            except Exception:
                                continue
                        if ai_resp and ai_resp.text:
                            ai_text = ai_resp.text.strip().replace('"', '')
                            acc4_client = clients["acc4"]["client"]
                            acc4_entity = BOT_ENTITY or TARGET_INPUT_PEER or await acc4_client.get_entity(TARGET_CHAT_ID or TARGET_CHAT)
                            await simulate_typing(acc4_client, acc4_entity, ai_text)
                            ai_sent_msg = await acc4_client.send_message(acc4_entity, ai_text, reply_to=sent_msg.id)
                            logging.info(f"[Account 4 (Bot)] AI Joined ({lang_mode}): {ai_text}")
                            total_messages_sent += 1
                            recent_thread_messages.append(f"Account 4: {ai_text}")
                            if delete_delay > 0:
                                asyncio.create_task(delete_message_later(acc4_client, entity.id, ai_sent_msg.id, delete_delay))
                    except Exception as ai_e:
                        logging.warning(f"Account 4 AI participation error: {ai_e}")
                
                csv_index = (csv_index + 1) % len(conversation_data)
                if csv_index % 50 == 0:
                    asyncio.create_task(save_state_to_telegram(csv_index))
            except FloodWaitError as e:
                logging.warning(f"[{name}] Rate limited! Pausing this account for {e.seconds}s")
                rate_limited_until[chosen_key] = current_time + e.seconds
                try:
                    if "acc4" in clients:
                        acc4_client = clients["acc4"]["client"]
                        acc4_entity = BOT_ENTITY or TARGET_INPUT_PEER or await acc4_client.get_entity(TARGET_CHAT_ID or TARGET_CHAT)
                        await acc4_client.send_message(acc4_entity, f"⚠️ **Warning**: {name} is sending messages too fast and got rate-limited by Telegram! Pausing them for {e.seconds} seconds.")
                except: pass
                continue
            except ConnectionError as e:
                logging.error(f"Connection dropped! Pausing for 5s to reconnect: {e}")
                await asyncio.sleep(5)
            except Exception as e:
                logging.error(f"Error sending message: {e}")
                await asyncio.sleep(3)
                
            # Realistic variable pacing:
            # - If same speaker sends 2 consecutive lines: fast burst (2.0s - 3.5s)
            # - If different speakers: natural pacing with subtle jitter
            elapsed = time.time() - loop_start
            if is_same_speaker:
                sleep_duration = random.uniform(2.0, 3.5)
            else:
                jitter = random.uniform(0.85, 1.15)
                sleep_duration = max(1.5, (message_speed * jitter) - elapsed)
                
            await asyncio.sleep(sleep_duration)
        else:
            await asyncio.sleep(2)

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
        if key == "acc4":
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
            
    global TARGET_CHAT_ID, TARGET_INPUT_PEER, BOT_ENTITY
    BOT_ENTITY = None
    TARGET_INPUT_PEER = None
    if "acc1" in clients:
        try:
            if isinstance(TARGET_CHAT, str) and (TARGET_CHAT.startswith("-100") or TARGET_CHAT.lstrip('-').isdigit()):
                entity = await clients["acc1"]["client"].get_entity(int(TARGET_CHAT))
            else:
                entity = await clients["acc1"]["client"].get_entity(TARGET_CHAT)
            TARGET_CHAT_ID = utils.get_peer_id(entity)
            if hasattr(entity, 'access_hash'):
                from telethon.tl.types import InputPeerChannel
                TARGET_INPUT_PEER = InputPeerChannel(entity.id, entity.access_hash)
            logging.info(f"Resolved TARGET_CHAT to ID: {TARGET_CHAT_ID}")
        except Exception as e:
            logging.warning(f"Could not resolve TARGET_CHAT via link ({e}). Searching dialogs for group...")
            try:
                dialogs = await clients["acc1"]["client"].get_dialogs(limit=50)
                for d in dialogs:
                    if d.is_group or d.is_channel:
                        title = (d.title or "").lower()
                        if any(term in title for term in ["prisoner", "mafia", "tarot", "anime", "limited", "club"]) or not TARGET_CHAT_ID:
                            TARGET_CHAT_ID = d.id
                            if hasattr(d.entity, 'access_hash'):
                                from telethon.tl.types import InputPeerChannel
                                TARGET_INPUT_PEER = InputPeerChannel(d.entity.id, d.entity.access_hash)
                            logging.info(f"Auto-discovered active group from dialogs: '{d.title}' (ID: {TARGET_CHAT_ID})")
                            if any(term in title for term in ["prisoner", "mafia", "tarot", "anime", "limited", "club"]):
                                break
            except Exception as dialog_err:
                logging.error(f"Dialog fallback search failed: {dialog_err}")
                TARGET_CHAT_ID = None

    if "acc4" in clients:
        setup_commands(clients["acc4"]["client"])
    elif "acc1" in clients:
        logging.info("Account 4 is connecting in background. Registering admin commands & auto-delete on Account 1 as fallback.")
        setup_commands(clients["acc1"]["client"])
        
    if "acc1" in clients:
        acc1_c = clients["acc1"]["client"]
        @acc1_c.on(events.NewMessage(pattern=r'(?i)^/(?:setdelete|autodelete|setdel|delete)(?:@genzetabot)?(?:\s+(.+))?$'))
        async def acc1_saved_setdelete(event):
            try:
                if event.is_private and (event.chat_id == accounts["acc1"]["user_id"] or event.chat_id == "me" or (getattr(event, 'out', False) and getattr(event.message, 'peer_id', None) and getattr(event.message.peer_id, 'user_id', None) == accounts["acc1"]["user_id"])):
                    global delete_delay
                    arg = event.pattern_match.group(1)
                    if not arg or not arg.strip():
                        readable = format_seconds_to_readable(delete_delay)
                        await event.reply(
                            f"🗑 **Current Auto-Delete:** **{readable}** ({delete_delay}s)\n\n"
                            f"Set to any duration anytime:\n"
                            f"• `/setdelete 15m` (15 minutes)\n"
                            f"• `/setdelete 1h` (1 hour)\n"
                            f"• `/setdelete 12h` (12 hours)\n"
                            f"• `/setdelete 1d` (1 day)\n"
                            f"• `/setdelete 7days` (7 days)\n"
                            f"• `/setdelete 0` (disable)"
                        )
                        return
                    del_val = parse_time_to_seconds(arg.strip())
                    if del_val is not None:
                        delete_delay = del_val
                        readable = format_seconds_to_readable(delete_delay)
                        await save_state_to_telegram()
                        await event.reply(f"🗑 Auto-delete set to **{readable}** ({delete_delay}s) by User 1! (Saved)")
                        try:
                            target = TARGET_CHAT_ID or TARGET_CHAT
                            if isinstance(target, str) and (target.startswith("-100") or target.lstrip('-').isdigit()):
                                target = int(target)
                            entity = await acc1_c.get_entity(target)
                            asyncio.create_task(history_sweeper(acc1_c, entity, delete_delay))
                        except: pass
                    else:
                        await event.reply("❌ Invalid format! Example: `/setdelete 15m`, `/setdelete 1h`, `/setdelete 7days`")
            except Exception as e:
                logging.error(f"Error in acc1_saved_setdelete: {e}")

        @acc1_c.on(events.NewMessage(pattern=r'(?i)^/(?:setspeed|speed)(?:@genzetabot)?(?:\s+(.+))?$'))
        async def acc1_saved_setspeed(event):
            try:
                if event.is_private and (event.chat_id == accounts["acc1"]["user_id"] or event.chat_id == "me" or (getattr(event, 'out', False) and getattr(event.message, 'peer_id', None) and getattr(event.message.peer_id, 'user_id', None) == accounts["acc1"]["user_id"])):
                    global message_speed
                    arg = event.pattern_match.group(1)
                    if not arg or not arg.strip():
                        await event.reply(
                            f"⚡ **Global Conversation Speed:** 1 message every **{message_speed}s**.\n\n"
                            f"All accounts (**Account 1, Account 2, Account 3**) follow this speed.\n"
                            f"To change, send: `/setspeed 5s`, `/setspeed 10s`, `/setspeed 15s`, or `/setspeed 30s`."
                        )
                        return
                    speed_val = parse_time_to_seconds(arg.strip())
                    if speed_val is not None and speed_val > 0:
                        message_speed = int(speed_val)
                        await save_state_to_telegram()
                        await event.reply(
                            f"⚡ **Speed Updated for ALL Accounts!**\n\n"
                            f"Every account (**Account 1, Account 2, Account 3**) will now send 1 message every **{message_speed} seconds**."
                        )
                    else:
                        await event.reply("❌ Invalid speed! Example: `/setspeed 5s`, `/setspeed 10s`, or `/setspeed 15s`.")
            except Exception as e:
                logging.error(f"Error in acc1_saved_setspeed: {e}")

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
    

    global SPAWN_CHAT_ID, SPAWN_CHAT_TITLE
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
    # Run conversation loop as a background task!
    asyncio.create_task(chat_loop())
    
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
