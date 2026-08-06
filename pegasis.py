import asyncio
import os
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

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if HAS_GENAI:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

API_ID = int(os.getenv("API_ID", 22692791))
API_HASH = os.getenv("API_HASH", "2c5a044f509e51c6b12a8656ee5dce0e")
TARGET_CHAT = os.getenv("TARGET_CHAT", "https://t.me/+1tWK4j-BYC85MDVl")
TARGET_CHAT_ID = None

# Global Admin States
AUTO_DELETE_DELAY = 360
MESSAGE_DELAY = 900  # 15 min default
CHAT_PAUSED = False
AI_TOPIC = None
TOTAL_MESSAGES_SENT = 0

chat_task = None
clients = {}
chat_memory = deque(maxlen=20)

# Persona Configurations
PERSONAS = {
    "acc1": "You are a highly sarcastic, funny person in a group chat. You use modern internet slang and always mock your friends jokingly. Keep responses short (1-2 sentences). Do not use emojis.",
    "acc2": "You are a deeply philosophical and somewhat dramatic person. You take things too seriously but mean well. Keep responses short (1-2 sentences). You love using exactly one heart or fire emoji.",
    "acc3": "You are a chaotic, hyperactive gamer who types in all lowercase. You are obsessed with anime and crypto. Keep responses very short and use 'lmao' or 'lol' often.",
    "acc4": "You are the calm, rational voice of reason in the group. You try to keep conversations on track and politely disagree with people. Keep it short."
}

def build_ai_prompt(account_key):
    persona = PERSONAS.get(account_key, "You are a casual friend in a group chat.")
    prompt = f"{persona}\n\nHere is the recent chat history:\n"
    for mem in chat_memory:
        prompt += f"{mem}\n"
    
    if AI_TOPIC:
        prompt += f"\nCritically important: Subtly try to steer the conversation towards: {AI_TOPIC}\n"
    
    prompt += "\nNow, generate your next response to the group. Reply naturally. Do not include your name or quotes in the output."
    return prompt

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

async def delete_other_message(message, delay):
    await asyncio.sleep(delay)
    try:
        await message.delete()
        logging.info(f"Deleted a group member's message after {delay} seconds.")
    except Exception as e:
        logging.error(f"Failed to delete member's message: {e}")

async def learning_chat_loop():
    global TOTAL_MESSAGES_SENT
    logging.info("Pegasis Learning Agent System STARTED via remote command!")
    
    if not HAS_GENAI:
        logging.error("google.generativeai is not installed or API key missing. Cannot run Pegasis.")
        return
        
    model = genai.GenerativeModel("gemini-1.5-pro")
    active_keys = list(clients.keys())
    
    if not active_keys:
        logging.error("No accounts connected. Exiting loop.")
        return

    entity = await clients["acc1"]["client"].get_entity(TARGET_CHAT_ID or TARGET_CHAT)
    
    try:
        while True:
            if CHAT_PAUSED:
                await asyncio.sleep(2)
                continue
                
            # Pick a random account to speak
            chosen_key = random.choice(active_keys)
            active_account = clients[chosen_key]
            client = active_account["client"]
            name = active_account["name"]
            
            # Generate AI Response based on memory
            prompt = build_ai_prompt(chosen_key)
            try:
                response = model.generate_content(prompt)
                msg_text = response.text.strip().replace('"', '')
            except Exception as e:
                logging.error(f"AI Generation failed: {e}")
                msg_text = "I don't know what to say right now."
                
            # Send the message
            try:
                async with client.action(entity, 'typing'):
                    await asyncio.sleep(random.uniform(2.0, 5.0))
                
                sent_msg = await client.send_message(entity, msg_text)
                TOTAL_MESSAGES_SENT += 1
                logging.info(f"[{name}] Generated and Sent: {msg_text}")
                
                # Add to shared memory
                chat_memory.append(f"{name}: {msg_text}")
                
            except FloodWaitError as e:
                logging.warning(f"RATE LIMITED! Pausing chat for {e.seconds} seconds.")
                await asyncio.sleep(e.seconds + 2)
            except Exception as e:
                logging.error(f"[{name}] Error sending message: {e}")

            # Sleep delay
            if MESSAGE_DELAY is not None:
                delay = MESSAGE_DELAY
            elif random.random() < 0.3:
                delay = random.uniform(1.0, 2.5)
            else:
                delay = random.uniform(3.0, 6.0)
                
            await asyncio.sleep(delay)
            
    except asyncio.CancelledError:
        logging.info("Pegasis Chat Loop stopped by admin.")
    except Exception as e:
        logging.error(f"Critical error in Pegasis loop: {e}")

async def start_bot():
    global TARGET_CHAT_ID, chat_task
    
    # Connection Logic
    account_configs = [
        {"name": "acc1", "env_var": "SESSION_STRING_1"},
        {"name": "acc2", "env_var": "SESSION_STRING_2"},
        {"name": "acc3", "env_var": "SESSION_STRING_3"},
        {"name": "acc4", "env_var": "SESSION_STRING_4"},
    ]
    
    for cfg in account_configs:
        session_str = os.getenv(cfg["env_var"])
        bot_token = os.getenv("BOT_TOKEN") if cfg["name"] == "acc4" else None
        
        if session_str:
            client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
            await client.start()
            clients[cfg["name"]] = {"client": client, "name": cfg["name"]}
            logging.info(f"Connected {cfg['name']} via Session String.")
        elif bot_token and cfg["name"] == "acc4":
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.start(bot_token=bot_token)
            clients[cfg["name"]] = {"client": client, "name": cfg["name"]}
            logging.info(f"Connected {cfg['name']} via Bot Token.")
            
    if "acc1" in clients:
        try:
            entity = await clients["acc1"]["client"].get_entity(TARGET_CHAT)
            TARGET_CHAT_ID = entity.id
        except Exception as e:
            logging.error(f"Failed to resolve TARGET_CHAT: {e}")
            
    if "acc4" not in clients:
        logging.error("Account 4 (Bot) is NOT connected! Exiting.")
        return
        
    host_client = clients["acc4"]["client"]
    listen_target = TARGET_CHAT_ID or TARGET_CHAT

    # Listen to real humans to build memory & auto-delete
    @host_client.on(events.NewMessage(chats=listen_target))
    async def group_listener(event):
        if event.raw_text and event.raw_text.lower().startswith(("/", "!")):
            return
            
        try:
            sender = await event.get_sender()
            if not sender: return
            
            our_ids = [ (await acc["client"].get_me()).id for acc in clients.values() ]
            if sender.id not in our_ids:
                asyncio.create_task(delete_other_message(event.message, AUTO_DELETE_DELAY))
                
                # Add real human message to memory so bots learn
                username = sender.username or sender.first_name or "Human"
                chat_memory.append(f"{username}: {event.raw_text}")
        except Exception:
            pass

    @host_client.on(events.NewMessage(pattern=r'(?i)^/(setspeed|topic|stats|pause|resume)(?:\s+(.+))?', chats=listen_target))
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
                await event.reply(f"AI Topic set to: {AI_TOPIC}")
        elif cmd == "pause":
            CHAT_PAUSED = True
            await event.reply("Pegasis PAUSED.")
        elif cmd == "resume":
            CHAT_PAUSED = False
            await event.reply("Pegasis RESUMED.")
        elif cmd == "stats":
            speed_text = "AUTO" if MESSAGE_DELAY is None else f"{MESSAGE_DELAY}s"
            status = "PAUSED ⏸️" if CHAT_PAUSED else "RUNNING ▶️"
            topic = AI_TOPIC if AI_TOPIC else "None"
            await event.reply(f"📊 **Pegasis Stats**\nStatus: {status}\nSpeed: {speed_text}\nAuto-Delete: {AUTO_DELETE_DELAY}s\nTopic: {topic}\nMessages Sent: {TOTAL_MESSAGES_SENT}")

    @host_client.on(events.NewMessage(pattern=r'(?i)^/setdelete(?:\s+(.+))?', chats=listen_target))
    async def set_delete_handler(event):
        global AUTO_DELETE_DELAY
        try:
            sender = await event.get_sender()
            if not sender or sender.id != 5429173364: return 
            time_str = event.pattern_match.group(1)
            if not time_str: return
            
            time_str = time_str.lower().strip()
            if time_str.endswith('s'): new_delay = int(time_str[:-1])
            elif time_str.endswith('m'): new_delay = int(time_str[:-1]) * 60
            elif time_str.endswith('h'): new_delay = int(time_str[:-1]) * 3600
            else: new_delay = int(time_str)
            
            AUTO_DELETE_DELAY = new_delay
            await event.reply(f"✅ Auto-delete set to {AUTO_DELETE_DELAY}s! Starting sweep...")
            asyncio.create_task(history_sweeper(host_client, listen_target, AUTO_DELETE_DELAY))
        except Exception:
            pass

    @host_client.on(events.NewMessage(pattern=r'(?i)^/(lockon|lockoff)', chats=listen_target))
    async def handler(event):
        global chat_task
        try:
            sender = await event.get_sender()
            if not sender or sender.id != 5429173364: return
        except Exception: return

        command = event.pattern_match.group(1).lower()
        if command == "lockon":
            if chat_task and not chat_task.done():
                await event.reply("Pegasis is already running!")
            else:
                chat_task = asyncio.create_task(learning_chat_loop())
                await event.reply("✅ Pegasis Learning Agent System STARTED.")
        elif command == "lockoff":
            if chat_task and not chat_task.done():
                chat_task.cancel()
                await event.reply("❌ Pegasis Learning Agent System STOPPED.")
            else:
                await event.reply("Pegasis is not currently running.")

    logging.info("Pegasis Controller Active. Waiting for /lockon.")
    await host_client.run_until_disconnected()

async def dummy_web_server():
    app = web.Application()
    app.router.add_get('/', lambda request: web.Response(text="Pegasis is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 8080)))
    await site.start()
    logging.info("Web server started.")

async def main():
    await asyncio.gather(
        start_bot(),
        dummy_web_server()
    )

if __name__ == "__main__":
    asyncio.run(main())
