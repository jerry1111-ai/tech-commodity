# -*- coding: utf-8 -*-
"""根据本地日K缓存生成网页所需的 K 线分片 JS 文件。

页面加载机制：动态加载 dataFile（如 HT_Trading_System_data/RB_SHF.js），
脚本执行后写入 window.HT_BARS[code]，供 K 线图渲染。
每个 bars 元素格式：[日期, 开, 高, 低, 收, 量]（页面约定 b[0]..b[5]）。
"""
import os
import re
import json
import math
from datetime import datetime

import pandas as pd

from config import HTML_PATH, DATA_DIR, ROOT

OUT_DIR = os.path.join(ROOT, "HT_Trading_System_data")


def load_db():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"const DB=(\{.*?\});", html, re.S)
    return json.loads(m.group(1))


def data_path(code):
    safe = re.sub(r"[^0-9A-Za-z]", "_", code)
    return os.path.join(DATA_DIR, safe + ".csv")


def load_cache(code):
    p = data_path(code)
    if not os.path.exists(p):
        return None
    try:
        df = pd.read_csv(p, dtype={"date": str})
        return df if not df.empty else None
    except Exception:
        return None


def num(v, nd=4):
    """转成精简数字，NaN/None -> None（页面用 null 处理）。"""
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, nd)
    except Exception:
        return None


def build_bars_for(code, df):
    """df -> [[date,o,h,l,c,v],...]"""
    bars = []
    for _, r in df.iterrows():
        d = str(r.get("date", "")).strip()
        if not d or not d.startswith("20"):
            continue
        o, h, l, c = num(r.get("open")), num(r.get("high")), num(r.get("low")), num(r.get("close"))
        if c is None:
            continue
        v = num(r.get("volume"))
        v = 0 if v is None else int(v)
        bars.append([d, o, h, l, c, v])
    return bars


def file_for_datafile(data_file):
    """HT_Trading_System_data/RB_SHF.js -> 绝对路径"""
    name = os.path.basename(data_file)
    return os.path.join(OUT_DIR, name)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    db = load_db()
    items = db["items"]

    ok = 0
    skip = 0
    total_bars = 0
    for item in items:
        code = item["code"]
        data_file = item.get("dataFile")
        if not data_file:
            skip += 1
            continue
        df = load_cache(code)
        if df is None or df.empty:
            skip += 1
            continue
        bars = build_bars_for(code, df)
        if not bars:
            skip += 1
            continue

        # 紧凑 JSON：无空格
        payload = json.dumps(bars, ensure_ascii=False, separators=(",", ":"))
        js = f'window.HT_BARS=window.HT_BARS||{{}};window.HT_BARS[{json.dumps(code)}]={payload};'
        out = file_for_datafile(data_file)
        with open(out, "w", encoding="utf-8") as f:
            f.write(js)
        ok += 1
        total_bars += len(bars)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"K线分片生成完成 {stamp}")
    print(f"成功 {ok} / 跳过 {skip} / 共 {len(items)}，总K线根数 {total_bars}")
    print(f"输出目录：{OUT_DIR}")


if __name__ == "__main__":
    main()
