from fastapi.testclient import TestClient
from app.main import app
import json

client = TestClient(app)

payload = {"preset":"szse","symbol":"000001","dry_run":True,"max_feeds_to_try":5,"max_items_per_feed":30}
resp = client.post('/api/news/ingest/official-a', json=payload)
print('STATUS', resp.status_code)
try:
    print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
except Exception:
    print('RESP TEXT:', resp.text)
