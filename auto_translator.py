import os
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from dotenv import load_dotenv

# We will use Gemini for high-quality translation
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logging.getLogger("google").setLevel(logging.ERROR)

load_dotenv()

# Configuration
API_ID = int(os.getenv("API_ID", "2282111"))
API_HASH = os.getenv("API_HASH", "da58a1841a16c352a2a999171bbabcad")
SESSION_STRING = os.getenv("SESSION_STRING") # The session of the account you use to chat
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

TARGET_CHAT = "https://t.me/your_group_link" # Replace with your target group link or ID

if not SESSION_STRING:
    logging.error("Please add SESSION_STRING to your environment variables.")
    exit(1)
if not GEMINI_API_KEY:
    logging.error("Please add GEMINI_API_KEY to your environment variables.")
    exit(1)

gemini_client = genai.Client(api_key=GEMINI_API_KEY)
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

async def translate_text(text, target_language):
    """Uses Gemini to translate text accurately."""
    try:
        # We tell Gemini to ignore English and Hindi so it doesn't spam translations for messages you already understand!
        prompt = f"If the following text is mostly in English or Hindi, output exactly 'NO_TRANSLATION'. Otherwise, translate the text to {target_language}. Respond ONLY with the translated text (or 'NO_TRANSLATION'), nothing else. Text: '{text}'"
        response = await gemini_client.aio.models.generate_content(model="gemini-3.6-flash", contents=prompt)
        result = response.text.strip()
        if "NO_TRANSLATION" in result:
            return None
        return result
    except Exception as e:
        logging.error(f"Translation failed: {e}")
        return None

@client.on(events.NewMessage(chats=TARGET_CHAT))
async def translator_handler(event):
    # 1. OUTGOING MESSAGES (You typing in English -> Auto-converts to Persian)
    if event.out:
        # If you start your message with .tr it will translate it!
        # Example: You type ".tr Hello brother" -> It edits your message to "سلام برادر"
        if event.raw_text.startswith('.tr '):
            original_text = event.raw_text[4:]
            translated = await translate_text(original_text, "Persian")
            if translated:
                await event.edit(translated)
                logging.info(f"Translated Outgoing: {original_text} -> {translated}")
        return

    # 2. INCOMING MESSAGES (Persian guy typing -> Bot replies in the group with English)
    if not event.out and event.raw_text:
        
        # Tell Gemini to translate it to English
        translated = await translate_text(event.raw_text, "English")
        
        if translated:
            # Send the translation directly into the group as a reply to the foreign message!
            msg = f"**[Auto-Translation]**\n{translated}"
            await event.reply(msg)
            logging.info(f"Replied in group with translation.")

async def main():
    logging.info("Starting Auto-Translator Userbot...")
    await client.start()
    logging.info("Translator is running! Listening to target chat...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
