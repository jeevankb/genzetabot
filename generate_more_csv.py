import os
import csv
import sys
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Try importing generative AI
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    print("Please install google-genai first: pip install google-genai")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logging.getLogger("google").setLevel(logging.ERROR)
logging.getLogger("google.genai").setLevel(logging.ERROR)

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    print("GEMINI_API_KEY not found in .env file.")
    import getpass
    API_KEY = getpass.getpass("Please paste your Gemini API Key here (input will be hidden): ").strip()

if not API_KEY:
    print("Error: No API key provided.")
    sys.exit(1)

client = genai.Client(api_key=API_KEY)
CSV_FILE = "anime_group_chat_10000.csv"

def get_last_state():
    last_id = 0
    last_time = datetime(2026, 1, 1, 8, 0, 0)
    
    if not os.path.exists(CSV_FILE):
        return last_id, last_time
        
    with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
        reader = list(csv.DictReader(f))
        if reader:
            last_row = reader[-1]
            last_id = int(last_row.get("id", 0))
            try:
                last_time = datetime.strptime(last_row.get("timestamp", ""), "%Y-%m-%d %H:%M:%S")
            except:
                pass
    return last_id, last_time

import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except:
    pass

async def generate_chat_batch(last_id, last_time, batch_size=20):
    prompt = f"""Generate {batch_size} lines of an authentic, chaotic, hilarious Telegram group chat between three close friends (acc1, acc2, acc3).

THEME: 3 Friends talking about ANIME, SPORTS, and ACTION GAMES, and ROASTING EACH OTHER non-stop in the middle of these conversations!

CONVERSATION DYNAMICS & TOPICS:
1. ACTION GAMES & GAMING ROASTS:
   - Games: Valorant, Elden Ring, Black Myth Wukong, GTA 6, Call of Duty / Warzone, Sekiro, Tekken, FIFA/FC.
   - Banter: Roasting each other's terrible aim, rage quitting after a boss, blaming lag or sticky controllers, hardstuck ranks, getting carried.
   - Example: "acc1: bro I almost clutched 1v4 in Val", "acc2: [reply_to acc1] you died to fall damage shut up 💀"

2. SPORTS & MATCH ROASTS:
   - Sports: Football / Champions League (Real Madrid, Barca, Man United, Arsenal, Messi vs Ronaldo), Cricket / IPL (Kohli, Rohit, choke jokes), Gym / lifting fails.
   - Banter: Clowning someone's team losing 4-0, arguing who is the GOAT, clowning someone's gym form or fake bench PR.
   - Example: "acc3: Arsenal winning the league this year trust", "acc1: [reply_to acc3] bro trust your therapist first 😭"

3. ANIME ARGUMENTS & POWERSCALING ROASTS:
   - Anime: Jujutsu Kaisen, Solo Leveling, One Piece, Dragon Ball, Demon Slayer, Bleach, Chainsaw Man.
   - Banter: Gojo vs Sukuna fraud debates, Zoro getting lost, calling someone's favorite anime mid, "bro watched through TikTok reels 💀".
   - Example: "acc2: Sung Jinwoo solos Goku low diff", "acc3: [reply_to acc2] please never speak about powerscaling ever again 🤡"

4. FRIEND ROASTING VIBE:
   - Quick comebacks, laughter, teasing, calling cap, natural Gen-Z slang (bro, fr, nah, lmao, ded, 💀, capping, L take, who let him cook, touch grass, 😭).
   - Short punchy replies mixed in ("Nah fr", "Bro is NOT him 💀", "Deserved", "Crying rn 😂", "Who asked?").

FORMAT REQUIREMENTS:
- Output STRICTLY as raw CSV rows. NO markdown blocks (no ```csv or ```), NO headers.
- Columns MUST be: id,timestamp,sender,message,reply_to,reaction
- Rules:
  1. `id`: Start at {last_id + 1} and increment sequentially (+1 per row).
  2. `timestamp`: Start at {last_time.strftime('%Y-%m-%d %H:%M:%S')} and advance by 1-4 minutes per row.
  3. `sender`: Randomly rotate between acc1, acc2, acc3.
  4. `message`: Natural, casual friend chat. Short or medium sentences.
  5. `reply_to`: CRITICAL! At least 50% of messages MUST reply to a previous message ID in this batch to maintain direct roasts and arguments.
  6. `reaction`: Emoji reaction (😂, 💀, 🔥, 😭, 🤡, ❤️, 👀) on about 25% of messages.

OUTPUT ONLY THE RAW CSV ROWS:"""

    response = await client.aio.models.generate_content(
        model="gemini-3.6-flash", 
        contents=prompt,
    )
    
    # Strip markdown block if model ignored the rule
    text = response.text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"): lines = lines[1:]
        if lines[-1].startswith("```"): lines = lines[:-1]
        text = "\n".join(lines).strip()
        
    return text

import asyncio

async def main():
    print("=== AI Natural & Roasting Chat Generator ===")
    print(f"Target file: {CSV_FILE}")
    
    last_id, last_time = get_last_state()
    print(f"Current max ID: {last_id}, Latest Time: {last_time}")
    
    # Support command-line argument for number of batches (e.g. python generate_more_csv.py 5)
    if len(sys.argv) > 1:
        try:
            batches = int(sys.argv[1])
        except ValueError:
            print("Invalid batch argument. Defaulting to 5 batches.")
            batches = 5
    else:
        try:
            user_input = input("How many batches of 20 messages do you want to generate? (default: 5 for 100 messages): ").strip()
            batches = int(user_input) if user_input else 5
        except (ValueError, EOFError):
            batches = 5

    print(f"Generating {batches * 20} new natural/roasting messages... This will take a few seconds.")
    
    with open(CSV_FILE, "a", encoding="utf-8-sig", newline="") as f:
        if last_id == 0:
            f.write("id,timestamp,sender,message,reply_to,reaction\n")
            
        total_appended = 0
        for i in range(batches):
            print(f"Generating batch {i+1}/{batches}...")
            try:
                csv_data = await generate_chat_batch(last_id, last_time)
                
                lines = csv_data.split('\n')
                valid_lines = []
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(',')
                    if len(parts) >= 4 and parts[0].isdigit():
                        valid_lines.append(line)
                        last_id = int(parts[0])
                        try:
                            last_time += timedelta(minutes=2) 
                        except:
                            pass
                
                if valid_lines:
                    f.write("\n" + "\n".join(valid_lines))
                    total_appended += len(valid_lines)
                    print(f"[OK] Appended {len(valid_lines)} messages (Current Max ID: {last_id}).")
                else:
                    print("[WARN] Model returned invalid format. Skipping batch.")
            except Exception as e:
                print(f"[ERROR] Error generating batch: {e}")
                
    print(f"[DONE] Successfully added {total_appended} new hilarious & nonsense conversations to {CSV_FILE}!")

if __name__ == "__main__":
    asyncio.run(main())

