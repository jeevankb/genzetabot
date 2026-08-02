import asyncio
import os
import csv
import random
import logging
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
from telethon.tl.types import ChannelParticipantsAdmins

# 1. Load Secrets
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", 2282111))
API_HASH = os.getenv("API_HASH", "da58a1841a16c352a2a999171bbabcad")
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

CSV_FILE = "anime_group_chat_10000.csv"
conversation_script = []
chat_task = None

client = TelegramClient(os.path.join(SCRIPT_DIR, "bot_session"), API_ID, API_HASH)

async def delete_message_later(entity, message_id, delay=300):
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
            msg = row["message"]
            csv_id = row["id"]
            reply_to_csv = row["reply_to"]
            reaction_emoji = row["reaction"]
            
            try:
                entity = await client.get_entity(TARGET_CHAT)
                
                reply_msg_id = None
                if reply_to_csv and reply_to_csv in message_tracker:
                    reply_msg_id = message_tracker[reply_to_csv]
                
                typing_time = min(max(len(msg) * 0.05, 2.0), 5.0)
                async with client.action(entity, 'typing'):
                    await asyncio.sleep(typing_time)
                    
                sent_msg = await client.send_message(entity, msg, reply_to=reply_msg_id)
                logging.info(f"Sent: {msg}")
                
                if csv_id:
                    message_tracker[csv_id] = sent_msg.id
                    
                asyncio.create_task(delete_message_later(entity, sent_msg.id, 300))
                
                if reaction_emoji and reply_msg_id:
                    try:
                        await client(SendReactionRequest(
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
                        sent_sticker = await client.send_file(entity, sticker_path)
                        asyncio.create_task(delete_message_later(entity, sent_sticker.id, 300))

            except FloodWaitError as e:
                logging.warning(f"RATE LIMITED! Pausing chat for {e.seconds} seconds.")
                await asyncio.sleep(e.seconds + 2)
                continue
            except Exception as e:
                logging.error(f"Error: {e}")

            line_index += 1
            if line_index >= len(conversation_script):
                line_index = 0 
                message_tracker.clear() 
                
            delay = random.uniform(15.0, 18.0)
            logging.info(f"Waiting {delay:.1f} seconds...")
            await asyncio.sleep(delay)
            
    except asyncio.CancelledError:
        logging.info("Chat sequence CANCELLED via remote command!")
        raise

async def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN is not set in the .env file! Exiting.")
        return

    print("\n" + "="*40)
    print("   GENZETABOT - BOT TOKEN EDITION")
    print("="*40)
    
    csv_filename = os.path.join(SCRIPT_DIR, CSV_FILE)
    global conversation_script

    if os.path.exists(csv_filename):
        with open(csv_filename, mode="r", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            for row in reader:
                message = row.get("message", "").strip()
                if message:
                    conversation_script.append({
                        "id": row.get("id", "").strip(),
                        "message": message,
                        "reply_to": row.get("reply_to", "").strip(),
                        "reaction": row.get("reaction", "").strip()
                    })
        logging.info(f"Loaded {len(conversation_script)} messages.")
    else:
        logging.error(f"'{CSV_FILE}' not found!")
        return

    # Connect using Bot Token
    await client.start(bot_token=BOT_TOKEN)
    logging.info("Bot successfully authenticated!")

    entity = await client.get_entity(TARGET_CHAT)

    @client.on(events.NewMessage(chats=entity, pattern=r'(?i)^/(start|stop)'))
    async def handler(event):
        global chat_task
        
        # Security Check: Ensure the sender is an Admin of the group
        try:
            sender = await event.get_sender()
            is_admin = False
            
            participants = await client.get_participants(entity, filter=ChannelParticipantsAdmins)
            admin_ids = [p.id for p in participants]
            if sender.id in admin_ids:
                is_admin = True
                
            if not is_admin:
                return 
        except Exception:
            return

        command = event.pattern_match.group(1).lower()
        
        if command == 'start':
            if chat_task and not chat_task.done():
                return
            else:
                chat_task = asyncio.create_task(chat_loop())
                logging.info(f"Admin {sender.id} sent /start")
                await asyncio.sleep(2)
                await event.delete()
                
        elif command == 'stop':
            if chat_task and not chat_task.done():
                chat_task.cancel()
                chat_task = None
                logging.info(f"Admin {sender.id} sent /stop")
                await asyncio.sleep(2)
                await event.delete()

    logging.info("Listening for /start and /stop commands in the group...")
    
    try:
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        pass
    finally:
        print("Disconnecting...")
        await client.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
