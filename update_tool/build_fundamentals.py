# -*- coding: utf-8 -*-
"""拉取全行业选股前20（620只）的基本面数据，供K线图下方展示。

指标：
  1) 主营业务介绍（stock_zyjs_ths）
  2) 历史年度营业总收入 / 归母净利润（stock_financial_abstract）
  3) 毛利率 / ROE（同上）
  4) 历史分红比例、股息率（stock_fhps_detail_em）
  5) PE(TTM 近似取快照动态市盈率)、最新股息率

注意：东财接口内部走 py_mini_racer(V8)，**多线程并发会 FATAL 崩溃**，故并发压到 2。
输出：HT_Trading_System_data/fundamentals.js -> window.HT_FUNDAMENTALS
"""
import os
import re
import json
import time
import random
import warnings
from concurrent.futures import ThreadPoolExecutor

import akshare as ak

warnings.filterwarnings("ignore")

from config import ROOT

DATA = os.path.join(ROOT, "HT_Trading_System_data")
ALL_SCREEN = os.path.join(DATA, "all_screen.js")
OUT = os.path.join(DATA, "fundamentals.js")
WORKERS = 2          # 东财 V8 不稳定，压低并发
MAX_YEARS = 12       # 展示最近12个年度


def safe_float(x):
    try:
        v = float(x)
        return v if v == v else None
    except Exception:
        return None


def fetch_one(code):
    out = {"code": code}

    # 1) 主营
    try:
        df = ak.stock_zyjs_ths(symbol=code)
        if df is not None and not df.empty:
            r = df.iloc[0]
            out["main"] = str(r.get("主营业务") or "").strip()
            out["products"] = str(r.get("产品类型") or "").strip()
    except Exception:
        pass

    # 2)+3) 财务摘要
    try:
        df = ak.stock_financial_abstract(symbol=code)
        if df is not None and not df.empty:
            ind_col = "指标"
            period_cols = [c for c in df.columns if re.fullmatch(r"\d{8}", str(c))]
            # 只取年报（1231）
            annual = [c for c in period_cols if str(c).endswith("1231")]
            annual.sort()
            annual = annual[-MAX_YEARS:]

            rows = {}
            for _, r in df.iterrows():
                rows[str(r[ind_col])] = r
            def pick(names):
                for n in names:
                    if n in rows:
                        return rows[n]
                return None
            rev_row = pick(["营业总收入"])
            np_row = pick(["归母净利润"])
            gm_row = pick(["毛利率"])
            roe_row = pick(["净资产收益率(ROE)"])

            years = []
            for p in annual:
                y = str(p)[:4]
                item = {"y": y}
                if rev_row is not None:
                    v = safe_float(rev_row.get(p))
                    item["rev"] = v
                if np_row is not None:
                    item["np"] = safe_float(np_row.get(p))
                if gm_row is not None:
                    item["gm"] = safe_float(gm_row.get(p))
                if roe_row is not None:
                    item["roe"] = safe_float(roe_row.get(p))
                if any(k in item for k in ("rev", "np", "gm", "roe")):
                    years.append(item)
            out["years"] = years

            # 最新一期（可能不是年报）
            latest = sorted(period_cols)[-1] if period_cols else None
            if latest:
                out["latestPeriod"] = str(latest)
                if rev_row is not None:
                    out["latestRev"] = safe_float(rev_row.get(latest))
                if np_row is not None:
                    out["latestNp"] = safe_float(np_row.get(latest))
    except Exception:
        pass

    # 4) 分红
    try:
        df = ak.stock_fhps_detail_em(symbol=code)
        if df is not None and not df.empty:
            divs = []
            for _, r in df.iterrows():
                d = {
                    "report": str(r.get("报告期") or ""),
                    "plan": str(r.get("现金分红-现金分红比例描述") or ""),
                    "ratio": safe_float(r.get("现金分红-现金分红比例")),
                    "yield": safe_float(r.get("现金分红-股息率")),
                }
                if d["plan"] or d["ratio"]:
                    divs.append(d)
            out["dividends"] = divs[-12:]
    except Exception:
        pass

    return code, out


def main():
    with open(ALL_SCREEN, "r", encoding="utf-8") as f:
        data = json.loads(re.search(r"window\.HT_ALL_SCREEN=(.*);\s*$", f.read(), re.S).group(1))

    codes = []
    for ind in data["industries"]:
        for it in ind["items"]:
            if it["code"] not in codes:
                codes.append(it["code"])

    # PE(TTM近似)：全市场快照的动态市盈率
    pe_map = {}
    try:
        spot = ak.stock_zh_a_spot_em()
        for _, r in spot.iterrows():
            c = str(r["代码"]).zfill(6)
            pe_map[c] = safe_float(r.get("市盈率-动态"))
    except Exception as e:
        print("快照获取失败（PE将缺失）:", str(e)[:60])

    t0 = time.time()
    result = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_one, c): c for c in codes}
        done = 0
        for fu in futs:
            pass
        from concurrent.futures import as_completed
        for fu in as_completed(futs):
            done += 1
            try:
                code, d = fu.result()
                if pe_map.get(code) is not None:
                    d["pe"] = pe_map[code]
                result[code] = d
            except Exception:
                pass
            if done % 50 == 0:
                print(f"  已处理 {done}/{len(codes)}，用时{time.time()-t0:.0f}s", flush=True)

    payload = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "data": result,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("window.HT_FUNDAMENTALS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";")
    print(f"完成：{len(result)}/{len(codes)} 只，用时{time.time()-t0:.0f}s，文件 {os.path.getsize(OUT)/1024:.0f}KB")


if __name__ == "__main__":
    main()
