# -*- coding: utf-8 -*-
"""生成外盘数据分片 external.js（window.HT_EXTERNAL_DATA）+ 各品种K线分片。

品种：LME 六金属 + COMEX 金银（新浪外盘源）
评分：复用 score_algo（HT四周期技术评分），字段兼容页面（weinstein_score 别名）。
"""
import os
import json
import time
import random
import warnings
import datetime as dt

import pandas as pd
import akshare as ak

warnings.filterwarnings("ignore")

from config import ROOT
import score_algo as sa

OUT_DIR = os.path.join(ROOT, "HT_Trading_System_data")

# (新浪代码, 显示名, 单位)
EXTERNAL = [
    ("CAD", "LME铜", "美元/吨"),
    ("AHD", "LME铝", "美元/吨"),
    ("ZSD", "LME锌", "美元/吨"),
    ("PBD", "LME铅", "美元/吨"),
    ("NID", "LME镍", "美元/吨"),
    ("SND", "LME锡", "美元/吨"),
    ("GC", "COMEX黄金", "美元/盎司"),
    ("SI", "COMEX白银", "美元/盎司"),
]


def fetch(symbol):
    for attempt in range(3):
        try:
            df = ak.futures_foreign_hist_sina(symbol=symbol)
            if df is None or df.empty:
                return None
            out = pd.DataFrame({
                "date": pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
                "open": pd.to_numeric(df["open"], errors="coerce"),
                "high": pd.to_numeric(df["high"], errors="coerce"),
                "low": pd.to_numeric(df["low"], errors="coerce"),
                "close": pd.to_numeric(df["close"], errors="coerce"),
                "volume": pd.to_numeric(df.get("volume", 0), errors="coerce"),
            }).dropna(subset=["close"])
            out = out.drop_duplicates(subset=["date"]).sort_values("date")
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
    items = []
    for sym, name, unit in EXTERNAL:
        df = fetch(sym)
        if df is None or df.empty:
            print(f"{name}({sym}) 拉取失败")
            continue
        bars = to_bars(df)
        res = sa.score_symbol(bars)
        if res["status"] != "ok":
            print(f"{name}({sym}) 数据不足 {len(bars)}")
            continue

        # 页面字段兼容：weinstein_score = tsai_score 别名
        periods = {}
        for p, d in res["periods"].items():
            dd = dict(d)
            dd["weinstein_score"] = dd.get("tsai_score")
            periods[p] = dd

        data_file = f"HT_Trading_System_data/ex_{sym}.js"
        items.append({
            "code": sym, "name": name, "unit": unit,
            "close": round(bars[-1]["close"], 2), "end": bars[-1]["date"],
            "periods": periods,
            "score": res["score"], "direction": res["direction"], "note": res["note"],
            "dataFile": data_file,
        })

        # K线分片
        compact = [[b["date"], round(b["open"], 2), round(b["high"], 2), round(b["low"], 2),
                    round(b["close"], 2), int(b["volume"] or 0)] for b in bars]
        js = ('window.HT_BARS=window.HT_BARS||{};window.HT_BARS['
              + json.dumps(sym) + ']=' + json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + ";")
        with open(os.path.join(OUT_DIR, f"ex_{sym}.js"), "w", encoding="utf-8") as f:
            f.write(js)
        print(f"{name}({sym}) OK {len(bars)}根 收{bars[-1]['close']} 总分{res['score']} {res['direction']}")

    data = {
        "source": "新浪外盘期货（LME/COMEX）",
        "generatedAt": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
    }
    with open(os.path.join(OUT_DIR, "external.js"), "w", encoding="utf-8") as f:
        f.write("window.HT_EXTERNAL_DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";")
    print(f"\n外盘数据生成完成：{len(items)} 个品种")


if __name__ == "__main__":
    main()
