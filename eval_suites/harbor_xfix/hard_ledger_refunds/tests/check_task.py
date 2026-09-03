import json, sys
try:
    data = json.load(open("/app/final_balances.json"))
except Exception:
    print("missing or invalid final_balances.json"); sys.exit(2)
if data != {"x": 30, "y": 80}:
    print("balances wrong: expected {x:30,y:80}, got", data); sys.exit(2)
print("verified")
