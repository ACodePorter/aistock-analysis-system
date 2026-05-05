from pymongo import MongoClient
import os

uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017')
db_name = os.environ.get('MONGO_DB', os.environ.get('MONGO_DB_NAME', 'aistock_news'))

print('MONGO_URI=', uri)
print('DB=', db_name)

client = MongoClient(uri, serverSelectionTimeoutMS=5000)
db = client[db_name]
cols = db.list_collection_names()
print('collections:', cols)

for name in ['macro_observations', 'macro_reports', 'macro_model_runs']:
    if name in cols:
        try:
            cnt = db.get_collection(name).count_documents({})
        except Exception as e:
            cnt = f'ERROR: {e}'
    else:
        cnt = 0
    print(f'{name}:', cnt)

# show latest macro_report doc sample
if 'macro_reports' in cols:
    doc = db.get_collection('macro_reports').find_one(sort=[('report_date', -1)])
    print('latest_macro_report:', doc)

client.close()
