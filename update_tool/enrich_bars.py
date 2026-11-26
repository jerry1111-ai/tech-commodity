# -*- coding: utf-8 -*-
"""为全行业选股的前20只股票补齐长历史日K（因评分只需400根，原输出仅300根）。

只处理 all_screen.js 里各行业前20（620只），重拉约5年历史，覆盖 all_bars/{行业}.js。
输出格式与 build_stock_all.py 一致：window.HT_ALL_BARS[行业][code]=[[date,o,h,l,c,v],...]
"""
import os
import re
import json
import time
import random
import warnings
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import akshare as ak

warnings.filterwarnings("ignore")

from config import ROOT

DATA = os.path.join(ROOT, "HT_Trading_System_data")
BARS_DIR = os.path.join(DATA, "all_bars")
ALL_SCREEN = os.path.join(DATA, "all_screen.js")

WORKERS = 8
HISTORY_DAYS = 2000   # 约5.5年
KEEP_BARS = 1200      # 输出保留最近1200根（约5年）


def sina(code):
    if code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def fetch_long(code):
    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=HISTORY_DAYS)).strftime("%Y%m%d")
    # 只用新浪：东财接口内部走 py_mini_racer(V8)，多线程并发会 FATAL 崩溃
    for attempt in range(2):
        try:
            df = ak.stock_zh_a_daily_sina(symbol=sina(code), start_date=start,
                                          end_date=end, adjust="qfq")
            if df is not None and not df.empty:
                rows = [[pd.to_datetime(r["date"]).strftime("%Y-%m-%d"),
                         round(float(r["open"]), 2), round(float(r["high"]), 2),
                         round(float(r["low"]), 2), round(float(r["close"]), 2),
                         int(r["volume"])] for _, r in df.iterrows()]
                return code, rows[-KEEP_BARS:]
        except Exception:
            time.sleep(1 + random.uniform(0, 1))
    return code, None


def main():
    with open(ALL_SCREEN, "r", encoding="utf-8") as f:
        data = json.loads(re.search(r"window\.HT_ALL_SCREEN=(.*);\s*$", f.read(), re.S).group(1))

    t0 = time.time()
    for idx, ind in enumerate(data["industries"], 1):
        codes = [it["code"] for it in ind["items"]]
        result = {}
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for code, rows in ex.map(fetch_long, codes):
                if rows:
                    result[code] = rows
        if not result:
            print(f"[{idx}/31] {ind['name']}: 全部失败，跳过", flush=True)
            continue
        js = ("window.HT_ALL_BARS=window.HT_ALL_BARS||{};"
              f"window.HT_ALL_BARS[{json.dumps(ind['code'])}]="
              + json.dumps(result, ensure_ascii=False, separators=(",", ":")) + ";")
        with open(os.path.join(BARS_DIR, f"{ind['code']}.js"), "w", encoding="utf-8") as f:
            f.write(js)
        bars = len(next(iter(result.values())))
        print(f"[{idx}/31] {ind['name']}: {len(result)}/{len(codes)} 只，每只约{bars}根，用时{time.time()-t0:.0f}s", flush=True)
    print(f"完成，总用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
