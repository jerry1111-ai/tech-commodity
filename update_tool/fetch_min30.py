# -*- coding: utf-8 -*-
"""拉取 75 个期货主连的 30 分钟 K 线，增量缓存为 CSV。

数据源：akshare futures_zh_min_sina(period='30')（新浪）
注意：该接口仅返回最近约 4 个月滚动数据（约 1023 根），无法获取更早历史。
每次增量：从本地缓存最后时间戳往前回退 2 天重新拉，按 datetime 去重合并。

用法：
    python fetch_min30.py            # 增量更新
    python fetch_min30.py --full     # 强制全量重拉
    python fetch_min30.py --only 沪铝,螺纹钢
"""
import os
import re
import json
import time
import random
import argparse
import warnings
from datetime import datetime, timedelta

import pandas as pd
import akshare as ak

warnings.filterwarnings("ignore")

from config import HTML_PATH, DATA_MIN30_DIR, LOG_DIR, SRC_FUT

COLS = ["datetime", "open", "high", "low", "close", "volume", "hold"]


def load_db():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"const DB=(\{.*?\});", html, re.S)
    return json.loads(m.group(1))


def fut_symbols():
    db = load_db()
    return [i for i in db["items"] if i.get("source") == SRC_FUT]


def cache_path(code):
    safe = re.sub(r"[^0-9A-Za-z]", "_", code)
    return os.path.join(DATA_MIN30_DIR, safe + ".csv")


def load_cache(code):
    p = cache_path(code)
    if not os.path.exists(p):
        return None
    try:
        df = pd.read_csv(p, dtype={"datetime": str})
        return df if not df.empty else None
    except Exception:
        return None


def save_cache(code, df):
    df = df.dropna(subset=["datetime"]).drop_duplicates(subset=["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    df[COLS].to_csv(cache_path(code), index=False, encoding="utf-8-sig")
    return df[COLS]


def fetch(symbol):
    last = None
    for attempt in range(3):
        try:
            df = ak.futures_zh_min_sina(symbol=symbol, period="30")
            out = pd.DataFrame({
                "datetime": pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d %H:%M:%S"),
                "open": pd.to_numeric(df["open"], errors="coerce"),
                "high": pd.to_numeric(df["high"], errors="coerce"),
                "low": pd.to_numeric(df["low"], errors="coerce"),
                "close": pd.to_numeric(df["close"], errors="coerce"),
                "volume": pd.to_numeric(df["volume"], errors="coerce"),
                "hold": pd.to_numeric(df["hold"], errors="coerce"),
            })
            return out
        except Exception as e:
            last = e
            time.sleep((4 if attempt == 0 else 8) + random.uniform(0, 2))
    raise last


def update_item(item, full=False):
    code = item["code"]
    symbol = code.split(".")[0] + "0"
    cache = load_cache(code)
    try:
        new = fetch(symbol)
    except Exception as e:
        return {"code": code, "name": item["name"], "status": "error",
                "rows": len(cache) if cache is not None else 0,
                "msg": f"{type(e).__name__}: {str(e)[:70]}"}

    if new is None or new.empty:
        return {"code": code, "name": item["name"], "status": "empty",
                "rows": len(cache) if cache is not None else 0, "msg": "无数据"}

    if full or cache is None:
        merged = new
    else:
        # 接口只给滚动窗口，直接全量替换即可（数据本身即最近窗口）
        merged = new
    merged = save_cache(code, merged)
    return {"code": code, "name": item["name"], "status": "ok",
            "rows": len(merged), "last": merged["datetime"].iloc[-1], "msg": ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--only", type=str, default="")
    args = ap.parse_args()

    os.makedirs(DATA_MIN30_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    items = fut_symbols()
    only = [x.strip() for x in args.only.split(",") if x.strip()]
    if only:
        items = [i for i in items if i["name"] in only]

    results = []
    t0 = time.time()
    for idx, item in enumerate(items, 1):
        r = update_item(item, full=args.full)
        results.append(r)
        flag = {"ok": "OK", "empty": "EMPTY", "error": "ERR"}.get(r["status"], "?")
        print(f"[{idx:>3}/{len(items)}] {flag:<5} {item['name']:<12} "
              f"{r.get('last',''):<18} rows={r['rows']:<6} {r['msg']}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(LOG_DIR, f"fetch_min30_{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump({"time": stamp, "results": results}, f, ensure_ascii=False, indent=2)

    okc = sum(1 for r in results if r["status"] == "ok")
    errc = sum(1 for r in results if r["status"] == "error")
    print(f"\n完成：成功 {okc} / 失败 {errc} / 共 {len(results)}，用时 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
