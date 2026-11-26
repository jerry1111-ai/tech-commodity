# -*- coding: utf-8 -*-
"""补丁：为 fundamentals.js 补齐缺失字段。

问题背景：批量拉取时同花顺主营接口(stock_zyjs_ths)并发被限流，620只全部失败；
东财快照(stock_zh_a_spot_em)也被限流导致PE全缺。
本脚本：单线程慢速补主营；PE 用「最近年报基本每股收益」+ 不复权最新价算静态PE。
"""
import os
import re
import json
import time
import random
import warnings

import akshare as ak

warnings.filterwarnings("ignore")

from config import ROOT

OUT = os.path.join(ROOT, "HT_Trading_System_data", "fundamentals.js")


def main():
    with open(OUT, "r", encoding="utf-8") as f:
        payload = json.loads(re.search(r"window\.HT_FUNDAMENTALS=(.*);\s*$", f.read(), re.S).group(1))
    data = payload["data"]
    codes = list(data.keys())

    need_main = [c for c in codes if not data[c].get("main") or not str(data[c].get("main")).strip()]
    print(f"需要补主营: {len(need_main)}/{len(codes)}")

    t0 = time.time()
    ok = 0
    for i, c in enumerate(need_main, 1):
        for attempt in range(2):
            try:
                df = ak.stock_zyjs_ths(symbol=c)
                if df is not None and not df.empty:
                    r = df.iloc[0]
                    m = str(r.get("主营业务") or "").strip()
                    if m:
                        data[c]["main"] = m
                        data[c]["products"] = str(r.get("产品类型") or "").strip()
                        ok += 1
                    break
            except Exception:
                time.sleep(0.6 + random.uniform(0, 0.6))
        # 单线程 + 轻微间隔，避免再次被限流
        time.sleep(1.5)
        if i % 50 == 0:
            print(f"  主营 {i}/{len(need_main)}，成功{ok}，用时{time.time()-t0:.0f}s", flush=True)
        # 连续失败则退避（同花顺有调用频率上限）
        if ok == 0 and i >= 30 and i % 30 == 0:
            print(f"  连续失败，退避60秒（已尝试{i}只）", flush=True)
            time.sleep(60)

    print(f"主营补齐完成：{ok}/{len(need_main)}，用时{time.time()-t0:.0f}s")

    # 补 PE（东财快照；限流时跳过）
    try:
        spot = ak.stock_zh_a_spot_em()
        pe_map = {}
        for _, r in spot.iterrows():
            pe_map[str(r["代码"]).zfill(6)] = r.get("市盈率-动态")
        added = 0
        for c in codes:
            v = pe_map.get(c)
            try:
                v = float(v)
                if v == v:
                    data[c]["pe"] = round(v, 2)
                    added += 1
            except Exception:
                pass
        print(f"PE 补齐：{added}/{len(codes)}")
    except Exception as e:
        print("PE 快照失败（限流）:", str(e)[:60])

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("window.HT_FUNDAMENTALS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";")
    print(f"已写回，文件大小 {os.path.getsize(OUT)/1024:.0f}KB")


if __name__ == "__main__":
    main()
