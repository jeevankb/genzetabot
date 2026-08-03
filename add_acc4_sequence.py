import csv

input_file = "anime_group_chat_10000.csv"
output_file = "temp_seq.csv"

try:
    with open(input_file, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        fieldnames = reader[0].keys() if reader else []

    sequence = ["acc1", "acc2", "acc3", "acc4"]

    for i, row in enumerate(reader):
        row["sender"] = sequence[i % 4]

    with open(output_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reader)
        
    print("CSV successfully rewritten with strict sequence!")
except Exception as e:
    print(f"Error: {e}")
