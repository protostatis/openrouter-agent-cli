import json
d = json.load(open("share.json"))
for k in sorted(d):
    print(k, sum(d[k]) / len(d[k]))
