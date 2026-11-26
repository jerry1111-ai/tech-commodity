import akshare as ak, warnings, time
warnings.filterwarnings("ignore")
for c in ["300010","002124","600519"]:
    try:
        df = ak.stock_zyjs_ths(symbol=c)
        print(c, "rows", 0 if df is None else len(df), flush=True)
    except Exception as e:
        print(c, "EXC", type(e).__name__, str(e)[:120], flush=True)
    time.sleep(0.5)
print("done", flush=True)
