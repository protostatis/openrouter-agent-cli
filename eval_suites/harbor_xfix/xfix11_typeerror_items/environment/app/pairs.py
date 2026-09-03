import json
r = json.load(open("routes.json"))
for k, v in r.items():
    print(k, v)
