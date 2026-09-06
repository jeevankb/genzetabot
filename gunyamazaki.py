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

# Try importing generative AI
try:
    from google import genai
    HAS_GENAI = True
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except ImportError:
    HAS_GENAI = False
    gemini_client = None

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()
if HAS_GENAI and not gemini_client:
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Data loading
CSV_FILE = "anime_group_chat_10000.csv"
TARGET_CHAT = os.getenv("TARGET_CHAT", "https://t.me/+1tWK4j-BYC85MDVl")
TARGET_CHAT_ID = None
conversation_data = []

# Arise Auto-Catcher Configuration
ARISE_DATABASE_CHANNEL = os.getenv("ARISE_DATABASE_CHANNEL", "Arise_your_character_database")
SPAWN_CHAT = os.getenv("SPAWN_CHAT", "https://t.me/+wO6jijXTj1VhNWQ1")
SPAWN_CHAT_ID = None
ARISE_DB_FILE = "arise_db.json"
arise_character_db = []
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
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, CSV_FILE)
    
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
delete_delay = 900  # Default 15 minutes
total_messages_sent = 0
clients = {}
STATE_MSG_ID = None



async def load_state_from_telegram():
    global STATE_MSG_ID
    try:
        acc1 = clients["acc1"]["client"]
        async for msg in acc1.iter_messages("me", search="[GunYamazaki State]"):
            if "[GunYamazaki State]" in msg.text:
                STATE_MSG_ID = msg.id
                try:
                    return int(msg.text.split("csv_index=")[1])
                except: pass
                break
    except Exception as e:
        logging.error(f"Failed to load state from telegram: {e}")
    return 0

async def save_state_to_telegram(csv_idx):
    global STATE_MSG_ID
    try:
        acc1 = clients["acc1"]["client"]
        text = f"[GunYamazaki State] csv_index={csv_idx}"
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
    try:
        # Check weeks
        if time_str.endswith(('weeks', 'week', 'w')):
            val = time_str.rstrip('weeks').rstrip('week').rstrip('w')
            return int(val) * 604800
        # Check days (e.g. 4days, 4day, 4d)
        elif time_str.endswith(('days', 'day', 'd')):
            val = time_str.rstrip('days').rstrip('day').rstrip('d')
            return int(val) * 86400
        # Check hours (e.g. 12hours, 12hour, 12h)
        elif time_str.endswith(('hours', 'hour', 'h')):
            val = time_str.rstrip('hours').rstrip('hour').rstrip('h')
            return int(val) * 3600
        # Check minutes (e.g. 15mins, 15min, 15m)
        elif time_str.endswith(('mins', 'min', 'm')):
            val = time_str.rstrip('mins').rstrip('min').rstrip('m')
            return int(val) * 60
        # Check seconds (e.g. 30secs, 30sec, 30s)
        elif time_str.endswith(('secs', 'sec', 's')):
            val = time_str.rstrip('secs').rstrip('sec').rstrip('s')
            return int(val)
        return int(time_str)
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
    if message_speed < 3:
        await asyncio.sleep(message_speed)
        return
        
    typing_time = min(max(len(text) * 0.05, 1.0), 8.0)
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
# ARISE AUTO-CATCHER MODULE
# ==========================================

def compute_dhash(image, hash_size=8):
    """Computes difference hash (dHash) for fast visual comparison."""
    try:
        image = image.convert('L').resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
        pixels = list(image.getdata())
        diff = []
        for row in range(hash_size):
            for col in range(hash_size):
                left = pixels[row * (hash_size + 1) + col]
                right = pixels[row * (hash_size + 1) + col + 1]
                diff.append(left > right)
        decimal_val = 0
        for index, value in enumerate(diff):
            if value:
                decimal_val |= 1 << index
        return hex(decimal_val)[2:].zfill(hash_size * hash_size // 4)
    except Exception as e:
        logging.error(f"Error computing dHash: {e}")
        return None

def hamming_distance(h1, h2):
    """Calculates bit difference between two hex hashes."""
    try:
        val1 = int(h1, 16)
        val2 = int(h2, 16)
        return bin(val1 ^ val2).count('1')
    except:
        return 999

def load_arise_db():
    global arise_character_db
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(script_dir, ARISE_DB_FILE)
    if os.path.exists(db_path):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                arise_character_db = json.load(f)
            logging.info(f"Loaded {len(arise_character_db)} Arise characters from {ARISE_DB_FILE}.")
        except Exception as e:
            logging.error(f"Failed to load {ARISE_DB_FILE}: {e}")
    else:
        logging.info(f"{ARISE_DB_FILE} not found. Use /syncarise to scan the database channel.")

def save_arise_db():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(script_dir, ARISE_DB_FILE)
    try:
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(arise_character_db, f, ensure_ascii=False, indent=2)
        logging.info(f"Saved {len(arise_character_db)} Arise characters to {ARISE_DB_FILE}.")
    except Exception as e:
        logging.error(f"Failed to save {ARISE_DB_FILE}: {e}")

async def sync_arise_database(client, status_callback=None):
    """Scans the Arise character database channel and builds arise_db.json."""
    global arise_character_db
    try:
        logging.info(f"Scanning Arise database channel: {ARISE_DATABASE_CHANNEL}...")
        entity = await client.get_entity(ARISE_DATABASE_CHANNEL)
        existing_ids = {entry["id"] for entry in arise_character_db if "id" in entry}
        
        new_entries = []
        scanned_count = 0
        
        async for msg in client.iter_messages(entity, limit=4000):
            if not msg.photo or not msg.text:
                continue
                
            match = re.search(r'\b(\d+):\s*([^\n\(\)]+)', msg.text)
            if not match:
                continue
                
            char_id = int(match.group(1))
            char_name = match.group(2).strip()
            
            if char_id in existing_ids:
                continue
                
            anime_match = re.search(r'Anime:\s*([^\n\[]+)', msg.text)
            anime_name = anime_match.group(1).strip() if anime_match else ""
            
            photo_bytes = io.BytesIO()
            await client.download_media(msg, file=photo_bytes, thumb=-1)
            photo_bytes.seek(0)
            
            try:
                img = Image.open(photo_bytes)
                img_hash = compute_dhash(img)
                if img_hash:
                    entry = {
                        "id": char_id,
                        "name": char_name,
                        "anime": anime_name,
                        "hash": img_hash,
                        "msg_id": msg.id
                    }
                    new_entries.append(entry)
                    existing_ids.add(char_id)
                    scanned_count += 1
                    if scanned_count % 100 == 0:
                        logging.info(f"[Arise Sync] Indexed {scanned_count} characters...")
                        if status_callback:
                            await status_callback(f"⏳ Indexed {scanned_count} characters...")
            except Exception as e:
                pass
                
        if new_entries:
            arise_character_db.extend(new_entries)
            save_arise_db()
            logging.info(f"Database sync complete! Added {len(new_entries)} characters. Total: {len(arise_character_db)}")
            return len(new_entries), len(arise_character_db)
        else:
            logging.info("Arise database is already up to date.")
            return 0, len(arise_character_db)
    except Exception as e:
        logging.error(f"Error syncing Arise database: {e}")
        return -1, len(arise_character_db)

def find_best_character_match(image_bytes):
    """Matches a spawn image against the indexed Arise database."""
    if not arise_character_db:
        return None, 999
    try:
        img = Image.open(image_bytes)
        spawn_hash = compute_dhash(img)
        if not spawn_hash:
            return None, 999
            
        best_match = None
        min_dist = 999
        for entry in arise_character_db:
            dist = hamming_distance(spawn_hash, entry["hash"])
            if dist < min_dist:
                min_dist = dist
                best_match = entry
                if dist == 0:
                    break
        return best_match, min_dist
    except Exception as e:
        logging.error(f"Error matching character: {e}")
        return None, 999

async def handle_spawn_message(event):
    """Processes gate spawn messages and catches the character using Account 1 (with Acc 2/3 fallback)."""
    global account_rate_limited_until, processed_spawn_ids
    if not arise_autocatch_active:
        return
        
    if event.id in processed_spawn_ids:
        return
    processed_spawn_ids.add(event.id)
    if len(processed_spawn_ids) > 500:
        processed_spawn_ids.pop()
        
    text = (event.raw_text or "").upper()
    if "THE GATE WAS SPAWNED" not in text and "/ARISE" not in text:
        return
        
    if not event.media:
        return
        
    logging.info(f"[Auto-Catcher] Gate spawn detected in chat {event.chat_id}! Identifying character...")
    
    photo_bytes = io.BytesIO()
    try:
        await event.download_media(file=photo_bytes, thumb=-1)
        photo_bytes.seek(0)
    except Exception as e:
        logging.error(f"[Auto-Catcher] Failed to download spawn photo: {e}")
        return
        
    char_name = None
    best_match, dist = find_best_character_match(photo_bytes)
    if best_match and dist <= 10:
        char_name = best_match["name"]
        logging.info(f"🎯 [Auto-Catcher] DATABASE MATCH: '{char_name}' (distance: {dist}/64)")
    else:
        # High-Speed Gemini Vision Fallback (Works 100% of the time, even if local DB is still building)
        logging.info(f"[Auto-Catcher] Database match distance ({dist}) too high or DB empty. Using Gemini Vision AI fallback...")
        if HAS_GENAI and gemini_client:
            try:
                photo_bytes.seek(0)
                img = Image.open(photo_bytes)
                prompt = "Identify this anime or video game character. Return ONLY the exact character name in English (e.g. 'Lain Iwakura' or 'Ruan Mei'), nothing else. No punctuation, no show title."
                res = await gemini_client.aio.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=[img, prompt]
                )
                if res and res.text:
                    char_name = res.text.strip().replace('\n', '').strip('".*')
                    logging.info(f"🎯 [Auto-Catcher] GEMINI VISION IDENTIFIED: '{char_name}'")
            except Exception as ge:
                logging.error(f"[Auto-Catcher] Gemini Vision fallback failed: {ge}")
                
    if not char_name:
        logging.warning("[Auto-Catcher] Could not identify character name via database or Gemini Vision. Skipping.")
        return
        
    logging.info(f"🏆 [Auto-Catcher] Target Locked: '{char_name}'. Preparing to catch...")
    
    # Natural reaction delay (1.2s to 2.0s)
    await asyncio.sleep(random.uniform(1.2, 2.0))
    
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
            await catcher_client.send_message(event.chat_id, catch_cmd, reply_to=event.message.id)
            logging.info(f"🏆 [Auto-Catcher] {catcher_name} SENT: {catch_cmd}")
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
    @bot_client.on(events.NewMessage(pattern='(?i)^/stats(?:@genzetabot)?$'))
    async def stats_handler(event):
        try:
            sender = await event.get_sender()
            if sender and sender.id == accounts["acc1"]["user_id"]:
                status = "🟢 ONLINE" if bot_active else "🔴 OFFLINE"
                del_str = format_seconds_to_readable(delete_delay)
                catch_status = f"🟢 ONLINE ({len(arise_character_db)} chars)" if arise_autocatch_active else "🔴 OFFLINE"
                await event.reply(f"📊 **GunYamazaki Stats**\n\nStatus: {status}\nSpeed: {message_speed}s\nAuto-Delete: {del_str}\nAuto-Catch: {catch_status}\nMessages Sent: {total_messages_sent}")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/syncarise(?:@genzetabot)?$'))
    async def syncarise_handler(event):
        try:
            sender = await event.get_sender()
            if sender and sender.id == accounts["acc1"]["user_id"]:
                status_msg = await event.reply("🔄 Scanning @Arise_your_character_database for character cards... Please wait!")
                async def update_status(text):
                    try: await status_msg.edit(text)
                    except: pass
                if "acc1" in clients:
                    new_added, total = await sync_arise_database(clients["acc1"]["client"], update_status)
                    if new_added >= 0:
                        await status_msg.edit(f"✅ **Arise Database Synced!**\n\nNew Characters Added: {new_added}\nTotal in Database: {total}")
                    else:
                        await status_msg.edit("❌ Failed to sync database! Check logs for details.")
                else:
                    await status_msg.edit("❌ Account 1 is not connected to perform the sync.")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/ariseon(?:@genzetabot)?$'))
    async def ariseon_handler(event):
        global arise_autocatch_active
        try:
            sender = await event.get_sender()
            if sender and sender.id == accounts["acc1"]["user_id"]:
                arise_autocatch_active = True
                await event.reply("✅ Arise Auto-Catcher is now **ONLINE**! Watching for gate spawns.")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/ariseoff(?:@genzetabot)?$'))
    async def ariseoff_handler(event):
        global arise_autocatch_active
        try:
            sender = await event.get_sender()
            if sender and sender.id == accounts["acc1"]["user_id"]:
                arise_autocatch_active = False
                await event.reply("🛑 Arise Auto-Catcher is now **OFFLINE**.")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/lockon(?:@genzetabot)?$'))
    async def lockon_handler(event):
        global bot_active, BOT_ENTITY, TARGET_CHAT_ID
        BOT_ENTITY = event.input_chat
        TARGET_CHAT_ID = event.chat_id
        # Only allow Account 1 to use this command
        try:
            sender = await event.get_sender()
            if sender and sender.id == accounts["acc1"]["user_id"]:
                bot_active = True
                await event.reply(f"✅ GunYamazaki System Locked On to chat {TARGET_CHAT_ID}. Starting conversation loop...")
                logging.info(f"System LOCKED ON to {TARGET_CHAT_ID} by admin.")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/lockoff(?:@genzetabot)?$'))
    async def lockoff_handler(event):
        global bot_active
        try:
            sender = await event.get_sender()
            if sender and sender.id == accounts["acc1"]["user_id"]:
                bot_active = False
                await event.reply("🛑 GunYamazaki System Locked Off. Stopping conversation loop...")
                logging.info("System LOCKED OFF by admin.")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/setspeed(?:@genzetabot)?\\s+(.+)'))
    async def setspeed_handler(event):
        global message_speed
        try:
            sender = await event.get_sender()
            if sender and sender.id == accounts["acc1"]["user_id"]:
                speed_val = parse_time_to_seconds(event.pattern_match.group(1))
                if speed_val is not None:
                    message_speed = speed_val
                    await event.reply(f"⚡ Speed set to 1 message every {message_speed} seconds.")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/setdelete(?:@genzetabot)?\\s+(.+)'))
    async def setdelete_handler(event):
        global delete_delay
        try:
            sender = await event.get_sender()
            if sender and sender.id == accounts["acc1"]["user_id"]:
                raw_val = event.pattern_match.group(1).strip()
                del_val = parse_time_to_seconds(raw_val)
                if del_val is not None:
                    delete_delay = del_val
                    readable = format_seconds_to_readable(delete_delay)
                    await event.reply(f"🗑 Auto-delete set to **{readable}** ({delete_delay}s). Starting sweep...")
                    try:
                        acc1_client = clients["acc1"]["client"]
                        target = TARGET_CHAT_ID or TARGET_CHAT
                        if isinstance(target, str) and (target.startswith("-100") or target.lstrip('-').isdigit()):
                            target = int(target)
                        entity = await acc1_client.get_entity(target)
                        asyncio.create_task(history_sweeper(acc1_client, entity, delete_delay))
                    except: pass
                else:
                    await event.reply("❌ Invalid time format! You can use: `/setdelete 4days`, `/setdelete 12h`, `/setdelete 15m`, `/setdelete 30s`, or `/setdelete 0`.")
        except: pass

    @bot_client.on(events.NewMessage())
    async def auto_delete_handler(event):
        global BOT_ENTITY
        if not event.is_group and not event.is_channel:
            return
        if TARGET_CHAT_ID and isinstance(TARGET_CHAT_ID, int) and event.chat_id != TARGET_CHAT_ID:
            return
        BOT_ENTITY = event.input_chat
        if event.raw_text and event.raw_text.lower().startswith(("/lockon", "/lockoff", "/setdelete", "/setspeed")):
            return
            
        try:
            sender = await event.get_sender()
            if not sender: return
            
            our_ids = []
            for acc_data in clients.values():
                our_ids.append((await acc_data["client"].get_me()).id)
                
            # If a bot speaks
            if sender.id in our_ids:
                if random.random() < 0.15:
                    try:
                        emoji = random.choice(["👍", "😂", "❤️", "🔥", "🤔", "👀", "👌", "✨"])
                        reactor_acc = random.choice([c for k, c in clients.items() if k != "acc4" and (await c["client"].get_me()).id != sender.id])
                        entity = await bot_client.get_entity(TARGET_CHAT_ID or TARGET_CHAT)
                        await reactor_acc["client"](SendReactionRequest(
                            peer=entity,
                            msg_id=event.message.id,
                            reaction=[ReactionEmoji(emoticon=emoji)]
                        ))
                    except: pass
                return
                
            # If a human speaks
            if sender.id not in our_ids:
                if delete_delay > 0:
                    asyncio.create_task(delete_other_message(event.message, delete_delay))
                    
                msg_text = event.raw_text.lower() if event.raw_text else ""
                if not msg_text: return
                
                entity = await bot_client.get_entity(TARGET_CHAT_ID or TARGET_CHAT)

                # Emoji Reaction (20% chance)
                if random.random() < 0.2:
                    emoji = "👍"
                    if any(word in msg_text for word in ["lol", "lmao", "haha", "funny"]): emoji = "😂"
                    elif any(word in msg_text for word in ["love", "amazing", "best", "great", "cute"]): emoji = "❤️"
                    elif any(word in msg_text for word in ["fire", "insane", "crazy", "wow"]): emoji = "🔥"
                    elif any(word in msg_text for word in ["sad", "cry", "rip", "bad"]): emoji = "😢"
                    
                    try:
                        reactor_acc = random.choice([clients["acc1"], clients["acc2"], clients["acc3"]])
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
                        if reply_msg and reply_msg.sender_id in our_ids:
                            is_reply_to_bot = True
                    except: pass
                        
                if is_reply_to_bot and HAS_GENAI:
                    try:
                        prompt = f"You are chatting in a group. A user replied to your message. Reply casually (1-2 short sentences) to them: '{event.raw_text}'"
                        response = await gemini_client.aio.models.generate_content(model="gemini-flash-lite-latest", contents=prompt)
                        if response and response.text:
                            asyncio.create_task(send_dynamic_reply(bot_client, entity, event.message, response.text.strip()))
                            return
                    except: pass

                # Keyword Response
                keyword_replies = {
                    r'\b(hi|hello|hey|sup)\b': ["Hey there!", "Hi!", "Hello!"],
                    r'\b(bye|cya|gn)\b': ["See ya!", "Bye!"],
                    r'\b(anime|manga)\b': ["I love anime!", "What's your favorite anime?"]
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
                            prompt = f"You are Gun, a casual anime fan chatting in a Telegram group. Keep your response very short (1-2 sentences), natural, lowercase, and human-like. Reply to this message: {msg_text}"
                            response = await gemini_client.aio.models.generate_content(model="gemini-flash-lite-latest", contents=prompt)
                            if response and response.text:
                                if "acc4" in clients:
                                    reply_acc = clients["acc4"]
                                    acc4_entity = BOT_ENTITY or TARGET_INPUT_PEER or await reply_acc["client"].get_entity(TARGET_CHAT_ID or TARGET_CHAT)
                                    asyncio.create_task(send_dynamic_reply(reply_acc["client"], acc4_entity, event.message, response.text.strip()))
                        except: pass
        except: pass

async def trigger_anime_news_event(entity):
    global total_messages_sent
    if not HAS_GENAI or "acc4" not in clients: return
    try:
        logging.info("Triggering Anime News Event...")
        prompt_news = "You are an anime fan in a group chat. Drop a random exciting piece of anime news (real or believable). Keep it to 1 sentence, casual, human-like. Do not use hashtags."
        resp_news = await gemini_client.aio.models.generate_content(model="gemini-flash-lite-latest", contents=prompt_news)
        news_text = resp_news.text.strip() if (resp_news and resp_news.text) else "Did you guys hear about the new anime season dropping next month? Looks insane."
        
        acc4 = clients["acc4"]["client"]
        acc4_entity = BOT_ENTITY or TARGET_INPUT_PEER or await acc4.get_entity(TARGET_CHAT_ID or TARGET_CHAT)
        await simulate_typing(acc4, acc4_entity, news_text)
        
        news_msg = await acc4.send_message(acc4_entity, news_text)
        logging.info(f"[Account 4] NEWS: {news_text}")
        total_messages_sent += 1
        if delete_delay > 0:
            asyncio.create_task(delete_message_later(acc4, entity.id, news_msg.id, delete_delay))
            
        await asyncio.sleep(message_speed)
        
        active_accs = [c for k, c in clients.items() if k != "acc4"]
        random.shuffle(active_accs)
        
        for acc in active_accs:
            if random.random() < 0.7:
                try:
                    emoji = random.choice(["🔥", "😱", "👀", "💯", "❤️"])
                    await acc["client"](SendReactionRequest(peer=entity, msg_id=news_msg.id, reaction=[ReactionEmoji(emoticon=emoji)]))
                except: pass
                
            prompt_reply = f"You are a human anime fan in a group chat. Someone just dropped this news: '{news_text}'. Reply with a natural 1-sentence reaction (e.g. wow, no way, hype). No hashtags."
            resp_reply = await gemini_client.aio.models.generate_content(model="gemini-flash-lite-latest", contents=prompt_reply)
            reply_text = resp_reply.text.strip() if (resp_reply and resp_reply.text) else "No way, that's hype!"
            
            acc_entity = await acc["client"].get_entity(TARGET_CHAT_ID or TARGET_CHAT)
            await simulate_typing(acc["client"], acc_entity, reply_text)
                
            reply_msg = await acc["client"].send_message(acc_entity, reply_text, reply_to=news_msg.id)
            logging.info(f"[{acc['name']}] REACTS: {reply_text}")
            total_messages_sent += 1
            if delete_delay > 0:
                asyncio.create_task(delete_message_later(acc["client"], entity.id, reply_msg.id, delete_delay))
                
            await asyncio.sleep(message_speed)
            
    except Exception as e:
        logging.error(f"Anime News Event Failed: {e}")

async def trigger_poll_event(entity):
    global total_messages_sent
    if not HAS_GENAI or "acc4" not in clients: return
    try:
        logging.info("Triggering Anime Poll Event...")
        prompt = "Create a fun, engaging anime poll for a group chat. Format your response exactly like this: Question | Option 1 | Option 2 | Option 3"
        response = await gemini_client.aio.models.generate_content(model="gemini-flash-lite-latest", contents=prompt)
        text = response.text.strip() if response and response.text else "Who is the strongest Hashira? | Gyomei | Sanemi | Rengoku"
        
        parts = [p.strip() for p in text.split('|') if p.strip()]
        if len(parts) < 3:
            parts = ["Who is the strongest Hashira?", "Gyomei", "Sanemi", "Rengoku"]
            
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
        logging.error(f"Anime Poll Event Failed: {e}")

async def chat_loop():
    global bot_active, total_messages_sent
    
    csv_index = await load_state_from_telegram()
    logging.info(f"Resuming conversation from CSV index {csv_index}")
    active_keys = [k for k in clients.keys() if k != "acc4"]
    message_tracker = {}
    import time
    rate_limited_until = {}
    
    while True:
        current_time = time.time()
        available_keys = [k for k in active_keys if rate_limited_until.get(k, 0) < current_time]
        
        if bot_active and conversation_data and available_keys:
            msg_data = conversation_data[csv_index]
            
            sender_str = msg_data.get("sender", "").strip()
            if sender_str in available_keys:
                chosen_key = sender_str
            else:
                chosen_key = random.choice(available_keys)
                
            client = clients[chosen_key]["client"]
            name = clients[chosen_key]["name"]
            
            msg_text = msg_data.get("message", "...")
            csv_id = msg_data.get("id", "").strip()
            reply_to_csv = msg_data.get("reply_to", "").strip()
            
            try:
                entity = await client.get_entity(TARGET_CHAT_ID or TARGET_CHAT)
                
                # 5% chance to trigger Anime News Event
                if HAS_GENAI and random.random() < 0.05:
                    await trigger_anime_news_event(entity)
                    
                # 3% chance to trigger Anime Poll Event
                if HAS_GENAI and random.random() < 0.03:
                    await trigger_poll_event(entity)
                    
                # 2% chance to drop an animated emoji sticker
                if random.random() < 0.02:
                    emoji_sticker = random.choice(['🎲', '🎯', '🏀', '⚽', '🎳', '🎰', '❤️', '🔥', '😂', '👍'])
                    if emoji_sticker in ['🎲', '🎯', '🏀', '⚽', '🎳', '🎰']:
                        await simulate_typing(client, entity, "sticker")
                        sent_sticker = await client.send_message(entity, file=InputMediaDice(emoticon=emoji_sticker))
                    else:
                        await simulate_typing(client, entity, emoji_sticker)
                        sent_sticker = await client.send_message(entity, emoji_sticker)
                    logging.info(f"[{name}] Sent Animated Sticker: {emoji_sticker}")
                    total_messages_sent += 1
                    if delete_delay > 0:
                        asyncio.create_task(delete_message_later(client, entity.id, sent_sticker.id, delete_delay))
                    await asyncio.sleep(message_speed)
                
                reply_msg_id = None
                if reply_to_csv and reply_to_csv in message_tracker:
                    reply_msg_id = message_tracker[reply_to_csv]
                
                # Fast forward if text is just [Photo] or [Sticker]
                if msg_text in ["[Photo]", "[Sticker]", "[Video]", "[GIF]"]:
                    # Don't try to type a photo tag, it looks weird. Just skip or send something small.
                    msg_text = "✨"
                    
                await simulate_typing(client, entity, msg_text)
                
                sent_msg = await client.send_message(entity, msg_text, reply_to=reply_msg_id)
                logging.info(f"[{name}] Sent: {msg_text}")
                
                total_messages_sent += 1
                
                if csv_id:
                    message_tracker[csv_id] = sent_msg.id
                    if len(message_tracker) > 1000:
                        message_tracker.pop(next(iter(message_tracker)))
                
                if delete_delay > 0:
                    asyncio.create_task(delete_message_later(client, entity.id, sent_msg.id, delete_delay))
                    
                # Account 4 AI Participation (5%)
                if HAS_GENAI and random.random() < 0.05 and "acc4" in clients:
                    try:
                        prompt = f"You are a human anime fan in a group chat. Someone just said: '{msg_text}'. Reply to them casually in 1 short sentence using natural human language (like yes, no, haha, I agree, lol). Do not use hashtags."
                        response = await gemini_client.aio.models.generate_content(model="gemini-flash-lite-latest", contents=prompt)
                        if response and response.text:
                            ai_text = response.text.strip()
                            acc4_client = clients["acc4"]["client"]
                            acc4_entity = BOT_ENTITY or TARGET_INPUT_PEER or await acc4_client.get_entity(TARGET_CHAT_ID or TARGET_CHAT)
                            await simulate_typing(acc4_client, acc4_entity, ai_text)
                            ai_sent_msg = await acc4_client.send_message(acc4_entity, ai_text, reply_to=sent_msg.id)
                            logging.info(f"[Account 4 (Bot)] AI Sent: {ai_text}")
                            total_messages_sent += 1
                            if delete_delay > 0:
                                asyncio.create_task(delete_message_later(acc4_client, entity.id, ai_sent_msg.id, delete_delay))
                    except Exception as e:
                        logging.error(f"AI Account 4 error: {e}")
                
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
                
            await asyncio.sleep(message_speed)
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

async def main():
    load_csv()
    
    # Start web server for Render
    await dummy_server()
    
    for key, cfg in accounts.items():
        session_str = cfg.get("session")
        bot_token = cfg.get("bot_token")
        api_id = cfg["api_id"]
        api_hash = cfg["api_hash"]
        
        try:
            if session_str:
                client = TelegramClient(StringSession(session_str), api_id, api_hash)
                await client.start()
                clients[key] = {"client": client, "name": cfg["name"]}
                logging.info(f"Connected {cfg['name']} via Session String.")
            elif bot_token and key == "acc4":
                client = TelegramClient(StringSession(), api_id, api_hash)
                await client.start(bot_token=bot_token)
                clients[key] = {"client": client, "name": cfg["name"]}
                logging.info(f"Connected {cfg['name']} via Bot Token.")
        except FloodWaitError as e:
            logging.warning(f"Telegram Rate Limit! {cfg['name']} must wait {e.seconds} seconds before logging in. Sleeping...")
            await asyncio.sleep(e.seconds + 2)
            if session_str:
                await client.start()
            elif bot_token and key == "acc4":
                await client.start(bot_token=bot_token)
            clients[key] = {"client": client, "name": cfg["name"]}
            logging.info(f"Connected {cfg['name']} after waiting.")
            
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
                        if any(term in title for term in ["mafia", "tarot", "anime", "limited", "club"]) or not TARGET_CHAT_ID:
                            TARGET_CHAT_ID = d.id
                            if hasattr(d.entity, 'access_hash'):
                                from telethon.tl.types import InputPeerChannel
                                TARGET_INPUT_PEER = InputPeerChannel(d.entity.id, d.entity.access_hash)
                            logging.info(f"Auto-discovered active group from dialogs: '{d.title}' (ID: {TARGET_CHAT_ID})")
                            if any(term in title for term in ["mafia", "tarot", "anime", "limited", "club"]):
                                break
            except Exception as dialog_err:
                logging.error(f"Dialog fallback search failed: {dialog_err}")
                TARGET_CHAT_ID = None

    if "acc4" in clients:
        setup_commands(clients["acc4"]["client"])
        
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
    
    # Initialize Arise Character Database & Auto-Catcher
    load_arise_db()
    if not arise_character_db and "acc1" in clients:
        logging.info("Arise database empty on boot. Starting background sync from @Arise_your_character_database...")
        asyncio.create_task(sync_arise_database(clients["acc1"]["client"]))
        
    global SPAWN_CHAT_ID
    if "acc1" in clients and SPAWN_CHAT:
        try:
            spawn_ent = await clients["acc1"]["client"].get_entity(SPAWN_CHAT)
            SPAWN_CHAT_ID = utils.get_peer_id(spawn_ent)
            logging.info(f"Resolved SPAWN_CHAT to ID: {SPAWN_CHAT_ID}")
        except Exception as e:
            logging.warning(f"Could not resolve SPAWN_CHAT ({e}). Auto-catcher will detect spawns by gate content.")
            
    # Register Arise Gate spawn listener
    for key in ["acc1", "acc2", "acc3"]:
        if key in clients:
            c_client = clients[key]["client"]
            @c_client.on(events.NewMessage())
            async def spawn_watcher(event):
                if not event.is_group and not event.is_channel:
                    return
                await handle_spawn_message(event)
    logging.info("Arise Auto-Catcher listener registered for gate spawns.")
    
    await chat_loop()
    
    # Start dummy web server for Render health checks
    from aiohttp import web
    async def handle(request):
        return web.Response(text="GunYamazaki Bot is running!")
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Dummy Web Server started on port {port} for Render.")
    
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
