# -*- coding: utf-8 -*-
"""生成网页宏观数据分片 macro.js（window.MACRO_DATA + window.MACRO_EXTRA_DATA）。"""
import os
import json
import math
import datetime as dt

import pandas as pd

from config import ROOT, HTML_PATH
import macro_algo as ma

OUT = os.path.join(ROOT, "HT_Trading_System_data", "macro.js")


def _score_at(series_vals, h, idx):
    """在索引 idx 处（含）计算金融条件技术分（用于历史序列）。"""
    if idx < h:
        return None
    sub = series_vals[:idx + 1]
    raw, imp = ma.series_score(sub, h)
    return imp


def build_score_history(data, xlsx_path):
    """用持仓历史日期为轴，滚动计算各周期综合分历史序列（最近180点）。"""
    pos = data.get("position")
    if not pos or not pos.get("history"):
        return {p: [] for p in ma.PERIOD_H}
    dates = [h["date"] for h in pos["history"]]
    if not dates:
        return {p: [] for p in ma.PERIOD_H}

    # 预加载各指标序列
    rate_df = pd.read_excel(xlsx_path, sheet_name="美国利率数据", header=None)
    real_df = pd.read_excel(xlsx_path, sheet_name="中美实体经济", header=None)
    eu_df = pd.read_excel(xlsx_path, sheet_name="日欧经济", header=None)
    mm = {}
    mm.update(ma.read_block(rate_df, 1, 4))
    mm.update(ma.read_block(real_df, 1, 4))
    mm.update(ma.read_block(eu_df, 1, 4))

    def series_map(name):
        s = mm.get(name)
        if not s:
            return [], []
        return [d for d, _ in s], [v for _, v in s]

    # 预构建指标日期->值索引
    def make_lookup(name):
        s = mm.get(name)
        return dict(s) if s else {}

    market_lk = [(make_lookup(n), w) for n, _, w in ma.MARKET_INDICATORS]
    real_lk = [(make_lookup(n), country, sign, neutral, scale, w)
               for n, _, country, sign, neutral, scale, w in ma.REAL_INDICATORS]
    other_lk = [(make_lookup(n), country, sign, neutral, scale, w)
                for n, _, country, sign, neutral, scale, w in ma.OTHER_INDICATORS]

    # 每个日期取截至该日的最新值（简化：用该日或之前最后观察）
    def latest_upto(lk, d):
        # 为效率，构建排序键数组略复杂；此处用线性回溯（日期数*指标可控）
        best_date = None
        best_v = None
        for dd, vv in lk.items():
            if dd <= d and (best_date is None or dd > best_date):
                best_date, best_v = dd, vv
        return best_v

    # 收益率序列（用于实体step）
    def hist_upto(lk, d):
        arr = sorted((dd, vv) for dd, vv in lk.items() if dd <= d)
        return [v for _, v in arr]

    tail = dates[-180:]
    score_hist = {p: [] for p in ma.PERIOD_H}
    for d in tail:
        for p in ma.PERIOD_H:
            h = ma.PERIOD_H[p]
            # 金融
            mvals = []
            for lk, w in market_lk:
                arr = hist_upto(lk, d)
                if len(arr) > h:
                    _, imp = ma.series_score(arr, h)
                    if imp is not None:
                        mvals.append((imp, w))
            ms = ma.clamp(sum(v * w for v, w in mvals) / sum(w for _, w in mvals)) if mvals else None
            # 实体
            step, lw = ma.REAL_STEPS[p]
            rvals = []
            for lk, country, sign, neutral, scale, w in real_lk:
                arr = hist_upto(lk, d)
                _, sc, _ = ma.real_item_score([(str(i), v) for i, v in enumerate(arr)], neutral, scale, sign, step, lw)
                if sc is not None:
                    rvals.append((sc, w))
            rs = ma.clamp(sum(v * w for v, w in rvals) / sum(w for _, w in rvals)) if rvals else None
            # 持仓（用整体 position periods 的最新值近似，历史曲线主要靠金融/实体）
            ps = None
            if pos["periods"].get(p):
                ps = pos["periods"][p]["positionScore"]
            # 整体
            wm, wr, wp = ma.OVERALL_W[p]
            comps = [(ms, wm), (rs, wr), (ps, wp)]
            avail = [(v, w) for v, w in comps if v is not None]
            overall = ma.clamp(sum(v * w for v, w in avail) / sum(w for _, w in avail)) if avail else None
            score_hist[p].append({
                "date": d, "overall": ma.rnd(overall), "market": ma.rnd(ms),
                "realUS": None, "realChina": ma.rnd(rs), "realOther": None,
                "position": ma.rnd(ps),
            })
    return score_hist


def build_extra(data):
    """额外图表组（地区拆分、持仓等）。"""
    groups = []
    if data.get("position"):
        pos = data["position"]
        groups.append({
            "title": "有色持仓结构",
            "series": [{
                "name": "有色持仓 / 全部商品持仓",
                "unit": "%",
                "latestDate": pos.get("latestDate"),
                "history": [{"date": h["date"], "value": round(h["ratio"] * 100, 2)} for h in pos["history"]],
            }],
        })
    return {"groups": groups}


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    data = ma.build_macro_data()
    # 历史序列
    try:
        data["scoreHistory"] = build_score_history(data, ma.MACRO_XLSX)
    except Exception as e:
        print("历史序列计算跳过：", e)
        data["scoreHistory"] = {p: [] for p in ma.PERIOD_H}

    js = "window.MACRO_DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
    extra = build_extra(data)
    js += "\nwindow.MACRO_EXTRA_DATA=" + json.dumps(extra, ensure_ascii=False, separators=(",", ":")) + ";"
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(js)

    size = os.path.getsize(OUT) / 1024
    print(f"已生成 macro.js ({size:.0f}KB)")
    s = data["summary"]
    for p in ma.PERIOD_H:
        print(f"  {p}: 整体{s[p]['score']}({s[p]['direction']}) 金融{s[p]['marketScore']} 实体{s[p]['realScore']} 持仓{s[p]['positionScore']}")


if __name__ == "__main__":
    main()
