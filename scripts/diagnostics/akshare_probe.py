import akshare as ak

functions_to_try = [
    'stock_news_em',
    'stock_notice_report',
    'stock_notice_em',
    'stock_zh_a_news',
    'stock_zh_a_daily',
    'stock_notice'
]

candidates = ['600519', '600519.SH', 'sh600519', '600519.SHA', '000001', '000001.SZ', 'sz000001']

for func_name in functions_to_try:
    print('\n-- Testing function:', func_name)
    if not hasattr(ak, func_name):
        print('   not available in AKShare')
        continue
    func = getattr(ak, func_name)
    for cand in candidates:
        try:
            print('  trying', cand)
            df = func(cand)
            if hasattr(df, 'empty') and getattr(df, 'empty'):
                print('   -> empty')
            else:
                # try to print small sample
                try:
                    print('   -> rows:', len(df) if hasattr(df, '__len__') else 'unknown')
                    print(df.head(1).to_dict('records'))
                except Exception as e:
                    print('   -> returned object, print error:', e)
        except Exception as e:
            print('   -> error:', type(e).__name__, e)
