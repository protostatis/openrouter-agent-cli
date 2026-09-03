import json
rows = json.load(open("pairs.json"))
rows = rows["pairs_count"]
for i in range(rows):
    print(i, "->", i + 1)
