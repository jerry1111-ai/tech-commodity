# -*- coding: utf-8 -*-
"""为全行业选股的前20只股票生成 30 分钟 K 线。

数据源：新浪 stock_zh_a_hist_min_sina(period='30')（东财已限流，新浪稳定，约1970根/只）。
输出：HT_Trading_System_data/all_bars/{行业代码}_30m.js
      -> window.HT_ALL_BARS_30M[行业][股票代码] = [[datetime,o,h,l,c,v],...]
"""
import os
import re
import json
import time
import random
import warnings
from concurrent.futures import ThreadPoolExecutor

import akshare as ak

warnings.filterwarnings("ignore")

from config import ROOT

DATA = os.path.join(ROOT, "HT_Trading_System_data")
BARS_DIR = os.path.join(DATA, "all_bars")
ALL_SCREEN = os.path.join(DATA, "all_screen.js")
WORKERS = 8
KEEP = 300  # 每只保留最近300根30分钟K线


def sina(code):
    if code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def fetch_one(code):
    for attempt in range(2):
        try:
            df = ak.stock_zh_a_hist_min_sina(symbol=sina(code), period="30")
            if df is None or df.empty:
                return code, None
            rows = []
            for _, r in df.iterrows():
                try:
                    rows.append([str(r["day"]), float(r["open"]), float(r["high"]),
                                 float(r["low"]), float(r["close"]),
                                 int(float(r["volume"])) if r.get("volume") not in (None, "") else 0])
                except Exception:
                    continue
            return code, rows
        except Exception:
            time.sleep(1 + random.uniform(0, 1))
    return code, None


def main():
    with open(ALL_SCREEN, "r", encoding="utf-8") as f:
        txt = f.read()
    data = json.loads(re.search(r"window\.HT_ALL_SCREEN=(.*);\s*$", txt, re.S).group(1))

    t0 = time.time()
    for idx, ind in enumerate(data["industries"], 1):
        codes = [it["code"] for it in ind["items"]]
        result = {}
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for code, rows in ex.map(fetch_one, codes):
                if rows:
                    result[code] = rows
        out = os.path.join(BARS_DIR, f"{ind['code']}_30m.js")
        # 每只只保留最近 300 根（约1.5个月），控制仓库体积
        result = {c: (v[-KEEP:] if len(v) > KEEP else v) for c, v in result.items()}
        js = ("window.HT_ALL_BARS_30M=window.HT_ALL_BARS_30M||{};"
              f"window.HT_ALL_BARS_30M[{json.dumps(ind['code'])}]="
              + json.dumps(result, ensure_ascii=False, separators=(",", ":")) + ";")
        with open(out, "w", encoding="utf-8") as f:
            f.write(js)
        print(f"[{idx}/31] {ind['name']}: {len(result)}/{len(codes)} 只 用时{time.time()-t0:.0f}s", flush=True)

    print(f"完成，总用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
