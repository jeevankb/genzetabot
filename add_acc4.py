import csv
import random

input_file = "anime_group_chat_10000.csv"
output_file = "temp.csv"

try:
    with open(input_file, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        fieldnames = reader[0].keys() if reader else []

    for row in reader:
        # 25% chance to change the sender to acc4
        if random.random() < 0.25:
            row["sender"] = "acc4"

    with open(output_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reader)
        
    print("CSV successfully rewritten with acc4!")
except Exception as e:
    print(f"Error: {e}")
