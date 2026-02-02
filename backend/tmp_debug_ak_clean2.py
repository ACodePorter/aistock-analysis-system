import sys
sys.path.insert(0, r'd:/workspace/mpj/aistock-full-project/backend')
from app.data.data_source import ak
import pandas as pd
sym='600519.SH'
base = sym.replace('.SH','').replace('.SZ','')
print('raw call')
df = ak.stock_zh_a_hist(symbol=base, period='daily', adjust='qfq')
print('orig cols:', df.columns.tolist())
df2 = df.copy()
df2.columns = [str(c).strip().replace('\n','').replace('\r','') for c in df2.columns]
print('stripped cols:', df2.columns.tolist())
rename_map = { '日期':'trade_date','开盘':'open','收盘':'close','最高':'high','最低':'low','成交量':'vol','成交额':'amount','涨跌幅':'pct_chg',}
df2 = df2.rename(columns=rename_map)
print('after rename cols:', df2.columns.tolist())
if 'trade_date' in df2.columns:
    df2['trade_date'] = pd.to_datetime(df2['trade_date'], errors='coerce').dt.date
for col in ['open','high','low','close','pct_chg','amount']:
    if col in df2.columns:
        df2[col] = pd.to_numeric(df2[col], errors='coerce')
    else:
        df2[col] = None

df2['symbol'] = sym
cols = ['symbol','trade_date','open','high','low','close','pct_chg','vol','amount']
out = df2[cols].dropna(subset=['close']).reset_index(drop=True)
print('out rows:', len(out))
print(out.head().to_dict())
