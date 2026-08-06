import asyncio
import os
import csv
import random
import logging
import re
import datetime
from collections import defaultdict, deque
from aiohttp import web
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
from telethon.tl.types import ChannelParticipantsAdmins

# Try importing generative AI, but don't crash if missing locally
try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

if HAS_GENAI:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-1.5-flash')

# 1. Load Secrets
load_dotenv()
TARGET_CHAT = os.getenv("TARGET_CHAT", "https://t.me/+1tWK4j-BYC85MDVl")
TARGET_CHAT_ID = None
AUTO_DELETE_DELAY = 360
MESSAGE_DELAY = 900  # Default 15 minutes
CHAT_PAUSED = False
AI_TOPIC = None
TOTAL_MESSAGES_SENT = 0

# 2. Configure Logging & Directories
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "chat_log.txt")
STICKERS_DIR = os.path.join(SCRIPT_DIR, "stickers")

if not os.path.exists(STICKERS_DIR):
    os.makedirs(STICKERS_DIR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

accounts = {
    "acc1": {"name": "Account 1", "api_id": 2282111, "api_hash": "da58a1841a16c352a2a999171bbabcad", "session": os.getenv("ACC1_SESSION"), "bot_token": None},
    "acc2": {"name": "Account 2", "api_id": 8447214, "api_hash": "9ec5782ddd935f7e2763e5e49a590c0d", "session": os.getenv("ACC2_SESSION"), "bot_token": None},
    "acc3": {"name": "Account 3", "api_id": 22792918, "api_hash": "ff10095d2bb96d43d6eb7a7d9fc85f81", "session": os.getenv("ACC3_SESSION"), "bot_token": None},
    "acc4": {"name": "Account 4 (Bot)", "api_id": 2282111, "api_hash": "da58a1841a16c352a2a999171bbabcad", "session": os.getenv("ACC4_SESSION"), "bot_token": os.getenv("ACC4_BOT_TOKEN")}
}

# Try the massive dataset first, fallback to the sample
if os.path.exists(os.path.join(SCRIPT_DIR, "massive_dataset_5000.csv")):
    CSV_FILE = "massive_dataset_5000.csv"
else:
    CSV_FILE = "advanced_dataset_sample.csv"

conversation_script = []
clients = {}
chat_task = None
chat_memory = deque(maxlen=20) # Shared memory for AI Context

async def delete_message_later(client, chat, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat, message_id)
        logging.info(f"Deleted our own message {message_id} after {delay} seconds")
    except Exception as e:
        logging.error(f"Failed to delete message: {e}")

async def delete_other_message(message, delay):
    await asyncio.sleep(delay)
    try:
        await message.delete()
        logging.info(f"Deleted a group member's message after {delay} seconds.")
    except Exception as e:
        logging.error(f"Failed to delete member's message: {e}")

async def history_sweeper(client, chat_entity, delay_seconds):
    try:
        logging.info(f"Starting background history sweeper for messages older than {delay_seconds}s...")
        cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=delay_seconds)
        
        messages_to_delete = []
        async for msg in client.iter_messages(chat_entity, offset_date=cutoff_date):
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

async def send_dynamic_reply(client, entity, target_msg, text):
    await asyncio.sleep(random.uniform(3.0, 7.0))
    try:
        sent_msg = await client.send_message(entity, text, reply_to=target_msg)
        asyncio.create_task(delete_message_later(client, entity, sent_msg.id, AUTO_DELETE_DELAY))
        logging.info(f"Sent dynamic AI reply: {text}")
    except Exception as e:
        logging.error(f"Failed to send dynamic reply: {e}")

async def chat_loop():
    logging.info("Advanced CSV Chat sequence STARTED via remote command!")
    line_index = random.randint(0, max(0, len(conversation_script) - 1)) if conversation_script else 0
    logging.info(f"Randomly starting at line {line_index}")
    message_tracker = {}
    
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
            csv_id = row["id"]
            reply_to_csv = row["reply_to"]
            topic = row["topic"]
            emotion = row["emotion"]
            
            if speaker_key in clients:
                active_account = clients[speaker_key]
                try:
                    entity = await active_account["client"].get_entity(TARGET_CHAT_ID or TARGET_CHAT)
                    
                    reply_msg_id = None
                    if reply_to_csv and reply_to_csv in message_tracker:
                        reply_msg_id = message_tracker[reply_to_csv]
                        
                    typing_time = min(max(len(msg) * 0.05, 2.0), 5.0)
                    async with active_account["client"].action(entity, 'typing'):
                        await asyncio.sleep(typing_time)
                        
                    sent_msg = await active_account["client"].send_message(entity, msg, reply_to=reply_msg_id)
                    global TOTAL_MESSAGES_SENT
                    TOTAL_MESSAGES_SENT += 1
                    logging.info(f"[{active_account['name']}] Sent CSV: {msg}")
                    
                    if csv_id:
                        message_tracker[csv_id] = sent_msg.id
                        
                    # Add to AI Memory
                    chat_memory.append(f"{active_account['name']}: {msg}")
                    
                    asyncio.create_task(delete_message_later(active_account["client"], entity, sent_msg.id, AUTO_DELETE_DELAY))
                    
                    # 90% AI INJECTION SYSTEM (Account 4 Memory Agent)
                    if HAS_GENAI and os.getenv("GEMINI_API_KEY") and "acc4" in clients:
                        if random.random() < 0.90:  # 90% chance to jump in
                            logging.info("Account 4 (AI) jumping in based on memory...")
                            await asyncio.sleep(random.uniform(2.0, 6.0))
                            
                            prompt = "You are a casual Indian college student/professional in a Telegram group. "
                            prompt += "Reply naturally and shortly (1-2 sentences max) based on the recent chat history. "
                            prompt += "Do not use quotes or your name. Use slang naturally (bro, macha, lol, etc).\n\n"
                            
                            prompt += "Recent Chat History:\n"
                            for mem in chat_memory:
                                prompt += f"{mem}\n"
                            
                            if topic:
                                prompt += f"\nCurrent Topic vibe: {topic}"
                            if emotion:
                                prompt += f"\nCurrent Emotion vibe: {emotion}"
                                
                            try:
                                ai_model = genai.GenerativeModel("gemini-2.5-flash")
                                response = await ai_model.generate_content_async(prompt)
                                if response and response.text:
                                    bot_msg = response.text.strip().replace('"', '')
                                    bot_client = clients["acc4"]["client"]
                                    
                                    # Fix: Don't share 'entity' object across clients. Use raw ID.
                                    chat_target = TARGET_CHAT_ID or TARGET_CHAT
                                    async with bot_client.action(chat_target, 'typing'):
                                        await asyncio.sleep(min(max(len(bot_msg) * 0.05, 1.0), 3.0))
                                        
                                    bot_sent_msg = await bot_client.send_message(chat_target, bot_msg, reply_to=sent_msg.id)
                                    logging.info(f"[Account 4 (Bot)] Sent Dynamic AI Reply: {bot_msg}")
                                    chat_memory.append(f"Account 4: {bot_msg}")
                                    TOTAL_MESSAGES_SENT += 1
                                    asyncio.create_task(delete_message_later(bot_client, chat_target, bot_sent_msg.id, AUTO_DELETE_DELAY))
                            except Exception as e:
                                logging.error(f"Account 4 AI Generation failed: {e}")
                                
                except FloodWaitError as e:
                    logging.warning(f"RATE LIMITED! Pausing chat for {e.seconds} seconds.")
                    await asyncio.sleep(e.seconds + 2)
                except Exception as e:
                    logging.error(f"[{active_account['name']}] Error: {e}")

            line_index += 1
            if line_index >= len(conversation_script):
                line_index = random.randint(0, max(0, len(conversation_script) - 1)) if conversation_script else 0
                logging.info(f"Reached end of CSV. Randomly starting at line {line_index}") 
                message_tracker.clear()
                
            if MESSAGE_DELAY is not None:
                delay = MESSAGE_DELAY
            elif random.random() < 0.3:
                delay = random.uniform(1.0, 2.5)
            else:
                delay = random.uniform(3.0, 6.0)
                
            logging.info(f"Waiting {delay:.1f}s before next message...")
            await asyncio.sleep(delay)
            
    except asyncio.CancelledError:
        logging.info("Chat sequence CANCELLED via remote command!")
        raise

# --- DUMMY WEB SERVER ---
async def health_check(request):
    return web.Response(text="GenZetaBot (Advanced Dataset) is running safely 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Web server started on port {port}")

async def main():
    if not accounts["acc1"]["session"]:
        logging.error("String Sessions not found in Environment Variables!")
        return

    print("\n" + "="*50)
    print("   GENZETABOT - ADVANCED DATASET EDITION")
    print("="*50)
    
    await start_web_server()
    
    csv_filename = os.path.join(SCRIPT_DIR, CSV_FILE)
    global conversation_script

    if os.path.exists(csv_filename):
        # 11-column mapping
        sender_mapping = {
            "Account1": "acc1",
            "Account2": "acc2",
            "Account3": "acc3",
            "Account4": "acc4",
        }
        with open(csv_filename, mode="r", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            for row in reader:
                raw_sender = row.get("sender", "").strip()
                sender = sender_mapping.get(raw_sender, raw_sender)
                message = row.get("message", "").strip()
                if sender in accounts and message:
                    conversation_script.append({
                        "id": row.get("message_id", row.get("id", "")).strip(),
                        "sender": sender,
                        "message": message,
                        "reply_to": row.get("reply_to", "").strip(),
                        "topic": row.get("topic", "").strip(),
                        "emotion": row.get("emotion", "").strip()
                    })
        logging.info(f"Loaded {len(conversation_script)} messages from {CSV_FILE}.")
    else:
        logging.error(f"'{CSV_FILE}' not found!")
        return

    for acc_key, acc_data in accounts.items():
        if not acc_data["session"] and not acc_data["bot_token"]:
            continue
            
        if acc_data["session"]:
            client = TelegramClient(StringSession(acc_data["session"]), acc_data["api_id"], acc_data["api_hash"])
            await client.connect()
        else:
            client = TelegramClient(StringSession(), acc_data["api_id"], acc_data["api_hash"])
            await client.start(bot_token=acc_data["bot_token"])

        if not await client.is_user_authorized():
            logging.error(f"{acc_data['name']} credentials invalid! Cannot connect.")
            continue
        clients[acc_key] = {"client": client, "name": acc_data["name"]}
        
    if not clients:
        logging.error("No valid accounts connected! Exiting.")
        return
        
    logging.info(f"{len(clients)} User Accounts Connected Safely!")

    if "acc1" in clients:
        try:
            entity = await clients["acc1"]["client"].get_entity(TARGET_CHAT)
            global TARGET_CHAT_ID
            TARGET_CHAT_ID = entity.id
        except Exception as e:
            logging.error(f"Failed to resolve TARGET_CHAT: {e}")
    
    if "acc4" not in clients:
        logging.error("Account 4 (Bot) is NOT connected! Exiting.")
        return
        
    host_client = clients["acc4"]["client"]
    listen_target = TARGET_CHAT_ID or TARGET_CHAT
    logging.info("Account 4 (Bot) is now the active Command Controller.")

    @host_client.on(events.NewMessage(pattern=r'(?i)^/(setspeed|topic|stats|pause|resume|purge)(?:\s+(.+))?', chats=listen_target))
    async def admin_command_handler(event):
        global MESSAGE_DELAY, CHAT_PAUSED, AI_TOPIC, AUTO_DELETE_DELAY, TOTAL_MESSAGES_SENT
        try:
            sender = await event.get_sender()
            if not sender or sender.id != 5429173364: return 
        except Exception: return

        cmd = event.pattern_match.group(1).lower()
        args = event.pattern_match.group(2)
        
        if cmd == "setspeed":
            if not args:
                await event.reply("Usage: /setspeed <time> (e.g. 15m, 1h) or /setspeed auto")
                return
            args = args.lower().strip()
            if args == "auto":
                MESSAGE_DELAY = None
                await event.reply("Speed set to AUTO (Fast Human-like random bursts).")
            else:
                try:
                    if args.endswith('s'): MESSAGE_DELAY = int(args[:-1])
                    elif args.endswith('m'): MESSAGE_DELAY = int(args[:-1]) * 60
                    elif args.endswith('h'): MESSAGE_DELAY = int(args[:-1]) * 3600
                    else: MESSAGE_DELAY = int(args)
                    await event.reply(f"Speed locked to {MESSAGE_DELAY} seconds per message.")
                except ValueError:
                    await event.reply("Invalid format.")
        elif cmd == "topic":
            if not args:
                AI_TOPIC = None
                await event.reply("AI Topic cleared.")
            else:
                AI_TOPIC = args.strip()
                await event.reply(f"AI Topic set to: {AI_TOPIC}.")
        elif cmd == "pause":
            CHAT_PAUSED = True
            await event.reply("Chat automation PAUSED.")
        elif cmd == "resume":
            CHAT_PAUSED = False
            await event.reply("Chat automation RESUMED.")
        elif cmd == "stats":
            speed_text = "AUTO" if MESSAGE_DELAY is None else f"{MESSAGE_DELAY}s"
            status = "PAUSED ⏸️" if CHAT_PAUSED else "RUNNING ▶️"
            topic = AI_TOPIC if AI_TOPIC else "None"
            await event.reply(f"📊 **Bot Stats**\n\nStatus: {status}\nSpeed: {speed_text}\nAuto-Delete: {AUTO_DELETE_DELAY}s\nCurrent AI Topic: {topic}\nMessages Sent: {TOTAL_MESSAGES_SENT}")
        elif cmd == "purge":
            await event.reply("🗑️ Sweeping all bot and AI messages from this chat...")
            try:
                our_ids = [(await acc["client"].get_me()).id for acc in clients.values()]
                deleted_count = 0
                messages_to_delete = []
                async for msg in host_client.iter_messages(listen_target):
                    if msg.sender_id in our_ids:
                        messages_to_delete.append(msg.id)
                        if len(messages_to_delete) >= 100:
                            await host_client.delete_messages(listen_target, messages_to_delete)
                            deleted_count += len(messages_to_delete)
                            messages_to_delete.clear()
                            await asyncio.sleep(2.0)
                if messages_to_delete:
                    await host_client.delete_messages(listen_target, messages_to_delete)
                    deleted_count += len(messages_to_delete)
                await event.respond(f"✅ Successfully scrubbed {deleted_count} messages.")
            except Exception as e:
                await event.respond(f"❌ Failed to purge messages: {e}")

    @host_client.on(events.NewMessage(pattern=r'(?i)^/setdelete(?:\s+(.+))?', chats=listen_target))
    async def set_delete_handler(event):
        global AUTO_DELETE_DELAY
        try:
            sender = await event.get_sender()
            if not sender or sender.id != 5429173364: return 
        except Exception: return

        time_str = event.pattern_match.group(1)
        if not time_str: return
            
        time_str = time_str.lower().strip()
        try:
            if time_str.endswith('s'): new_delay = int(time_str[:-1])
            elif time_str.endswith('m'): new_delay = int(time_str[:-1]) * 60
            elif time_str.endswith('h'): new_delay = int(time_str[:-1]) * 3600
            else: new_delay = int(time_str)
                
            AUTO_DELETE_DELAY = new_delay
            await event.reply(f"✅ Auto-delete set to {AUTO_DELETE_DELAY}s! Starting sweep...")
            asyncio.create_task(history_sweeper(host_client, listen_target, AUTO_DELETE_DELAY))
        except ValueError:
            pass

    @host_client.on(events.NewMessage(pattern=r'(?i)^/(lockon|lockoff)', chats=listen_target))
    async def handler(event):
        global chat_task
        try:
            sender = await event.get_sender()
            if not sender or sender.id != 5429173364: return 
        except Exception: return

        command = event.pattern_match.group(1).lower()
        if command == 'lockon':
            if not (chat_task and not chat_task.done()):
                chat_task = asyncio.create_task(chat_loop())
                await event.delete()
        elif command == 'lockoff':
            if chat_task and not chat_task.done():
                chat_task.cancel()
                chat_task = None
                await event.delete()

    @host_client.on(events.NewMessage(chats=entity))
    async def auto_delete_handler(event):
        if event.raw_text and event.raw_text.lower().startswith(("/lockon", "/lockoff", "/setdelete")):
            return
            
        try:
            sender = await event.get_sender()
            if not sender: return
                
            our_ids = [(await acc["client"].get_me()).id for acc in clients.values()]
                
            if sender.id not in our_ids:
                asyncio.create_task(delete_other_message(event.message, AUTO_DELETE_DELAY))
                
                # Add real human message to AI Memory so Account 4 can read it!
                msg_text = event.raw_text
                if msg_text:
                    username = sender.username or sender.first_name or "Human"
                    chat_memory.append(f"{username}: {msg_text}")

                if event.message.is_reply:
                    try:
                        reply_msg = await event.message.get_reply_message()
                        acc4_id = (await clients["acc4"]["client"].get_me()).id
                        if reply_msg and reply_msg.sender_id == acc4_id:
                            prompt = f"You are chatting in a group. A user replied to your message. Reply casually (1-2 short sentences) to them: '{event.raw_text}'"
                            ai_model = genai.GenerativeModel("gemini-2.5-flash")
                            response = await ai_model.generate_content_async(prompt)
                            if response and response.text:
                                asyncio.create_task(send_dynamic_reply(clients["acc4"]["client"], entity, event.message, response.text.strip()))
                    except Exception:
                        pass
        except Exception as e:
            pass

    logging.info("Listening for /lockon and /lockoff commands in the group...")
    
    try:
        await host_client.run_until_disconnected()
    except KeyboardInterrupt:
        pass
    finally:
        print("Disconnecting...")
        for acc in clients.values():
            await acc["client"].disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
