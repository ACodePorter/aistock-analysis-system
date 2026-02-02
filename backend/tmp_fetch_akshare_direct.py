import sys
sys.path.insert(0, r'd:/workspace/mpj/aistock-full-project/backend')
from app.data.data_source import fetch_daily_akshare
print('call fetch_daily_akshare for 600519.SH')
df = fetch_daily_akshare('600519.SH')
print('type', type(df))
print('rows', len(df))
print('cols', df.columns.tolist())
if not df.empty:
    print(df.head().to_dict())
