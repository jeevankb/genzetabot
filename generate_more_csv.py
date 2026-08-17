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

async def generate_chat_batch(last_id, last_time, batch_size=20):
    prompt = f"""Generate {batch_size} lines of organic, casual Telegram group chat conversation between anime fans.
    
Topics should be extremely diverse (new anime, old classics, manga chapters, power scaling, waifus, openings/endings, merch, convention plans, light novels, etc). DO NOT repeat the same quotes. Use human-like slang (lol, rn, tbh, lmao, peak fiction, mid).
Include users replying to each other naturally (arguments, agreements, hype).

Format the output STRICTLY as a CSV without markdown block tags, headers, or anything else. Just the raw rows.
Columns MUST be: id,timestamp,sender,message,reply_to,reaction

Rules:
1. `id` must start at {last_id + 1} and increment sequentially.
2. `timestamp` must start at {last_time.strftime('%Y-%m-%d %H:%M:%S')} and increment by 1-5 minutes per row.
3. `sender` must randomly be one of: acc1, acc2, acc3.
4. `message` must be a short, natural sentence. Be creative!
5. `reply_to` is either empty, or the ID of a previous message they are replying to. (Make about 30% of messages replies).
6. `reaction` is either empty or a single emoji (😂, ❤️, 🔥, 😭, 👀, etc) that someone reacted with. (Make about 20% of messages have a reaction).

OUTPUT EXACTLY THE RAW CSV ROWS. DO NOT wrap in ```csv or ``` tags."""

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
    print("Welcome to the AI Anime Chat Generator!")
    print(f"Target file: {CSV_FILE}")
    
    last_id, last_time = get_last_state()
    print(f"Current max ID: {last_id}, Latest Time: {last_time}")
    
    try:
        batches = int(input("How many batches of 20 messages do you want to generate? (e.g., 5 for 100 messages): "))
    except ValueError:
        print("Please enter a valid number.")
        return

    print(f"Generating {batches * 20} new messages... This might take a minute.")
    
    with open(CSV_FILE, "a", encoding="utf-8-sig", newline="") as f:
        # If file is completely empty, write headers (unlikely since it has 10k rows)
        if last_id == 0:
            f.write("id,timestamp,sender,message,reply_to,reaction\n")
            
        for i in range(batches):
            print(f"Generating batch {i+1}/{batches}...")
            try:
                csv_data = await generate_chat_batch(last_id, last_time)
                
                # Update last_id and last_time for the next batch
                lines = csv_data.split('\n')
                valid_lines = []
                for line in lines:
                    parts = line.split(',')
                    if len(parts) >= 4 and parts[0].isdigit():
                        valid_lines.append(line)
                        last_id = int(parts[0])
                        try:
                            # Handling timestamp, but roughly advancing it just in case parsing fails
                            last_time += timedelta(minutes=2) 
                        except:
                            pass
                
                if valid_lines:
                    f.write("\n" + "\n".join(valid_lines))
                    print(f"✅ Appended {len(valid_lines)} messages.")
                else:
                    print("❌ Model returned invalid format. Skipping batch.")
            except Exception as e:
                print(f"❌ Error generating batch: {e}")
                
    print("🎉 Done! You can now run your main script and it will use the exciting new messages!")

if __name__ == "__main__":
    asyncio.run(main())
