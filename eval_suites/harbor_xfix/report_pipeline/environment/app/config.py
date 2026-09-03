import json
class Config:
    def __init__(self):
        d = json.load(open("settings.json"))
        self.threshold = float(d["threshold"])
        self.group = d["group"]
        self.exclude = d["exclude"]
