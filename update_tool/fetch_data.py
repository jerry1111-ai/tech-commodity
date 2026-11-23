# -*- coding: utf-8 -*-
"""从 HTML 解析品种清单，用 akshare 拉取历史日K，增量缓存为 CSV。

每次运行：读取每个品种已有缓存的最后日期，仅拉取增量部分并追加，
避免全量重复拉取（东财/新浪接口对高频请求敏感）。

用法：
    python fetch_data.py            # 增量更新全部品种
    python fetch_data.py --full     # 强制全量重拉
    python fetch_data.py --only 沪铝,螺纹钢   # 仅更新指定品种
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

from config import (
    HTML_PATH, DATA_DIR, LOG_DIR, HIST_START,
    SRC_FUT, SRC_SW, SRC_CSI, SRC_YAHOO_PREFIX, OVERSEA_MAP,
)

# 统一列结构
COLS = ["date", "open", "high", "low", "close", "volume"]


def load_db():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"const DB=(\{.*?\});", html, re.S)
    if not m:
        raise RuntimeError("无法从 HTML 中解析 DB 数据块")
    return json.loads(m.group(1))


def safe_symbol(item):
    """返回 (src_type, akshare_symbol) 或 (None, None) 表示跳过。"""
    src = item.get("source", "")
    code = item.get("code", "")
    if src == SRC_FUT:
        # RB.SHF -> RB0
        return "fut", code.split(".")[0] + "0"
    if src == SRC_SW:
        # 801050.SI -> 801050
        return "sw", code.split(".")[0]
    if src == SRC_CSI:
        # 000922.CSI -> 000922
        return "csi", code.split(".")[0]
    if src.startswith(SRC_YAHOO_PREFIX):
        return "oversea", OVERSEA_MAP.get(code)
    return None, None


def _call_with_retry(fn, max_retry=3, **kwargs):
    """对接口调用做简单重试，处理限流/网络抖动。"""
    last = None
    for attempt in range(max_retry):
        try:
            return fn(**kwargs)
        except Exception as e:
            last = e
            # 遇限流退避更久
            wait = (5 if attempt == 0 else 10) + random.uniform(0, 2)
            time.sleep(wait)
    raise last


def fetch_fut(symbol, start, end):
    df = _call_with_retry(
        ak.futures_main_sina,
        symbol=symbol,
        start_date=start,
        end_date=end,
    )
    out = pd.DataFrame({
        "date": pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d"),
        "open": pd.to_numeric(df["开盘价"], errors="coerce"),
        "high": pd.to_numeric(df["最高价"], errors="coerce"),
        "low": pd.to_numeric(df["最低价"], errors="coerce"),
        "close": pd.to_numeric(df["收盘价"], errors="coerce"),
        "volume": pd.to_numeric(df["成交量"], errors="coerce"),
    })
    return out


def _norm_date(x):
    s = str(x).replace("-", "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return str(x)


def fetch_sw(symbol, start, end):
    s, e = _norm_date(start), _norm_date(end)
    df = _call_with_retry(ak.index_hist_sw, symbol=symbol, period="day")
    dts = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d")
    df = df[(dts >= s) & (dts <= e)]
    out = pd.DataFrame({
        "date": pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d"),
        "open": pd.to_numeric(df["开盘"], errors="coerce"),
        "high": pd.to_numeric(df["最高"], errors="coerce"),
        "low": pd.to_numeric(df["最低"], errors="coerce"),
        "close": pd.to_numeric(df["收盘"], errors="coerce"),
        "volume": pd.to_numeric(df["成交量"], errors="coerce"),
    })
    # 申万官网接口常滞后：用 index_analysis_daily_sw 补最新缺失日期（仅收盘，OHLC 以邻日收盘近似）
    try:
        cur_max = out["date"].max() if not out.empty else ""
        if cur_max < e:
            # 一级行业不含细分（半导体/新材料/保险等在二级行业），逐个分类探测
            sub = None
            for cat in ("一级行业", "二级行业"):
                try:
                    patch = ak.index_analysis_daily_sw(symbol=cat, start_date=s.replace("-", ""),
                                                       end_date=e.replace("-", ""))
                except Exception:
                    continue
                t = patch[patch["指数代码"].astype(str) == symbol]
                if not t.empty:
                    sub = t
                    break
            existing = set(out["date"]) if not out.empty else set()
            prev_close = float(out["close"].iloc[-1]) if not out.empty else None
            rows = []
            if sub is not None:
                for _, r in sub.sort_values("发布日期").iterrows():
                    d = str(r["发布日期"])
                    if d in existing:
                        continue
                    c = float(r["收盘指数"])
                    v = float(r["成交量"]) if pd.notna(r.get("成交量")) else 0
                    op = prev_close if prev_close is not None else c
                    rows.append({"date": d, "open": op, "high": max(op, c), "low": min(op, c),
                                 "close": c, "volume": v})
                    prev_close = c
            if rows:
                out = pd.concat([out, pd.DataFrame(rows)], ignore_index=True)
                out = out.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    except Exception:
        pass
    return out


def fetch_csi(symbol, start, end):
    df = _call_with_retry(
        ak.index_hist_csindex,
        symbol=symbol,
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
    )
    out = pd.DataFrame({
        "date": pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d"),
        "open": pd.to_numeric(df["开盘"], errors="coerce"),
        "high": pd.to_numeric(df["最高"], errors="coerce"),
        "low": pd.to_numeric(df["最低"], errors="coerce"),
        "close": pd.to_numeric(df["收盘"], errors="coerce"),
        "volume": pd.to_numeric(df["成交量"], errors="coerce"),
    })
    return out


def fetch_oversea(symbol, start, end):
    df = _call_with_retry(ak.index_us_daily_sina, symbol=symbol)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    out = pd.DataFrame({
        "date": df["date"],
        "open": pd.to_numeric(df["open"], errors="coerce"),
        "high": pd.to_numeric(df["high"], errors="coerce"),
        "low": pd.to_numeric(df["low"], errors="coerce"),
        "close": pd.to_numeric(df["close"], errors="coerce"),
        "volume": pd.to_numeric(df["volume"], errors="coerce"),
    })
    return out


FETCHERS = {
    "fut": fetch_fut,
    "sw": fetch_sw,
    "csi": fetch_csi,
    "oversea": fetch_oversea,
}


def data_path(code):
    safe = re.sub(r"[^0-9A-Za-z]", "_", code)
    return os.path.join(DATA_DIR, safe + ".csv")


def load_cache(code):
    p = data_path(code)
    if not os.path.exists(p):
        return None
    try:
        df = pd.read_csv(p, dtype={"date": str})
        if df.empty:
            return None
        return df[COLS]
    except Exception:
        return None


def save_cache(code, df):
    df = df.dropna(subset=["date"]).drop_duplicates(subset=["date"]).sort_values("date")
    df = df[COLS].reset_index(drop=True)
    df.to_csv(data_path(code), index=False, encoding="utf-8-sig")
    return df


def update_item(item, full=False, today=None):
    today = today or datetime.now().strftime("%Y-%m-%d")
    code = item["code"]
    src_type, sym = safe_symbol(item)
    if not sym:
        return {"code": code, "name": item["name"], "status": "skip", "rows": 0, "msg": "无映射"}

    cache = load_cache(code)
    if full or cache is None:
        start = HIST_START
    else:
        # 从缓存最后日期的前3天开始拉，保证衔接
        last = cache["date"].max()
        d = datetime.strptime(last, "%Y-%m-%d") - timedelta(days=3)
        start = d.strftime("%Y%m%d")

    end = datetime.strptime(today, "%Y-%m-%d").strftime("%Y%m%d")

    try:
        new = FETCHERS[src_type](sym, start, end)
    except Exception as e:
        return {"code": code, "name": item["name"], "status": "error",
                "rows": len(cache) if cache is not None else 0,
                "msg": f"{type(e).__name__}: {str(e)[:80]}"}

    if new is None or new.empty:
        return {"code": code, "name": item["name"], "status": "empty",
                "rows": len(cache) if cache is not None else 0, "msg": "无增量数据"}

    if cache is None:
        merged = new
    else:
        merged = pd.concat([cache, new], ignore_index=True)
    merged = save_cache(code, merged)
    return {"code": code, "name": item["name"], "status": "ok",
            "rows": len(merged), "last": merged["date"].max(), "msg": ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="强制全量重拉")
    ap.add_argument("--only", type=str, default="", help="仅更新指定品种，逗号分隔名称")
    ap.add_argument("--date", type=str, default="", help="指定截止日期 YYYY-MM-DD")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    db = load_db()
    items = db["items"]
    only = [x.strip() for x in args.only.split(",") if x.strip()]
    if only:
        items = [i for i in items if i["name"] in only]

    results = []
    t0 = time.time()
    for idx, item in enumerate(items, 1):
        r = update_item(item, full=args.full, today=args.date or None)
        results.append(r)
        flag = {"ok": "OK", "skip": "SKIP", "empty": "EMPTY", "error": "ERR"}.get(r["status"], "?")
        print(f"[{idx:>3}/{len(items)}] {flag:<5} {item['name']:<12} "
              f"{r.get('last',''):<12} rows={r['rows']:<6} {r['msg']}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logf = os.path.join(LOG_DIR, f"fetch_{stamp}.json")
    with open(logf, "w", encoding="utf-8") as f:
        json.dump({"time": stamp, "results": results}, f, ensure_ascii=False, indent=2)

    okc = sum(1 for r in results if r["status"] == "ok")
    errc = sum(1 for r in results if r["status"] == "error")
    print(f"\n完成：成功 {okc} / 失败 {errc} / 共 {len(results)}，用时 {time.time()-t0:.1f}s")
    print(f"日志：{logf}")


if __name__ == "__main__":
    main()
