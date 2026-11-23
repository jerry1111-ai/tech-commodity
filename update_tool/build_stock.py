# -*- coding: utf-8 -*-
"""申万有色选股：拉成分股日K -> 按股票SKILL.md评分 -> 前20 -> 生成 screen.js + 个股K线分片。"""
import os
import re
import sys
import json
import time
import random
import datetime as dt
import warnings

import pandas as pd
import akshare as ak

warnings.filterwarnings("ignore")

from config import ROOT
import stock_algo as sa

OUT_DIR = os.path.join(ROOT, "HT_Trading_System_data", "sw_nonferrous")
CACHE_DIR = os.path.join(ROOT, "update_tool", "data_stock")
SW_SECTOR = "801050"


def sina_code(code):
    if code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def fetch_daily(code, full=False):
    """拉单只股票日K（前复权），带缓存。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    p = os.path.join(CACHE_DIR, f"{code}.csv")
    today = dt.date.today().strftime("%Y%m%d")
    start = "20180101"
    if not full and os.path.exists(p):
        try:
            old = pd.read_csv(p, dtype={"date": str})
            if not old.empty:
                start = (dt.date.fromisoformat(old["date"].max()) - dt.timedelta(days=5)).strftime("%Y%m%d")
        except Exception:
            pass
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_daily_sina(symbol=sina_code(code), start_date=start,
                                          end_date=today, adjust="qfq")
            if df is None or df.empty:
                return None
            out = pd.DataFrame({
                "date": pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
                "open": pd.to_numeric(df["open"], errors="coerce"),
                "high": pd.to_numeric(df["high"], errors="coerce"),
                "low": pd.to_numeric(df["low"], errors="coerce"),
                "close": pd.to_numeric(df["close"], errors="coerce"),
                "volume": pd.to_numeric(df["volume"], errors="coerce"),
            }).dropna(subset=["close"])
            if os.path.exists(p) and start != "20180101":
                old = pd.read_csv(p, dtype={"date": str})
                out = pd.concat([old, out], ignore_index=True)
            out = out.drop_duplicates(subset=["date"]).sort_values("date")
            out.to_csv(p, index=False, encoding="utf-8-sig")
            return out
        except Exception:
            time.sleep(3 + random.uniform(0, 2))
    return None


def to_bars(df):
    return [{"date": str(r["date"]), "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"]),
             "volume": 0 if pd.isna(r["volume"]) else float(r["volume"])} for _, r in df.iterrows()]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    # 当天已生成则跳过（避免每半小时重复拉141只被限流），--force 强制重跑
    force = "--force" in sys.argv
    screen_path = os.path.join(OUT_DIR, "screen.js")
    if not force and os.path.exists(screen_path):
        try:
            mtime = dt.date.fromtimestamp(os.path.getmtime(screen_path))
            if mtime == dt.date.today():
                print(f"选股今日已生成（{mtime}），跳过。加 --force 可强制重跑。")
                return
        except Exception:
            pass

    comp = ak.index_component_sw(symbol=SW_SECTOR)
    comp = comp.rename(columns={"证券代码": "code", "证券名称": "name"})
    total = len(comp)
    print(f"成分股 {total} 只，开始拉取分析…")

    scored = []
    insufficient = 0
    failed = 0
    for idx, row in enumerate(comp.itertuples(), 1):
        code = str(row.code).zfill(6)
        name = row.name
        df = fetch_daily(code)
        if df is None or df.empty:
            failed += 1
            print(f"[{idx}/{total}] {name}({code}) 拉取失败")
            continue
        bars = to_bars(df)
        r = sa.score_stock(bars)
        if r is None:
            insufficient += 1
            print(f"[{idx}/{total}] {name}({code}) 数据不足({len(bars)})")
            continue
        r["code"] = code
        r["name"] = name
        scored.append(r)
        print(f"[{idx}/{total}] {name}({code}) 日{r['dailyScore']:+d} 周{r['weeklyScore']:+d} 排{r['rankScore']}")

    chosen, strict_count = sa.rank_top(scored, 20)

    # 生成个股K线分片 + items
    items = []
    for rank, (x, is_sub) in enumerate(chosen, 1):
        code = x["code"]
        items.append({
            "rank": rank, "code": code, "name": x["name"],
            "dailyScore": x["dailyScore"], "weeklyScore": x["weeklyScore"],
            "rankScore": x["rankScore"], "justStarted": x["justStarted"],
            "strictMatch": x["strictMatch"], "reason": x["reason"],
            "close": round(x["close"], 2), "lastDate": x["lastDate"],
            "dataFile": f"HT_Trading_System_data/sw_nonferrous/{code}.js",
            "substitute": is_sub,
        })

    # 写个股K线分片（用已缓存csv）
    for it in items:
        df = fetch_daily(it["code"])
        if df is None or df.empty:
            continue
        bars = [[str(r["date"]), round(float(r["open"]), 2), round(float(r["high"]), 2),
                 round(float(r["low"]), 2), round(float(r["close"]), 2),
                 int(0 if pd.isna(r["volume"]) else r["volume"])] for _, r in df.iterrows()]
        payload = json.dumps(bars, ensure_ascii=False, separators=(",", ":"))
        js = f'window.HT_STOCK_BARS=window.HT_STOCK_BARS||{{}};window.HT_STOCK_BARS[{json.dumps(it["code"])}]={payload};'
        with open(os.path.join(OUT_DIR, f'{it["code"]}.js'), "w", encoding="utf-8") as f:
            f.write(js)

    screen = {
        "constituents": total,
        "analyzed": len(scored),
        "strictMatches": strict_count,
        "insufficient": insufficient,
        "failed": failed,
        "generatedAt": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "screen.js"), "w", encoding="utf-8") as f:
        f.write("window.HT_SW_SCREEN=" + json.dumps(screen, ensure_ascii=False, separators=(",", ":")) + ";")

    print(f"\n完成：成分{total} 分析{len(scored)} 严格符合{strict_count} 不足{insufficient} 失败{failed}")
    print(f"前20已生成，用时 {time.time()-t0:.0f}s")
    print(f"输出：{OUT_DIR}")


if __name__ == "__main__":
    main()
