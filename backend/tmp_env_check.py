import os,sys
sys.path.insert(0, r'd:/workspace/mpj/aistock-full-project/backend')
from app.data import data_source
print('ENV DATA_SOURCE=', os.getenv('DATA_SOURCE'))
print('module DATA_SOURCE=', data_source.DATA_SOURCE)
print('TUSHARE_TOKEN present=', bool(os.getenv('TUSHARE_TOKEN')))
print('POSTGRES_HOST=', os.getenv('POSTGRES_HOST'))
print('POSTGRES_PORT=', os.getenv('POSTGRES_PORT'))
