# -*- coding: utf-8 -*-
"""申万行业指数 30 分钟 K 线：从 index_min_sw（当天 10 秒分笔）聚合，按日累积。

背景：申万指数无免费历史 30 分钟源（东财不含、腾讯不通、iFinD 仅日内）。
index_min_sw 只给当天 09:30 起的分笔，故本脚本每次运行把当天分笔聚合成 30 分钟，
覆盖缓存中当天记录、其他日期保留，实现"从今天起自动累积"。

输出：update_tool/data_min30/{safe}.csv（与期货 30 分钟同目录，供 build_bars30.py 生成分片）
"""
import os
import re
import json
import time
import random
import argparse
import warnings
from datetime import datetime

import pandas as pd
import akshare as ak

warnings.filterwarnings("ignore")

from config import HTML_PATH, DATA_MIN30_DIR, LOG_DIR, SRC_SW

COLS = ["datetime", "open", "high", "low", "close", "volume", "hold"]

# A股交易时段 30 分钟分桶（左闭右开，标签取区间终点）
BUCKETS = [
    (570, 600, "10:00"), (600, 630, "10:30"), (630, 660, "11:00"), (660, 691, "11:30"),
    (780, 810, "13:30"), (810, 840, "14:00"), (840, 870, "14:30"), (870, 901, "15:00"),
]


def load_db():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"const DB=(\{.*?\});", html, re.S)
    return json.loads(m.group(1))


def sw_items():
    db = load_db()
    return [i for i in db["items"] if i.get("source") == SRC_SW]


def cache_path(code):
    safe = re.sub(r"[^0-9A-Za-z]", "_", code)
    return os.path.join(DATA_MIN30_DIR, safe + ".csv")


def bucket_of(t):
    """'HH:MM:SS' -> 桶标签 'HH:MM' 或 None（非交易时段）。"""
    try:
        hh, mm = int(t[0:2]), int(t[3:5])
    except Exception:
        return None
    m = hh * 60 + mm
    for s, e, lab in BUCKETS:
        if s <= m < e:
            return lab
    return None


def aggregate(df):
    """分笔（日期/时间/价格）-> 30 分钟 OHLC 列表。"""
    groups = {}
    order = []
    for _, r in df.iterrows():
        d = str(r["日期"])
        t = str(r["时间"])
        try:
            p = float(r["价格"])
        except Exception:
            continue
        lab = bucket_of(t)
        if not lab:
            continue
        key = f"{d} {lab}:00"
        if key not in groups:
            groups[key] = {"o": p, "h": p, "l": p, "c": p}
            order.append(key)
        else:
            g = groups[key]
            g["h"] = max(g["h"], p)
            g["l"] = min(g["l"], p)
            g["c"] = p
    rows = []
    for k in order:
        g = groups[k]
        rows.append({"datetime": k, "open": g["o"], "high": g["h"], "low": g["l"],
                     "close": g["c"], "volume": 0, "hold": 0})
    return rows


def fetch(symbol):
    last = None
    for attempt in range(3):
        try:
            return ak.index_min_sw(symbol=symbol)
        except Exception as e:
            last = e
            time.sleep((3 if attempt == 0 else 6) + random.uniform(0, 2))
    raise last


def update_item(item):
    code = item["code"]
    sym = code.split(".")[0]
    path = cache_path(code)
    try:
        raw = fetch(sym)
    except Exception as e:
        return {"code": code, "name": item["name"], "status": "error", "msg": str(e)[:70]}

    if raw is None or raw.empty:
        return {"code": code, "name": item["name"], "status": "empty", "msg": "无分笔"}

    new_rows = aggregate(raw)
    if not new_rows:
        return {"code": code, "name": item["name"], "status": "empty", "msg": "非交易时段/无有效分笔"}

    today = new_rows[-1]["datetime"][:10]
    old = pd.read_csv(path, dtype={"datetime": str}) if os.path.exists(path) else pd.DataFrame(columns=COLS)
    # 覆盖当天，保留其他日期
    if not old.empty:
        old = old[~old["datetime"].astype(str).str.startswith(today)]
    merged = pd.concat([old, pd.DataFrame(new_rows)], ignore_index=True)
    merged = merged.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    merged[COLS].to_csv(path, index=False, encoding="utf-8-sig")
    return {"code": code, "name": item["name"], "status": "ok",
            "rows": len(merged), "today": len(new_rows), "last": merged["datetime"].iloc[-1]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=str, default="")
    args = ap.parse_args()

    os.makedirs(DATA_MIN30_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    items = sw_items()
    only = [x.strip() for x in args.only.split(",") if x.strip()]
    if only:
        items = [i for i in items if i["name"] in only]

    t0 = time.time()
    results = []
    for idx, it in enumerate(items, 1):
        r = update_item(it)
        results.append(r)
        flag = {"ok": "OK", "empty": "EMPTY", "error": "ERR"}.get(r["status"], "?")
        print(f"[{idx:>2}/{len(items)}] {flag:<5} {it['name']:<12} rows={r.get('rows',0):<5} "
              f"今日{r.get('today',0)}根 {r.get('msg','')}")

    okc = sum(1 for r in results if r["status"] == "ok")
    print(f"\n完成：成功 {okc} / 共 {len(results)}，用时 {time.time()-t0:.1f}s")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(LOG_DIR, f"min30_index_{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump({"time": stamp, "results": results}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
