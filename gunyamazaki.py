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
from aiohttp import web
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji, InputMediaPoll, Poll, PollAnswer, InputMediaDice

# Try importing generative AI
try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()
if HAS_GENAI:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Data loading
CSV_FILE = "anime_group_chat_10000.csv"
TARGET_CHAT = "https://t.me/+1tWK4j-BYC85MDVl"
TARGET_CHAT_ID = None
conversation_data = []

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
delete_delay = 360  # Default 6 minutes
total_messages_sent = 0
clients = {}

def parse_time_to_seconds(time_str):
    time_str = time_str.lower().strip()
    try:
        if time_str.endswith('s'): return int(time_str[:-1])
        elif time_str.endswith('m'): return int(time_str[:-1]) * 60
        elif time_str.endswith('h'): return int(time_str[:-1]) * 3600
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

async def simulate_typing(client, entity, text):
    typing_time = min(max(len(text) * 0.05, 1.0), 8.0)
    async with client.action(entity, 'typing'):
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

def setup_commands(bot_client):
    @bot_client.on(events.NewMessage(pattern='(?i)^/stats(?:@genzetabot)?$'))
    async def stats_handler(event):
        try:
            sender = await event.get_sender()
            if sender and sender.id == accounts["acc1"]["user_id"]:
                status = "🟢 ONLINE" if bot_active else "🔴 OFFLINE"
                await event.reply(f"📊 **GunYamazaki Stats**\n\nStatus: {status}\nSpeed: {message_speed}s\nAuto-Delete: {delete_delay}s\nMessages Sent: {total_messages_sent}")
        except: pass

    @bot_client.on(events.NewMessage(pattern='(?i)^/lockon(?:@genzetabot)?$'))
    async def lockon_handler(event):
        global bot_active
        # Only allow Account 1 to use this command
        try:
            sender = await event.get_sender()
            if sender and sender.id == accounts["acc1"]["user_id"]:
                bot_active = True
                await event.reply("✅ GunYamazaki System Locked On. Starting conversation loop...")
                logging.info("System LOCKED ON by admin.")
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
                del_val = parse_time_to_seconds(event.pattern_match.group(1))
                if del_val is not None:
                    delete_delay = del_val
                    await event.reply(f"🗑 Auto-delete set to {delete_delay} seconds. Starting sweep...")
                    try:
                        entity = await bot_client.get_entity(TARGET_CHAT_ID or TARGET_CHAT)
                        asyncio.create_task(history_sweeper(bot_client, entity, delete_delay))
                    except: pass
        except: pass

    @bot_client.on(events.NewMessage(chats=TARGET_CHAT_ID or TARGET_CHAT))
    async def auto_delete_handler(event):
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
                        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
                        prompt = f"You are chatting in a group. A user replied to your message. Reply casually (1-2 short sentences) to them: '{event.raw_text}'"
                        ai_model = genai.GenerativeModel("gemini-1.5-flash")
                        response = await ai_model.generate_content_async(prompt)
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
                    if "?" in msg_text or random.random() < 0.3:
                        try:
                            genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
                            ai_model = genai.GenerativeModel("gemini-1.5-flash")
                            prompt = f"You are a casual anime fan chatting in a Telegram group. Keep your response very short (1-2 sentences), natural, lowercase, and human-like. Reply to this message: {msg_text}"
                            response = await ai_model.generate_content_async(prompt)
                            if response and response.text:
                                reply_acc = random.choice([clients["acc1"], clients["acc2"], clients["acc3"]])
                                asyncio.create_task(send_dynamic_reply(reply_acc["client"], entity, event.message, response.text.strip()))
                        except: pass
        except: pass

async def trigger_anime_news_event(entity):
    global total_messages_sent
    if not HAS_GENAI or "acc4" not in clients: return
    try:
        logging.info("Triggering Anime News Event...")
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        ai_model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt_news = "You are an anime fan in a group chat. Drop a random exciting piece of anime news (real or believable). Keep it to 1 sentence, casual, human-like. Do not use hashtags."
        resp_news = await ai_model.generate_content_async(prompt_news)
        news_text = resp_news.text.strip() if (resp_news and resp_news.text) else "Did you guys hear about the new anime season dropping next month? Looks insane."
        
        acc4 = clients["acc4"]["client"]
        await simulate_typing(acc4, entity, news_text)
        
        news_msg = await acc4.send_message(entity, news_text)
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
            resp_reply = await ai_model.generate_content_async(prompt_reply)
            reply_text = resp_reply.text.strip() if (resp_reply and resp_reply.text) else "No way, that's hype!"
            
            await simulate_typing(acc["client"], entity, reply_text)
                
            reply_msg = await acc["client"].send_message(entity, reply_text, reply_to=news_msg.id)
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
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        ai_model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = "Create a fun, engaging anime poll for a group chat. Format your response exactly like this: Question | Option 1 | Option 2 | Option 3"
        response = await ai_model.generate_content_async(prompt)
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
        await simulate_typing(acc4, entity, question)
        poll_msg = await acc4.send_message(entity, file=poll_media)
        logging.info(f"[Account 4] POLL: {question}")
        total_messages_sent += 1
        
        if delete_delay > 0:
            asyncio.create_task(delete_message_later(acc4, entity.id, poll_msg.id, max(delete_delay, 120)))
            
    except Exception as e:
        logging.error(f"Anime Poll Event Failed: {e}")

async def chat_loop():
    global bot_active, total_messages_sent
    
    csv_index = 0
    active_keys = [k for k in clients.keys() if k != "acc4"]
    message_tracker = {}
    
    while True:
        if bot_active and conversation_data and active_keys:
            msg_data = conversation_data[csv_index]
            
            sender_str = msg_data.get("sender", "").strip()
            # If the CSV specifies a sender that we have connected, use them. Otherwise, pick random.
            if sender_str in active_keys:
                chosen_key = sender_str
            else:
                chosen_key = random.choice(active_keys)
                
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
                    
                # Account 4 AI Participation (90%)
                if HAS_GENAI and random.random() < 0.90 and "acc4" in clients:
                    try:
                        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
                        ai_model = genai.GenerativeModel("gemini-1.5-flash")
                        prompt = f"You are a human anime fan in a group chat. Someone just said: '{msg_text}'. Reply to them casually in 1 short sentence using natural human language (like yes, no, haha, I agree, lol). Do not use hashtags."
                        response = await ai_model.generate_content_async(prompt)
                        if response and response.text:
                            ai_text = response.text.strip()
                            acc4_client = clients["acc4"]["client"]
                            await simulate_typing(acc4_client, entity, ai_text)
                            ai_sent_msg = await acc4_client.send_message(entity, ai_text, reply_to=sent_msg.id)
                            logging.info(f"[Account 4 (Bot)] AI Sent: {ai_text}")
                            total_messages_sent += 1
                            if delete_delay > 0:
                                asyncio.create_task(delete_message_later(acc4_client, entity.id, ai_sent_msg.id, delete_delay))
                    except Exception as e:
                        logging.error(f"AI Account 4 error: {e}")
                
                csv_index = (csv_index + 1) % len(conversation_data)
            except FloodWaitError as e:
                logging.warning(f"Rate limited! Sleeping for {e.seconds}s")
                await asyncio.sleep(e.seconds)
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
            
    global TARGET_CHAT_ID
    if "acc1" in clients:
        try:
            entity = await clients["acc1"]["client"].get_entity(TARGET_CHAT)
            TARGET_CHAT_ID = entity.id
            logging.info(f"Resolved TARGET_CHAT to ID: {TARGET_CHAT_ID}")
        except Exception as e:
            logging.error(f"Failed to resolve TARGET_CHAT: {e}")
            TARGET_CHAT_ID = TARGET_CHAT

    if "acc4" in clients:
        setup_commands(clients["acc4"]["client"])
        
    logging.info("All accounts connected! Waiting for /lockon command...")
    
    await chat_loop()
    
    await asyncio.gather(*[c["client"].run_until_disconnected() for c in clients.values()])

if __name__ == "__main__":
    asyncio.run(main())
