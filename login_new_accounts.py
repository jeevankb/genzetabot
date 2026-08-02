import asyncio
from telethon import TelegramClient

API_ID = 2282111
API_HASH = "da58a1841a16c352a2a999171bbabcad"

async def login_account(session_name):
    print(f"\n--- LOGGING IN: {session_name} ---")
    client = TelegramClient(session_name, API_ID, API_HASH)
    await client.start()
    print(f"Success! {session_name}.session has been saved locally.\n")
    await client.disconnect()

async def main():
    print("Welcome! Let's log in your two new accounts.")
    print("You will need their phone numbers (including country code) and the Telegram login code.")
    
    await login_account("acc4")
    await login_account("acc5")
    
    print("All done! You can now run 'python generate_sessions.py' to get their String Sessions.")

if __name__ == "__main__":
    asyncio.run(main())
