import os
import json
from pathlib import Path
from datetime import datetime

# ensure backend package import path
os.environ.setdefault('PYTHONPATH', str(Path(__file__).resolve().parent))

from app.utils.agent_persistence import REPORTS_DIR, persist_agent_report, _infer_report_date

from pymongo import MongoClient

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
DB_NAME = os.getenv('MONGO_DB_NAME', os.getenv('MONGO_DB', 'aistock_news'))
COLL = os.getenv('AGENT_MONGO_COLLECTION', 'agent_daily_reports')

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client[DB_NAME]
coll = db[COLL]

files = sorted(REPORTS_DIR.glob('agent_report_*.json'), key=lambda p: p.stat().st_mtime)
print(f'Found {len(files)} report files in {REPORTS_DIR}')
to_backfill = []

for f in files:
    try:
        payload = json.loads(f.read_text(encoding='utf-8'))
    except Exception as e:
        print('Failed to read', f, e)
        continue
    report_date = _infer_report_date(payload).isoformat()
    existing = coll.find_one({'report_date': report_date})
    if existing:
        # already present
        continue
    to_backfill.append((f, report_date))

print(f'{len(to_backfill)} files to backfill')

success = 0
fail = 0
for f, dt in to_backfill:
    print('Backfilling', f, 'report_date=', dt)
    try:
        res = persist_agent_report(f)
        if res:
            success += 1
            print('  persisted SQL id=', res)
        else:
            fail += 1
            print('  persist returned None')
    except Exception as e:
        fail += 1
        print('  Exception while persisting', e)

print('Done. success=', success, 'fail=', fail)
