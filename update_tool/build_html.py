# -*- coding: utf-8 -*-
"""同步更新 HTML 内嵌 DB：行情字段 + 技术评分（严格按 SKILL.md 规格重算）。

更新内容：
- 行情：close / end / start / rowCount / volumeCount / volumeCoverage
- 评分：score / direction / note / support / resistance / periods（四周期全套）
评分按 ht-market-scoring SKILL.md 计算，口径可复现。
"""
import os
import re
import json
import shutil
from datetime import datetime

import pandas as pd

from config import HTML_PATH, DATA_DIR, TOOL_DIR
import score_algo as sa


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


def to_bars(df):
    bars = []
    for _, r in df.iterrows():
        try:
            o = float(r["open"]); h = float(r["high"]); l = float(r["low"]); c = float(r["close"])
        except Exception:
            continue
        if any(pd.isna(v) for v in (o, h, l, c)):
            continue
        # 剔除非法 OHLC
        if h < l or h < max(o, c) or l > min(o, c):
            continue
        v = r.get("volume")
        vol = 0.0 if pd.isna(v) else float(v)
        bars.append({"date": str(r["date"]), "open": o, "high": h, "low": l, "close": c, "volume": vol})
    return bars


def main():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    m = re.search(r"const DB=(\{.*?\});", html, re.S)
    if not m:
        raise RuntimeError("无法定位 DB 数据块")
    db = json.loads(m.group(1))

    stat = {"score_ok": 0, "insufficient": 0, "no_cache": 0}
    for item in db["items"]:
        df = load_cache(item["code"])
        if df is None or df.empty:
            stat["no_cache"] += 1
            continue
        bars = to_bars(df)
        if not bars:
            stat["no_cache"] += 1
            continue

        # --- 行情字段 ---
        last = bars[-1]
        item["close"] = last["close"]
        item["end"] = last["date"]
        item["start"] = bars[0]["date"]
        item["rowCount"] = len(bars)
        vol_cnt = sum(1 for b in bars if b["volume"] and b["volume"] > 0)
        item["volumeCount"] = vol_cnt
        item["volumeCoverage"] = round(vol_cnt / len(bars) * 100, 1) if bars else 0.0

        # --- 评分 ---
        res = sa.score_symbol(bars)
        if res["status"] != "ok":
            stat["insufficient"] += 1
            item["status"] = "insufficient"
            item["error"] = f"有效K线不足（{len(bars)}根，需≥80）"
            continue

        item["status"] = "ok"
        item["error"] = None
        item["score"] = res["score"]
        item["direction"] = res["direction"]
        item["note"] = res["note"]
        item["support"] = res["support"]
        item["resistance"] = res["resistance"]
        item["periods"] = res["periods"]
        stat["score_ok"] += 1

    db["generatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M 中国标准时间")

    new_json = json.dumps(db, ensure_ascii=False, separators=(",", ":"))
    new_html = html[:m.start(1)] + new_json + html[m.end(1):]

    # 写前校验
    check = re.search(r"const DB=(\{.*?\});", new_html, re.S)
    json.loads(check.group(1))

    bak = os.path.join(TOOL_DIR, "backup_before_htmlsync.html")
    shutil.copyfile(HTML_PATH, bak)

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(new_html)

    # 同步一份到 index.html（GitHub Pages 根路径默认页）
    try:
        index_path = os.path.join(os.path.dirname(HTML_PATH), "index.html")
        shutil.copyfile(HTML_PATH, index_path)
        print(f"已同步 index.html")
    except Exception as e:
        print(f"index.html 同步失败：{e}")

    print(f"HTML 同步完成：评分成功 {stat['score_ok']} / 数据不足 {stat['insufficient']} / 无缓存 {stat['no_cache']}")
    print(f"生成时间戳：{db['generatedAt']}")
    print(f"备份：{bak}")


if __name__ == "__main__":
    main()
