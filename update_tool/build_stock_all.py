# -*- coding: utf-8 -*-
"""全行业股票筛选：申万 31 个一级行业，各行业按股票SKILL.md规则筛前20。

数据：akshare index_component_sw 取成分股；日K 前复权（data_stock 缓存，增量）。
并发 8 线程（实测 3.2 只/秒，全量约 25-30 分钟）。
输出：HT_Trading_System_data/all_screen.js + all_bars/{industry}.js（每行业前20的K线）
"""
import os
import re
import sys
import json
import time
import random
import datetime as dt
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import akshare as ak

warnings.filterwarnings("ignore")

from config import ROOT
import stock_algo as sa

OUT_DIR = os.path.join(ROOT, "HT_Trading_System_data")
BARS_DIR = os.path.join(OUT_DIR, "all_bars")
CACHE_DIR = os.path.join(ROOT, "update_tool", "data_stock")

SW_INDUSTRIES = [
    ("801010", "农林牧渔"), ("801030", "基础化工"), ("801040", "钢铁"), ("801050", "有色金属"),
    ("801080", "电子"), ("801110", "家用电器"), ("801120", "食品饮料"), ("801130", "纺织服饰"),
    ("801140", "轻工制造"), ("801150", "医药生物"), ("801160", "公用事业"), ("801170", "交通运输"),
    ("801180", "房地产"), ("801200", "商贸零售"), ("801210", "社会服务"), ("801230", "综合"),
    ("801710", "建筑材料"), ("801720", "建筑装饰"), ("801730", "电力设备"), ("801740", "国防军工"),
    ("801750", "计算机"), ("801760", "传媒"), ("801770", "通信"), ("801780", "银行"),
    ("801790", "非银金融"), ("801880", "汽车"), ("801890", "机械设备"), ("801950", "煤炭"),
    ("801960", "石油石化"), ("801970", "环保"), ("801980", "美容护理"),
]

WORKERS = 10
CACHED_ONLY = False
# 评分只需 ~121 根日K、周线需 ~30 周（约150交易日）。首次拉 500 天足够，
# 避免拉 2018 年起 2000+ 根导致全量耗时翻倍。
FIRST_START_DAYS = 500


def sina_code(code):
    if code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def fetch_daily(code, cached_only=False):
    """增量拉取日K（前复权）。东财优先（实测快6倍），失败降级新浪。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    p = os.path.join(CACHE_DIR, f"{code}.csv")
    if cached_only:
        if os.path.exists(p):
            try:
                df = pd.read_csv(p, dtype={"date": str})
                return df if not df.empty else None
            except Exception:
                return None
        return None
    today = dt.date.today()
    start = (today - dt.timedelta(days=FIRST_START_DAYS)).strftime("%Y%m%d")
    if os.path.exists(p):
        try:
            old = pd.read_csv(p, dtype={"date": str})
            if not old.empty:
                start = (dt.date.fromisoformat(old["date"].max()) - dt.timedelta(days=5)).strftime("%Y%m%d")
        except Exception:
            pass
    end = today.strftime("%Y%m%d")

    out = None
    # 东财接口内部走 py_mini_racer(V8)，多线程并发会 FATAL 崩溃，故只用新浪
    # 新浪
    if out is None or out.empty:
        for attempt in range(2):
            try:
                df = ak.stock_zh_a_daily_sina(symbol=sina_code(code), start_date=start,
                                              end_date=end, adjust="qfq")
                if df is not None and not df.empty:
                    out = pd.DataFrame({
                        "date": pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
                        "open": pd.to_numeric(df["open"], errors="coerce"),
                        "high": pd.to_numeric(df["high"], errors="coerce"),
                        "low": pd.to_numeric(df["low"], errors="coerce"),
                        "close": pd.to_numeric(df["close"], errors="coerce"),
                        "volume": pd.to_numeric(df["volume"], errors="coerce"),
                    }).dropna(subset=["close"])
                    break
            except Exception:
                time.sleep(0.8 + random.uniform(0, 0.8))
    if out is None or out.empty:
        return None

    if os.path.exists(p) and start != (today - dt.timedelta(days=FIRST_START_DAYS)).strftime("%Y%m%d"):
        try:
            old = pd.read_csv(p, dtype={"date": str})
            out = pd.concat([old, out], ignore_index=True)
        except Exception:
            pass
    out = out.drop_duplicates(subset=["date"]).sort_values("date")
    out.to_csv(p, index=False, encoding="utf-8-sig")
    return out


def to_bars(df):
    return [{"date": str(r["date"]), "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"]),
             "volume": 0 if pd.isna(r["volume"]) else float(r["volume"])} for _, r in df.iterrows()]


def process_stock(args):
    """(code, name) -> (result_dict|None, bars|None)"""
    code, name, cached_only = args
    df = fetch_daily(code, cached_only=cached_only)
    if df is None or df.empty:
        return None, None
    bars = to_bars(df)
    r = sa.score_stock(bars)
    if r is None:
        return None, None
    r["code"] = code
    r["name"] = name
    return r, bars


def main():
    global CACHED_ONLY
    only = None
    for a in sys.argv:
        if a.startswith("--only="):
            only = a.split("=", 1)[1].split(",")
        if a == "--cached":
            CACHED_ONLY = True
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(BARS_DIR, exist_ok=True)

    t0 = time.time()
    industries = []
    for i, (icode, iname) in enumerate(SW_INDUSTRIES, 1):
        if only and iname not in only and icode not in only:
            continue
        try:
            comp = None
            for attempt in range(3):
                try:
                    comp = ak.index_component_sw(symbol=icode)
                    if comp is not None and not comp.empty:
                        break
                except Exception:
                    time.sleep(2 + random.uniform(0, 2))
            if comp is None or comp.empty:
                print(f"[{i}/31] {iname} 成分股获取失败（重试后仍空）")
                continue
            comp = comp.rename(columns={"证券代码": "code", "证券名称": "name"})
            stocks = [(str(r.code).zfill(6), r.name) for r in comp.itertuples()]
        except Exception as e:
            print(f"[{i}/31] {iname} 成分股获取失败 {e}")
            continue

        scored = []
        done = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(process_stock, (s[0], s[1], CACHED_ONLY)): s for s in stocks}
            for fu in as_completed(futs):
                done += 1
                try:
                    r, bars = fu.result()
                    if r:
                        scored.append(r)  # 不保留 bars，省内存
                except Exception:
                    pass

        chosen, strict_count = sa.rank_top(scored, 20)

        # 生成该行业 K线分片（前20，精简最近300根）——按需从缓存读取
        payload = {}
        items = []
        for rank, (x, is_sub) in enumerate(chosen, 1):
            cp = os.path.join(CACHE_DIR, f"{x['code']}.csv")
            try:
                dfx = pd.read_csv(cp, dtype={"date": str})
                bars = to_bars(dfx)
            except Exception:
                bars = []
            compact = [[b["date"], round(b["open"], 2), round(b["high"], 2), round(b["low"], 2),
                        round(b["close"], 2), int(b["volume"] or 0)] for b in bars[-300:]]
            payload[x["code"]] = compact
            items.append({
                "rank": rank, "code": x["code"], "name": x["name"],
                "dailyScore": x["dailyScore"], "weeklyScore": x["weeklyScore"],
                "rankScore": x["rankScore"], "justStarted": x["justStarted"],
                "strictMatch": x["strictMatch"], "reason": x["reason"],
                "close": round(x["close"], 2), "lastDate": x["lastDate"],
                "substitute": is_sub,
            })

        js = "window.HT_ALL_BARS=window.HT_ALL_BARS||{};" \
             f"window.HT_ALL_BARS[{json.dumps(icode)}]=" \
             + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";"
        with open(os.path.join(BARS_DIR, f"{icode}.js"), "w", encoding="utf-8") as f:
            f.write(js)

        industries.append({
            "code": icode, "name": iname,
            "total": len(stocks), "analyzed": len(scored), "strict": strict_count,
            "barsFile": f"HT_Trading_System_data/all_bars/{icode}.js",
            "items": items,
        })
        print(f"[{i}/31] {iname}: 成分{len(stocks)} 分析{len(scored)} 严格{strict_count} "
              f"用时{time.time()-t0:.0f}s")

    data = {
        "generatedAt": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "industries": industries,
    }
    with open(os.path.join(OUT_DIR, "all_screen.js"), "w", encoding="utf-8") as f:
        f.write("window.HT_ALL_SCREEN=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";")
    print(f"\n完成：{len(industries)} 个行业，总用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
