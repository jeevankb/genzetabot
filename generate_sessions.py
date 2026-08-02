import os
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

accounts = {
    "acc1": {"name": "Account 1", "api_id": 2282111, "api_hash": "da58a1841a16c352a2a999171bbabcad", "session": "session_unique 6"},
    "acc2": {"name": "Account 2", "api_id": 8447214, "api_hash": "9ec5782ddd935f7e2763e5e49a590c0d", "session": "session_unique_4"},
    "acc3": {"name": "Account 3", "api_id": 22792918, "api_hash": "ff10095d2bb96d43d6eb7a7d9fc85f81", "session": "session_unique_5"},
    "acc4": {"name": "Account 4", "api_id": 2282111, "api_hash": "da58a1841a16c352a2a999171bbabcad", "session": "acc4"},
    "acc5": {"name": "Account 5", "api_id": 2282111, "api_hash": "da58a1841a16c352a2a999171bbabcad", "session": "acc5"}
}

async def main():
    print("="*60)
    print("   STRING SESSION GENERATOR (FOR FREE CLOUD DEPLOYMENT)")
    print("="*60)
    print("Extracting String Sessions from your local database...\n")
    
    for key, data in accounts.items():
        session_file = f"{data['session']}"
        session_path = os.path.join(SCRIPT_DIR, session_file)
        
        # Connect using the local file
        client = TelegramClient(session_path, data['api_id'], data['api_hash'])
        await client.connect()
        
        if await client.is_user_authorized():
            # Convert SQLiteSession to StringSession
            ss = StringSession()
            ss.set_dc(client.session.dc_id, client.session.server_address, client.session.port)
            ss.auth_key = client.session.auth_key
            string_session = ss.save()
            print(f"✅ {data['name']} ({key.upper()}_SESSION):\n{string_session}\n")
        else:
            print(f"❌ {data['name']} is not authorized. Please run friends_chat.py locally first to login.\n")
            
        await client.disconnect()
        
    print("="*60)
    print("INSTRUCTIONS:")
    print("1. Copy those 3 long blocks of random text above.")
    print("2. Paste them into your cloud server's Environment Variables panel.")
    print("3. Name them ACC1_SESSION, ACC2_SESSION, and ACC3_SESSION.")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
