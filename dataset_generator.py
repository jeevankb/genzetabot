import os
import time
import google.generativeai as genai
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# This is the exact prompt you provided for the massive dataset.
PROMPT_TEMPLATE = """
Generate a large-scale synthetic chat dataset in CSV format exactly matching these rules.

Goal:
Create realistic human-to-human conversations between three friends: Account1, Account2, Account3.
The conversations should resemble Telegram or WhatsApp chats between Indian college students and young professionals.

Output Format (CSV)
Columns: conversation_id, message_id, timestamp, sender, receiver, chat_type, language, topic, message, reply_to, emotion

Requirements:
- Generate EXACTLY 5 full conversations.
- Each conversation should contain between 8 and 60 messages.
- Each message should feel natural and human.
- Never make every sentence grammatically perfect.
- Use typing habits like: "bro", "acha", "kya kar ra", "haa", "hmm", "ok", "lol", "😂", "😅", "👍", "bhai", "macha", "maga", "guru", "arre", "oye"
- Mix uppercase/lowercase naturally. Some spelling mistakes.
- Include abbreviations: "fr", "idk", "brb", "gn", "tc"
- Languages: Mix naturally between English, Hinglish, Kannada, Tamil, Telugu, Malayalam, Marathi (English transliterations).
- Topics: Mix College, Coding, Anime (like Solo Leveling, JJK, Naruto), Office work, Weather.
- Natural Behaviour: Someone changes topic suddenly. Someone sends only emoji. Someone says "brb" or "typing...".
- NO markdown wrappers in your output. JUST the raw CSV text.
- START AT CONVERSATION_ID: {start_id}

DO NOT print headers, ONLY the CSV rows!
"""

def generate_chunk(start_id, model):
    prompt = PROMPT_TEMPLATE.replace("{start_id}", str(start_id))
    try:
        response = model.generate_content(prompt)
        csv_content = response.text.strip()
        
        # Clean markdown if present
        if csv_content.startswith("```csv"): csv_content = csv_content[6:]
        if csv_content.startswith("```"): csv_content = csv_content[3:]
        if csv_content.endswith("```"): csv_content = csv_content[:-3]
        return csv_content.strip()
    except Exception as e:
        logging.error(f"Failed to generate chunk starting at {start_id}: {e}")
        return None

def main():
    print("=====================================================")
    print("   AUTOMATED 5000-CONVERSATION DATASET GENERATOR   ")
    print("=====================================================\n")
    
    api_key = input("Please paste your Google Gemini API Key: ").strip()
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-pro")
    
    output_file = "massive_dataset_5000.csv"
    
    # Write header if file doesn't exist
    if not os.path.exists(output_file):
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("conversation_id,message_id,timestamp,sender,receiver,chat_type,language,topic,message,reply_to,emotion\n")
            
    total_target_conversations = 5000
    conversations_generated = 0
    current_id = 3000
    
    logging.info(f"Starting generation loop. Target: {total_target_conversations} conversations.")
    
    while conversations_generated < total_target_conversations:
        logging.info(f"Requesting 5 conversations starting at ID {current_id}...")
        
        csv_data = generate_chunk(current_id, model)
        
        if csv_data:
            with open(output_file, "a", encoding="utf-8") as f:
                f.write(csv_data + "\n")
                
            conversations_generated += 5
            current_id += 5
            logging.info(f"SUCCESS! Total generated so far: {conversations_generated}/{total_target_conversations}")
            
            # Sleep to prevent API rate limiting (HTTP 429 errors)
            time.sleep(15) 
        else:
            logging.warning("Retrying in 30 seconds due to failure...")
            time.sleep(30)
            
    print(f"\n✅ GENERATION COMPLETE! Saved to {output_file}")

if __name__ == "__main__":
    main()
