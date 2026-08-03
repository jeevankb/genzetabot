import asyncio
import os
import csv
import random
import logging
from aiohttp import web
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
from telethon.tl.types import ChannelParticipantsAdmins

# 1. Load Secrets
load_dotenv()
TARGET_CHAT = os.getenv("TARGET_CHAT", "https://t.me/+1tWK4j-BYC85MDVl")

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

async def delete_message_later(client, entity, message_id, delay=300):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(entity, [message_id])
        logging.info(f"Auto-deleted message {message_id}")
    except Exception:
        pass

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
                    
                    typing_time = min(max(len(msg) * 0.05, 2.0), 5.0)
                    async with active_account["client"].action(entity, 'typing'):
                        await asyncio.sleep(typing_time)
                        
                    sent_msg = await active_account["client"].send_message(entity, msg, reply_to=reply_msg_id)
                    logging.info(f"[{active_account['name']}] Sent: {msg}")
                    
                    if csv_id:
                        message_tracker[csv_id] = sent_msg.id
                        
                    asyncio.create_task(delete_message_later(active_account["client"], entity, sent_msg.id, 300))
                    
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
                
            # Dynamic Human-Like Delay
            chance = random.random()
            if chance < 0.2:
                # 20% chance of a slow, thoughtful response
                delay = random.uniform(30.0, 60.0)
                logging.info(f"Taking a long break... Waiting {delay:.1f} seconds.")
            elif chance < 0.4:
                # 20% chance of rapid-fire response
                delay = random.uniform(2.0, 5.0)
                logging.info(f"Rapid response... Waiting {delay:.1f} seconds.")
            else:
                # 60% chance of normal conversation speed
                delay = random.uniform(8.0, 15.0)
                logging.info(f"Normal typing speed... Waiting {delay:.1f} seconds.")
                
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

    # 4. Setup the Listener on Account 1 (It acts as the 'host' for commands)
    host_client = clients["acc1"]["client"]
    entity = await host_client.get_entity(TARGET_CHAT)

    @host_client.on(events.NewMessage(chats=entity, pattern=r'(?i)^/(lockon|lockoff)'))
    async def handler(event):
        global chat_task
        
        # Security Check: Ensure the sender is an Admin of the group
        try:
            sender = await event.get_sender()
            is_me = sender.is_self
            is_admin = False
            
            participants = await host_client.get_participants(entity, filter=ChannelParticipantsAdmins)
            admin_ids = [p.id for p in participants]
            if sender.id in admin_ids:
                is_admin = True
                
            if not (is_me or is_admin):
                return 
        except Exception:
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
