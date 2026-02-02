import sys
sys.path.insert(0, r'd:/workspace/mpj/aistock-full-project/backend')
from app.data.data_source import fetch_daily
print('calling fetch_daily for 600519.SH')
df = fetch_daily('600519.SH')
print('type:', type(df))
try:
    print('rows:', len(df))
    print(df.head().to_dict())
except Exception as e:
    print('err2', e)
