from config import Config
from loader import load_records
from transform import process
from formatter import format_report
cfg = Config()
records = load_records()
groups = process(records, cfg)
print(format_report(records, groups))
