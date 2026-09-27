import json
import sys

from event_parser import load_events
from sessionizer import summarize


for session in summarize(load_events(sys.argv[1])):
    print(json.dumps(session, separators=(",", ":")))
