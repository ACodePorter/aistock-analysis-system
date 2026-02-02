import os
from datetime import date, datetime
import time

# Ensure we use backend package
os.environ.setdefault('PYTHONPATH', os.path.abspath('.'))
# Feature flags / mongo config
os.environ.setdefault('AGENT_MONGO_ENABLE', '1')
os.environ.setdefault('MONGO_URI', os.environ.get('MONGO_URI', 'mongodb://localhost:27017'))
os.environ.setdefault('MONGO_DB_NAME', os.environ.get('MONGO_DB_NAME', os.environ.get('MONGO_DB', 'aistock_news')))

print('ENV AGENT_MONGO_ENABLE=', os.environ['AGENT_MONGO_ENABLE'])
print('ENV MONGO_URI=', os.environ['MONGO_URI'])
print('ENV MONGO_DB_NAME=', os.environ['MONGO_DB_NAME'])

# Import the upsert function
from app.utils.agent_persistence import _maybe_upsert_mongo

# Build a sample payload
payload = {
    'version': 'test-1',
    'top20_count': 3,
    'stock_reports': [{'symbol': 'TEST', 'summary': 'test report'}],
    'macro': {'note': 'macro test'},
    'analytics': {'foo': 'bar'},
    'diagnostics': {'ok': True}
}

report_date = date.today()
job_id = 'test-job-123'

print('Calling _maybe_upsert_mongo...')
try:
    _maybe_upsert_mongo(report_date, job_id, payload, markdown_text='# test markdown')
    print('Upsert function returned (no exceptions)')
except Exception as e:
    print('Upsert raised exception:', e)

# Verify via pymongo
try:
    from pymongo import MongoClient
    client = MongoClient(os.environ['MONGO_URI'], serverSelectionTimeoutMS=5000)
    db = client[os.environ['MONGO_DB_NAME']]
    coll = db[os.environ.get('AGENT_MONGO_COLLECTION', 'agent_daily_reports')]
    doc = coll.find_one({'report_date': report_date.isoformat()})
    print('Found document:', doc)
except Exception as e:
    print('Verification read failed:', e)

print('done')
