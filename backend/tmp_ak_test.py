import sys
sys.path.insert(0, r'd:/workspace/mpj/aistock-full-project/backend')
from app.data.data_source import ak
print('calling ak.stock_zh_a_hist for 600519')
try:
    df = ak.stock_zh_a_hist(symbol='600519', period='daily', adjust='qfq')
    print(type(df), df is None)
    import pandas as pd
    if isinstance(df, pd.DataFrame):
        print('rows', len(df))
        print(df.head().to_dict())
except Exception as e:
    print('error', e)
