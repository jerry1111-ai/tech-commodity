# -*- coding: utf-8 -*-
"""生成网页 30 分钟 K 线分片：HT_Trading_System_data/{code}_30m.js

数据来源 update_tool/data_min30/*.csv（fetch_min30.py 生成），
写入 window.HT_BARS_30M[code] = [[datetime,o,h,l,c,v], ...]。
"""
import os
import re
import json
import datetime as dt

import pandas as pd

from config import ROOT, DATA_MIN30_DIR, HTML_PATH

OUT_DIR = os.path.join(ROOT, "HT_Trading_System_data")


def code_to_file(code):
    return re.sub(r"[^0-9A-Za-z]", "_", code)


def main():
    if not os.path.isdir(DATA_MIN30_DIR):
        print("无 data_min30 目录，跳过")
        return
    # 从 HTML DB 建立 safe名 -> 真实code 的映射，确保 key 精确
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"const DB=(\{.*?\});", html, re.S)
    db = json.loads(m.group(1)) if m else {"items": []}
    safe2code = {}
    for it in db.get("items", []):
        safe2code[code_to_file(it["code"])] = it["code"]

    ok = 0
    tot = 0
    for fn in os.listdir(DATA_MIN30_DIR):
        if not fn.endswith(".csv"):
            continue
        safe = fn[:-4]
        code = safe2code.get(safe, safe.replace("_", "."))
        try:
            df = pd.read_csv(os.path.join(DATA_MIN30_DIR, fn), dtype={"datetime": str})
        except Exception:
            continue
        if df.empty:
            continue
        bars = []
        for _, r in df.iterrows():
            dtstr = str(r["datetime"]).strip()
            if len(dtstr) < 16:
                continue
            try:
                o = round(float(r["open"]), 2); h = round(float(r["high"]), 2)
                l = round(float(r["low"]), 2); c = round(float(r["close"]), 2)
                v = int(float(r["volume"])) if pd.notna(r["volume"]) else 0
            except Exception:
                continue
            bars.append([dtstr[:19], o, h, l, c, v])
        if not bars:
            continue
        payload = json.dumps(bars, ensure_ascii=False, separators=(",", ":"))
        js = f'window.HT_BARS_30M=window.HT_BARS_30M||{{}};window.HT_BARS_30M[{json.dumps(code)}]={payload};'
        out = os.path.join(OUT_DIR, safe + "_30m.js")
        with open(out, "w", encoding="utf-8") as f:
            f.write(js)
        ok += 1
        tot += len(bars)
    print(f"30分钟K线分片生成：{ok} 个品种，{tot} 根")


if __name__ == "__main__":
    main()
