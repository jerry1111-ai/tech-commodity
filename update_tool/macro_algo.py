# -*- coding: utf-8 -*-
"""HT 宏观评分 —— 严格实现 宏观SKILL.md。

读取 宏观数据.xlsx（同花顺iFinD导出），计算：
金融条件 / 中美实体经济 / 其他实体经济 / 持仓情绪 / 整体宏观情绪
输出一周、一个月、一季度三周期 + 指标明细 + 历史序列。
"""
import os
import math
import datetime as dt

import numpy as np
import pandas as pd

from config import ROOT

MACRO_XLSX = os.path.join(ROOT, "宏观数据.xlsx")


def clamp(x, lo=-100, hi=100):
    if x is None:
        return None
    try:
        if isinstance(x, float) and math.isnan(x):
            return None
    except Exception:
        pass
    return max(lo, min(hi, x))


def rnd(x):
    if x is None:
        return None
    return int(math.floor(x + 0.5)) if x >= 0 else int(math.ceil(x - 0.5))


def direction(score):
    if score is None:
        return "—"
    if score >= 35:
        return "偏多"
    if score >= 15:
        return "震荡偏多"
    if score >= -14:
        return "中性"
    if score >= -34:
        return "震荡偏空"
    return "偏空"


def _to_num(x):
    try:
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except Exception:
        return None


def _date_str(x):
    if isinstance(x, (dt.datetime, dt.date)):
        return x.strftime("%Y-%m-%d")
    s = str(x).strip()
    if len(s) >= 8 and s[:4].isdigit():
        return s[:10]
    return None


# ---------------- 通用读取：行表头 + 日期列 ----------------
def read_block(df, header_row, data_start_row, date_col=0):
    """返回 {指标名: [(date, value), ...] 升序}，跳过空列与重复的'指标名称'列。"""
    names = df.iloc[header_row].tolist()
    out = {}
    for ci, name in enumerate(names):
        if ci == date_col:
            continue
        if not isinstance(name, str) or not name.strip() or name.strip() == "指标名称":
            continue
        series = []
        for ri in range(data_start_row, len(df)):
            d = _date_str(df.iat[ri, date_col])
            if not d:
                continue
            v = _to_num(df.iat[ri, ci])
            if v is not None:
                series.append((d, v))
        if series:
            series.sort(key=lambda z: z[0])
            # 同日去重（保留最后一个）
            dedup = {}
            for d, v in series:
                dedup[d] = v
            out[name.strip()] = sorted(dedup.items(), key=lambda z: z[0])
    return out


# ---------------- 金融条件技术分 ----------------
PERIOD_H = {"一周": 5, "一个月": 21, "一季度": 63}


def series_score(values, h):
    """单序列技术分，返回 (raw_score 原始, impactScore 反向)。"""
    arr = [v for v in values if v is not None]
    if len(arr) < max(3, h + 1):
        return None, None
    latest = arr[-1]
    base = arr[-1 - h]
    if base == 0:
        return None, None
    ret = latest / base - 1
    short_n = min(max(5, h // 2), len(arr))
    long_n = min(max(20, h), len(arr))
    ma_short = sum(arr[-short_n:]) / short_n
    ma_long = sum(arr[-long_n:]) / long_n
    win = arr[-(h + 1):]
    rets = [win[i] / win[i - 1] - 1 for i in range(1, len(win)) if win[i - 1]]
    vol = math.sqrt(sum(r * r for r in rets) / len(rets)) if rets else 0.001
    vol = max(vol, 0.001)
    momentum = clamp(ret / (vol * math.sqrt(h)) * 18, -45, 45)
    ma_score = (18 if latest > ma_short else -18) + (17 if ma_short > ma_long else -17)
    win2 = arr[-h:]
    lo, hi = min(win2), max(win2)
    position = ((latest - lo) / (hi - lo) - 0.5) * 30 if hi != lo else 0
    raw = clamp(momentum + ma_score + position)
    return raw, -raw


# ---------------- 金融条件 ----------------
# (Excel指标名, 显示名, 权重)
MARKET_INDICATORS = [
    ("美国:美元指数", "美元指数", 0.25),
    ("美国:国债收益率:10年", "美国10年期国债收益率", 0.20),
    ("美国:国债收益率:2年", "美国2年期国债收益率", 0.10),
    ("美国:国债实际收益率曲线:10年", "美国10年实际利率", 0.15),
    ("美国:10年期盈亏平衡通胀率", "美国10年通胀预期", 0.15),
    ("美国:5年期盈亏平衡通胀率", "美国5年通胀预期", 0.15),
]

# ---------------- 实体经济 ----------------
REAL_INDICATORS = [
    ("美国:ISM:服务业PMI", "美国ISM服务业PMI", "美国", 1, 50, 8, 0.14),
    ("美国:供应管理协会(ISM):制造业PMI", "美国ISM制造业PMI", "美国", 1, 50, 8, 0.16),
    ("美国:失业率:季调", "美国失业率", "美国", -1, 4.5, 20, 0.12),
    ("克强指数", "克强指数", "中国", 1, 5, 8, 0.14),
    ("规模以上工业增加值:累计同比", "中国工业增加值累计同比", "中国", 1, 5, 8, 0.16),
    ("制造业PMI", "中国制造业PMI", "中国", 1, 50, 8, 0.16),
    ("非制造业PMI:服务业", "中国服务业PMI", "中国", 1, 50, 8, 0.12),
]
OTHER_INDICATORS = [
    ("欧元区21国:失业率:季调", "欧元区失业率", "其他", -1, 6.5, 20, 0.25),
    ("日本:失业率:季调", "日本失业率", "其他", -1, 2.5, 20, 0.25),
    ("日本:工业生产指数(IIP):生产:同比", "日本工业生产同比", "其他", 1, 0, 8, 0.25),
    ("欧元区19国:工业生产指数:同比", "欧元区工业生产同比", "其他", 1, 0, 8, 0.25),
]
REAL_STEPS = {"一周": (1, 0.75), "一个月": (1, 0.55), "一季度": (3, 0.50)}


def real_item_score(series, neutral, scale, sign, step, level_w):
    """返回 (raw_original, score) —— score 已含方向符号。"""
    arr = [v for _, v in series]
    if len(arr) < step + 1:
        return None, None, None
    latest = arr[-1]
    level = (latest - neutral) * scale
    change = (latest - arr[-1 - step]) * scale * 1.5
    raw = level * level_w + change * (1 - level_w)
    return raw, clamp(raw * sign), latest


# ---------------- 持仓 ----------------
def build_position(xlsx_path):
    """返回 periods{period:{absoluteScore,ratioScore,positionScore,direction}},
    history[{date,absolute,total,ratio}], latest 值。"""
    # 有色持仓
    dz = pd.read_excel(xlsx_path, sheet_name="有色持仓量", header=None)
    # 表头行=3(时间/沪锌加权...)，数据从行4
    dz_names = dz.iloc[3].tolist()
    dz_data = {}
    for ci in range(1, len(dz_names)):
        series = []
        for ri in range(4, len(dz)):
            d = _date_str(dz.iat[ri, 0])
            if not d:
                continue
            v = _to_num(dz.iat[ri, ci])
            if v is not None:
                series.append((d, v))
        if series:
            dz_data[ci] = dict(series)

    # 全部品种持仓：找含 ths_open_inter 的行（该表日期在第1列，第0列空）
    all_df = pd.read_excel(xlsx_path, sheet_name="全部品种持仓量", header=None)
    hdr = None
    date_col = 0
    for ri in range(min(12, len(all_df))):
        rowvals = [str(x) for x in all_df.iloc[ri].tolist()]
        idx = next((i for i, v in enumerate(rowvals) if "ths_open_inter" in v), None)
        if idx is not None:
            hdr = ri
            # 该行 ths_open_interest 所在列 = 指标起始列；日期列通常是其左侧的"时间"列，
            # 但在本表中日期实际在第 1 列（与 ths_open_interest 同列起算）
            date_col = idx
            break
    all_data = {}
    if hdr is not None:
        for ci in range(date_col + 1, all_df.shape[1]):
            series = []
            for ri in range(hdr + 2, len(all_df)):
                d = _date_str(all_df.iat[ri, date_col])
                if not d:
                    continue
                v = _to_num(all_df.iat[ri, ci])
                if v is not None:
                    series.append((d, v))
            if series:
                all_data[ci] = dict(series)

    # 日期交集
    dz_dates = set()
    for s in dz_data.values():
        dz_dates |= set(s.keys())
    all_dates = set()
    for s in all_data.values():
        all_dates |= set(s.keys())
    common = sorted(dz_dates & all_dates)

    history = []
    for d in common:
        dz_vals = [s[d] for s in dz_data.values() if d in s]
        all_vals = [s[d] for s in all_data.values() if d in s]
        if not dz_vals or not all_vals:
            continue
        absolute = sum(dz_vals)
        total = sum(all_vals)
        if total <= 0:
            continue
        history.append({"date": d, "absolute": absolute, "total": total, "ratio": absolute / total})

    if not history:
        return None

    abs_series = [h["absolute"] for h in history]
    ratio_series = [h["ratio"] for h in history]

    periods = {}
    for period, h in PERIOD_H.items():
        _, abs_score = series_score(abs_series, h)
        _, ratio_score = series_score(ratio_series, h)
        if abs_score is None and ratio_score is None:
            continue
        a = abs_score if abs_score is not None else 0
        r = ratio_score if ratio_score is not None else 0
        pos_score = clamp(a * 0.45 + r * 0.55)
        periods[period] = {
            "absoluteScore": rnd(a), "ratioScore": rnd(r),
            "positionScore": rnd(pos_score), "direction": direction(pos_score),
        }

    last = history[-1]
    ratio_pct = sum(1 for x in history if x["ratio"] <= last["ratio"]) / len(history) * 100
    abs_pct = sum(1 for x in history if x["absolute"] <= last["absolute"]) / len(history) * 100
    return {
        "periods": periods,
        "history": history[-500:],  # 控制体积
        "absolute": last["absolute"], "total": last["total"], "ratio": last["ratio"],
        "ratioPercentile": round(ratio_pct, 1), "absolutePercentile": round(abs_pct, 1),
        "latestDate": last["date"],
    }


# ---------------- 主计算 ----------------
OVERALL_W = {
    "一周": (0.55, 0.25, 0.20),
    "一个月": (0.45, 0.40, 0.15),
    "一季度": (0.35, 0.50, 0.15),
}


def build_macro_data(xlsx_path=None):
    xlsx_path = xlsx_path or MACRO_XLSX
    # 1. 美国利率（金融条件）
    rate_df = pd.read_excel(xlsx_path, sheet_name="美国利率数据", header=None)
    rate = read_block(rate_df, header_row=1, data_start_row=4)

    # 2. 中美实体经济
    real_df = pd.read_excel(xlsx_path, sheet_name="中美实体经济", header=None)
    real = read_block(real_df, header_row=1, data_start_row=4)

    # 3. 日欧经济（两块表，取后半块的实体指标）
    eu_df = pd.read_excel(xlsx_path, sheet_name="日欧经济", header=None)
    eu = read_block(eu_df, header_row=1, data_start_row=4)

    all_series = {}
    all_series.update(rate)
    all_series.update(real)
    all_series.update(eu)

    # ---------- 金融条件 ----------
    market_indicators = []
    market_periods = {p: [] for p in PERIOD_H}
    for xls_name, disp, w in MARKET_INDICATORS:
        if xls_name not in all_series:
            continue
        series = all_series[xls_name]
        vals = [v for _, v in series]
        periods = {}
        for p, h in PERIOD_H.items():
            raw, impact = series_score(vals, h)
            if raw is not None:
                periods[p] = {"score": rnd(raw), "impactScore": rnd(impact)}
                market_periods[p].append((impact, w))
        market_indicators.append({
            "name": disp,
            "latest": vals[-1] if vals else None,
            "latestDate": series[-1][0] if series else None,
            "history": [{"date": d, "value": v} for d, v in series[-500:]],
            "periods": periods,
            "weight": w,
            "kind": "market",
        })

    market_score = {}
    for p in PERIOD_H:
        items = market_periods[p]
        if items:
            tot_w = sum(w for _, w in items)
            market_score[p] = clamp(sum(imp * w for imp, w in items) / tot_w) if tot_w else None
        else:
            market_score[p] = None

    # ---------- 实体经济 ----------
    def build_real_group(defs):
        out_items = []
        per_period = {p: [] for p in PERIOD_H}
        for xls_name, disp, country, sign, neutral, scale, w in defs:
            if xls_name not in all_series:
                continue
            series = all_series[xls_name]
            vals = [v for _, v in series]
            periods = {}
            for p, (step, lw) in REAL_STEPS.items():
                raw, score, latest = real_item_score(series, neutral, scale, sign, step, lw)
                if score is not None:
                    periods[p] = {"score": rnd(score), "impactScore": rnd(score)}
                    per_period[p].append((score, w, country))
            out_items.append({
                "name": disp, "country": country,
                "latest": vals[-1] if vals else None,
                "latestDate": series[-1][0] if series else None,
                "history": [{"date": d, "value": v} for d, v in series[-500:]],
                "periods": periods, "weight": w, "kind": "real",
            })
        return out_items, per_period

    real_items, real_pp = build_real_group(REAL_INDICATORS)
    other_items, other_pp = build_real_group(OTHER_INDICATORS)

    def weighted(pp, country_filter=None):
        res = {}
        for p in PERIOD_H:
            items = [(s, w) for s, w, c in pp[p] if country_filter is None or c == country_filter]
            tot = sum(w for _, w in items)
            res[p] = clamp(sum(s * w for s, w in items) / tot) if tot else None
        return res

    real_all = weighted(real_pp)
    real_us = weighted(real_pp, "美国")
    real_cn = weighted(real_pp, "中国")
    real_other = weighted(other_pp)

    # ---------- 持仓 ----------
    position = build_position(xlsx_path)

    # ---------- 整体 ----------
    summary = {}
    for p in PERIOD_H:
        wm, wr, wp = OVERALL_W[p]
        ms = market_score.get(p)
        rs = real_all.get(p)
        ps = position["periods"].get(p, {}).get("positionScore") if position else None
        # 缺失项剔除，权重归一
        comps = [(ms, wm), (rs, wr), (ps, wp)]
        avail = [(v, w) for v, w in comps if v is not None]
        overall = clamp(sum(v * w for v, w in avail) / sum(w for _, w in avail)) if avail else None
        summary[p] = {
            "score": rnd(overall), "direction": direction(overall),
            "marketScore": rnd(ms), "realScore": rnd(rs),
            "usRealScore": rnd(real_us.get(p)), "chinaRealScore": rnd(real_cn.get(p)),
            "otherRealScore": rnd(real_other.get(p)), "positionScore": rnd(ps),
        }

    # ---------- 历史综合分序列 ----------
    score_history = {}
    for p in PERIOD_H:
        hist = []
        # 以持仓历史日期为轴，简化：仅用最新点做锚（历史序列复杂，先给锚点）
        if position and position.get("latestDate"):
            hist.append({
                "date": position["latestDate"],
                "overall": summary[p]["score"],
                "market": summary[p]["marketScore"],
                "realUS": summary[p]["usRealScore"],
                "realChina": summary[p]["chinaRealScore"],
                "realOther": summary[p]["otherRealScore"],
                "position": summary[p]["positionScore"],
            })
        score_history[p] = hist

    return {
        "source": "同花顺iFinD / 宏观数据.xlsx",
        "generatedAt": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "marketScore": {p: rnd(market_score.get(p)) for p in PERIOD_H},
        "realScore": {p: rnd(real_all.get(p)) for p in PERIOD_H},
        "indicators": market_indicators,
        "realIndicators": real_items + other_items,
        "position": position,
        "scoreHistory": score_history,
    }
