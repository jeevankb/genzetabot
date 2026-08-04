import asyncio
import os
import csv
import random
import logging
import re
from collections import defaultdict
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
    model = genai.GenerativeModel('gemini-pro')

# 1. Load Secrets
load_dotenv()
TARGET_CHAT = os.getenv("TARGET_CHAT", "https://t.me/+1tWK4j-BYC85MDVl")
AUTO_DELETE_DELAY = 360

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
    "acc4": {"name": "Account 4 (Bot)", "api_id": 2282111, "api_hash": "da58a1841a16c352a2a999171bbabcad", "session": None, "bot_token": os.getenv("ACC4_BOT_TOKEN")}
}

CSV_FILE = "anime_group_chat_10000.csv"
conversation_script = []
clients = {}
chat_task = None

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

async def send_dynamic_reply(client, entity, target_msg, text):
    # Wait a few seconds to look like a human typing
    await asyncio.sleep(random.uniform(3.0, 7.0))
    try:
        sent_msg = await client.send_message(entity, text, reply_to=target_msg)
        # Auto delete the AI message after global delay
        asyncio.create_task(delete_message_later(client, entity, sent_msg.id, AUTO_DELETE_DELAY))
        logging.info(f"Sent dynamic reply: {text}")
    except Exception as e:
        logging.error(f"Failed to send dynamic reply: {e}")

async def chat_loop():
    logging.info("Chat sequence STARTED via remote command!")
    line_index = 0
    message_tracker = {}
    
    try:
        while True:
            if not conversation_script:
                logging.error("The conversation script is empty! Stopping.")
                break
                
            row = conversation_script[line_index]
            speaker_key = row["sender"]
            msg = row["message"]
            csv_id = row["id"]
            reply_to_csv = row["reply_to"]
            reaction_emoji = row["reaction"]
            
            if speaker_key in clients:
                active_account = clients[speaker_key]
                try:
                    entity = await active_account["client"].get_entity(TARGET_CHAT)
                    
                    reply_msg_id = None
                    if reply_to_csv and reply_to_csv in message_tracker:
                        reply_msg_id = message_tracker[reply_to_csv]
                        
                    # 16-Second Safety Delay specifically for the Bot Account (Account 4)
                    if speaker_key == "acc4":
                        logging.info("Bot account (acc4) is up next. Waiting 16s for safety...")
                        await asyncio.sleep(16.0)
                        
                        # Generate Conversational AI response based on previous message
                        if HAS_GENAI and os.getenv("GEMINI_API_KEY") and last_sent_text:
                            try:
                                ai_model = genai.GenerativeModel("gemini-1.5-flash")
                                prompt = f"You are an anime fan in a group chat. Respond naturally, casually, and shortly (1 sentence max) to this group message: '{last_sent_text}'"
                                response = await ai_model.generate_content_async(prompt)
                                if response and response.text:
                                    msg = response.text.strip()
                            except Exception as e:
                                logging.error(f"Failed to generate conversational AI msg: {e}")
                                msg = "Haha yeah exactly!"
                        else:
                            msg = "I completely agree!"
                    else:
                        last_sent_text = msg
                    
                    typing_time = min(max(len(msg) * 0.05, 2.0), 5.0)
                    async with active_account["client"].action(entity, 'typing'):
                        await asyncio.sleep(typing_time)
                        
                    sent_msg = await active_account["client"].send_message(entity, msg, reply_to=reply_msg_id)
                    logging.info(f"[{active_account['name']}] Sent: {msg}")
                    
                    if csv_id:
                        message_tracker[csv_id] = sent_msg.id
                    
                    # Delete message after global setting
                    asyncio.create_task(delete_message_later(active_account["client"], entity, sent_msg.id, AUTO_DELETE_DELAY))
                    
                    if reaction_emoji and reply_msg_id:
                        try:
                            await active_account["client"](SendReactionRequest(
                                peer=entity,
                                msg_id=reply_msg_id,
                                reaction=[ReactionEmoji(emoticon=reaction_emoji)]
                            ))
                        except Exception:
                            pass

                    if random.random() < 0.15:
                        available_stickers = [f for f in os.listdir(STICKERS_DIR) if f.endswith(('.webp', '.png', '.jpg', '.tgs'))]
                        if available_stickers:
                            chosen_sticker = random.choice(available_stickers)
                            sticker_path = os.path.join(STICKERS_DIR, chosen_sticker)
                            await asyncio.sleep(random.uniform(1.0, 3.0))
                            sent_sticker = await active_account["client"].send_file(entity, sticker_path)
                            asyncio.create_task(delete_message_later(active_account["client"], entity, sent_sticker.id, 300))

                except FloodWaitError as e:
                    logging.warning(f"RATE LIMITED! Pausing chat for {e.seconds} seconds.")
                    await asyncio.sleep(e.seconds + 2)
                    continue
                except Exception as e:
                    logging.error(f"[{active_account['name']}] Error: {e}")

            line_index += 1
            if line_index >= len(conversation_script):
                line_index = 0 
                message_tracker.clear() 
                
            # Simulate an active online group ("little spam")
            if random.random() < 0.3:
                # 30% chance they are typing very fast over each other
                delay = random.uniform(1.0, 2.5)
            else:
                # 70% chance for a normal fast conversation
                delay = random.uniform(3.0, 6.0)
                
            logging.info(f"Waiting {delay:.1f}s before next message...")
            await asyncio.sleep(delay)
            
    except asyncio.CancelledError:
        logging.info("Chat sequence CANCELLED via remote command!")
        raise

# --- DUMMY WEB SERVER FOR FREE CLOUD HOSTING (RENDER/KOYEB) ---
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
    logging.info(f"Web server started on port {port} for Cloud Health Checks.")

async def main():
    if not accounts["acc1"]["session"]:
        logging.error("String Sessions not found in Environment Variables!")
        logging.error("Please run generate_sessions.py to get your strings.")
        return

    print("\n" + "="*50)
    print("   GENZETABOT - CLOUD MASTER-SLAVE EDITION")
    print("="*50)
    
    # 1. Start the Health Check Server so Render/Koyeb doesn't crash the bot
    await start_web_server()
    
    # 2. Load the CSV
    csv_filename = os.path.join(SCRIPT_DIR, CSV_FILE)
    global conversation_script

    if os.path.exists(csv_filename):
        with open(csv_filename, mode="r", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            for row in reader:
                sender = row.get("sender", "").strip()
                message = row.get("message", "").strip()
                if sender in accounts and message:
                    conversation_script.append({
                        "id": row.get("id", "").strip(),
                        "sender": sender,
                        "message": message,
                        "reply_to": row.get("reply_to", "").strip(),
                        "reaction": row.get("reaction", "").strip()
                    })
        logging.info(f"Loaded {len(conversation_script)} messages.")
    else:
        logging.error(f"'{CSV_FILE}' not found!")
        return

    # 3. Connect User Accounts and Bot Accounts
    for acc_key, acc_data in accounts.items():
        if not acc_data["session"] and not acc_data["bot_token"]:
            logging.warning(f"Skipping {acc_data['name']} because session/token is missing.")
            continue
            
        if acc_data["session"]:
            # Normal User Account
            client = TelegramClient(StringSession(acc_data["session"]), acc_data["api_id"], acc_data["api_hash"])
            await client.connect()
        else:
            # Bot Token Account
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

    # 4. Setup the Listener on the first available account (Acts as the 'host')
    if "acc1" in clients:
        host_client = clients["acc1"]["client"]
    else:
        host_client = list(clients.values())[0]["client"]
        logging.warning("Account 1 failed to connect. Using another account as the command listener.")
        
    entity = await host_client.get_entity(TARGET_CHAT)

    @host_client.on(events.NewMessage(pattern=r'(?i)^/setdelete(?:\s+(.+))?', chats=entity))
    async def set_delete_handler(event):
        global AUTO_DELETE_DELAY
        try:
            sender = await event.get_sender()
            if not sender or sender.id != 5429173364:
                logging.warning(f"Unauthorized /setdelete attempt from User ID: {sender.id if sender else 'Unknown'}")
                return 
        except Exception as e:
            return

        time_str = event.pattern_match.group(1)
        if not time_str:
            await event.reply("Usage: /setdelete <time> (e.g. 1s, 45m, 24h)")
            return
            
        time_str = time_str.lower().strip()
        try:
            if time_str.endswith('s'):
                new_delay = int(time_str[:-1])
            elif time_str.endswith('m'):
                new_delay = int(time_str[:-1]) * 60
            elif time_str.endswith('h'):
                new_delay = int(time_str[:-1]) * 3600
            else:
                new_delay = int(time_str) # Default to seconds
                
            if new_delay < 1 or new_delay > 86400:
                await event.reply("❌ Please set a time between 1 second and 24 hours (86400s).")
                return
                
            AUTO_DELETE_DELAY = new_delay
            await event.reply(f"✅ Auto-delete time successfully updated to {AUTO_DELETE_DELAY} seconds!")
            logging.info(f"Auto-delete time changed to {AUTO_DELETE_DELAY}s by Admin.")
        except ValueError:
            await event.reply("❌ Invalid format. Please use a number followed by s, m, or h. (e.g. 10s, 5m, 2h)")

    @host_client.on(events.NewMessage(pattern=r'(?i)^/(lockon|lockoff)$', chats=entity))
    async def handler(event):
        global chat_task
        
        # Security Check: ONLY allow User ID 5429173364 (@Merlin_hermis)
        try:
            sender = await event.get_sender()
            if not sender:
                return
            if sender.id != 5429173364:
                logging.warning(f"Unauthorized /lockon attempt from User ID: {sender.id}. Ignoring.")
                return 
        except Exception as e:
            logging.error(f"Error checking sender ID: {e}")
            return

        command = event.pattern_match.group(1).lower()
        
        if command == 'lockon':
            if chat_task and not chat_task.done():
                return
            else:
                chat_task = asyncio.create_task(chat_loop())
                logging.info(f"Admin {sender.id} sent /lockon")
                await asyncio.sleep(2)
                await event.delete()
                
        elif command == 'lockoff':
            if chat_task and not chat_task.done():
                chat_task.cancel()
                chat_task = None
                logging.info(f"Admin {sender.id} sent /lockoff")
                await asyncio.sleep(2)
                await event.delete()

    @host_client.on(events.NewMessage(chats=entity))
    async def auto_delete_handler(event):
        # Ignore our stealth commands to prevent double deletion logic
        if event.raw_text and event.raw_text.lower().startswith(("/lockon", "/lockoff", "/setdelete")):
            return
            
        try:
            sender = await event.get_sender()
            if not sender:
                return
                
            # Get IDs of all our connected accounts
            our_ids = []
            for acc_data in clients.values():
                our_ids.append((await acc_data["client"].get_me()).id)
                
            # If the sender is NOT one of our accounts
            if sender.id not in our_ids:
                # 1. Schedule deletion after global setting
                asyncio.create_task(delete_other_message(event.message, AUTO_DELETE_DELAY))
                
                msg_text = event.raw_text.lower() if event.raw_text else ""
                if not msg_text:
                    return

                # 2. Contextual Emoji Reaction (20% chance)
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
                            big=True,
                            add_to_recent=True,
                            reaction=[ReactionEmoji(emoticon=emoji)]
                        ))
                    except Exception as e:
                        logging.error(f"Failed to send reaction: {e}")
                        
                # 3. Conversational AI Reply to Real Users
                is_reply_to_bot = False
                if event.message.is_reply:
                    try:
                        reply_msg = await event.message.get_reply_message()
                        if "acc4" in clients:
                            acc4_id = (await clients["acc4"]["client"].get_me()).id
                            if reply_msg and reply_msg.sender_id == acc4_id:
                                is_reply_to_bot = True
                    except Exception:
                        pass
                        
                if is_reply_to_bot and HAS_GENAI and os.getenv("GEMINI_API_KEY"):
                    try:
                        prompt = f"You are chatting in a group. A user replied to your message. Reply casually (1-2 short sentences) to them: '{event.raw_text}'"
                        ai_model = genai.GenerativeModel("gemini-1.5-flash")
                        response = await ai_model.generate_content_async(prompt)
                        if response and response.text:
                            asyncio.create_task(send_dynamic_reply(clients["acc4"]["client"], entity, event.message, response.text.strip()))
                            return # Stop processing further keywords
                    except Exception as e:
                        logging.error(f"Failed to generate reply to real user: {e}")

                # 4. Keyword Response System (if no direct reply)
                keyword_replies = {
                    r'\b(hi|hello|hey|sup)\b': ["Hey there!", "Hi!", "Hello!"],
                    r'\b(bye|cya|gn)\b': ["See ya!", "Bye!"],
                    r'\b(anime|manga)\b': ["I love anime!", "What's your favorite anime?"]
                }
                
                responded = False
                for pattern, replies in keyword_replies.items():
                    if re.search(pattern, msg_text):
                        reply_acc = random.choice(list(clients.values()))
                        reply_text = random.choice(replies)
                        asyncio.create_task(send_dynamic_reply(reply_acc["client"], entity, event.message, reply_text))
                        responded = True
                        break
                        
                # 3. AI Response (if no keyword matched, and GEMINI API KEY is present)
                if not responded and HAS_GENAI and os.getenv("GEMINI_API_KEY"):
                    # 30% chance to reply, or 100% if it's a question
                    if "?" in msg_text or random.random() < 0.3:
                        try:
                            genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
                            model = genai.GenerativeModel("gemini-1.5-flash")
                            prompt = f"You are a casual anime fan chatting in a Telegram group. Keep your response very short (1-2 sentences), natural, lowercase, and human-like. Reply to this message: {msg_text}"
                            
                            response = await model.generate_content_async(prompt)
                            if response and response.text:
                                reply_acc = random.choice(list(clients.values()))
                                asyncio.create_task(send_dynamic_reply(reply_acc["client"], entity, event.message, response.text.strip()))
                        except Exception as e:
                            logging.error(f"AI Generation failed: {e}")
                            
        except Exception as e:
            logging.error(f"Error in auto_delete_handler: {e}")

    logging.info("Listening for /lockon and /lockoff commands in the group...")
    
    try:
        await host_client.run_until_disconnected()
    except KeyboardInterrupt:
        pass
    finally:
        print("Disconnecting...")
        for key, acc in clients.items():
            await acc["client"].disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
