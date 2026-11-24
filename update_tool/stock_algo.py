# -*- coding: utf-8 -*-
"""HT 申万有色选股 —— 严格实现 股票SKILL.md (ht-sw-nonferrous-screening)。"""
import math
import datetime as dt

import numpy as np

from score_algo import ema, _sign


# 评分统一使用最近 400 根日K（覆盖日线MA60、 周线30周绰绰有余），
# 保证不同脚本/不同缓存长度下口径一致，避免同一股票在两处排名不同。
SCORE_LOOKBACK = 400


def rnd_int(x):
    if x is None:
        return None
    return int(math.floor(x + 0.5)) if x >= 0 else int(math.ceil(x - 0.5))


def rnd1(x):
    return None if x is None else round(float(x), 1)


# ---------------- 周K聚合（ISO周） ----------------
def to_weekly(bars):
    """bars: [{date,open,high,low,close,volume}] 日K升序 -> 周K列表。"""
    weeks = {}
    order = []
    for b in bars:
        try:
            d = dt.date.fromisoformat(b["date"])
        except Exception:
            continue
        iso = d.isocalendar()
        key = (iso[0], iso[1])
        if key not in weeks:
            weeks[key] = {
                "date": b["date"], "open": b["open"], "high": b["high"],
                "low": b["low"], "close": b["close"], "volume": b.get("volume") or 0,
            }
            order.append(key)
        else:
            w = weeks[key]
            w["high"] = max(w["high"], b["high"])
            w["low"] = min(w["low"], b["low"])
            w["close"] = b["close"]
            w["volume"] += (b.get("volume") or 0)
            w["date"] = b["date"]
    return [weeks[k] for k in order]


# ---------------- 日线趋势分 ----------------
def daily_score(bars):
    n = len(bars)
    if n < 121:  # 需要 close[-21] 与 MA60
        return None
    closes = [b["close"] for b in bars]
    C = closes[-1]
    ma20 = sum(closes[-20:]) / 20
    # MA20_prev：以倒数第6日为终点的20日均值 => closes[-25:-5]
    ma20_prev = sum(closes[-25:-5]) / 20
    ma60 = sum(closes[-60:]) / 60
    ret20 = C / closes[-21] - 1
    score = 0
    score += 35 if C > ma20 else -35
    score += 25 if ma20 > ma20_prev else -20
    score += 25 if C > ma60 else -25
    score += max(-15, min(15, ret20 * 180))
    return rnd_int(score)


# ---------------- 周线启动分 ----------------
def weekly_score(wbars):
    n = len(wbars)
    if n < 30:
        return None
    closes = [b["close"] for b in wbars]
    C = closes[-1]
    wma5 = sum(closes[-5:]) / 5
    wma5_prev = sum(closes[-7:-2]) / 5  # 以倒数第3周为终点 => 索引 -7..-3
    wma10 = sum(closes[-10:]) / 10
    # MACD
    dif = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
    dea = ema(dif, 9)
    hist = [dif[i] - dea[i] for i in range(n)]

    # 最近5周内：收盘由下向上站上当时10周均线
    cross_age = None
    for age in range(0, 5):
        i = n - 1 - age
        if i < 10 or i - 1 < 10:
            break
        ma10_now = sum(closes[i - 9:i + 1]) / 10
        ma10_prev = sum(closes[i - 10:i]) / 10
        if closes[i] > ma10_now and closes[i - 1] <= ma10_prev:
            cross_age = age
            break
    # 最近5周内：动能柱由非正转正
    momentum_age = None
    for age in range(0, 5):
        i = n - 1 - age
        if i - 1 < 0:
            break
        if hist[i] > 0 and hist[i - 1] <= 0:
            momentum_age = age
            break

    near = abs(C / wma10 - 1)

    score = 0
    score += 28 if C > wma10 else -35
    score += 24 if wma5 > wma5_prev else -20
    score += 22 if hist[-1] > 0 else -18
    if cross_age is not None:
        score += 28 - 5 * cross_age
    if momentum_age is not None:
        score += 20 - 4 * momentum_age
    if near < 0.08:
        score += 12

    # justStarted 条件
    c1 = C > wma10
    c2 = wma5 > wma5_prev
    c3a = cross_age is not None
    c3b = momentum_age is not None
    # 最近三周动能柱连续增强 且 距10周线<10%
    c3c = (n >= 3 and hist[-1] > hist[-2] > hist[-3]) and near < 0.10
    just_started = bool(c1 and c2 and (c3a or c3b or c3c))

    return {
        "weeklyScore": rnd_int(score),
        "justStarted": just_started,
        "crossAge": cross_age,
        "momentumAge": momentum_age,
        "near": near,
        "wma5": wma5, "wma10": wma10,
    }


def reason_text(wr):
    parts = []
    if wr["crossAge"] is not None:
        parts.append(f"{wr['crossAge']}周内站上10周线" if wr["crossAge"] > 0 else "本周站上10周线")
    if wr["momentumAge"] is not None:
        parts.append(f"{wr['momentumAge']}周内周动能转正" if wr["momentumAge"] > 0 else "本周周动能转正")
    if wr["near"] < 0.10 and wr["wma5"] > wr["wma10"]:
        pass
    if not parts:
        if wr["weeklyScore"] is not None and wr["weeklyScore"] > 0:
            parts.append("周线趋势改善")
    return "；".join(parts) if parts else "趋势改善"


# ---------------- 单股评分 ----------------
def score_stock(bars):
    if len(bars) < 121:
        return None
    # 统一回溯窗口，避免缓存长度差异导致评分不一致
    bars = bars[-SCORE_LOOKBACK:] if len(bars) > SCORE_LOOKBACK else bars
    ds = daily_score(bars)
    if ds is None:
        return None
    wbars = to_weekly(bars)
    if len(wbars) < 30:
        return None
    wr = weekly_score(wbars)
    if wr is None:
        return None
    ws = wr["weeklyScore"]
    rank_score = round(ds * 0.48 + ws * 0.52, 1)
    strict = bool(ds >= 35 and wr["justStarted"])
    return {
        "dailyScore": ds, "weeklyScore": ws, "rankScore": rank_score,
        "justStarted": wr["justStarted"], "strictMatch": strict,
        "reason": reason_text(wr),
        "close": bars[-1]["close"],
        "lastDate": bars[-1]["date"],
        "startDate": bars[0]["date"],
        "barCount": len(bars),
        "weeklyBars": wbars,
    }


# ---------------- 排名与补位 ----------------
def rank_top(scored, topn=20):
    """scored: list of dict(含 code/name/...score)。返回前 topn 及统计。"""
    valid = [x for x in scored if x.get("rankScore") is not None]
    strict = sorted([x for x in valid if x["strictMatch"]], key=lambda z: -z["rankScore"])
    chosen = []
    chosen_codes = set()
    for x in strict[:topn]:
        chosen.append((x, False))
        chosen_codes.add(x["code"])
    # 补位1：dailyScore>0
    if len(chosen) < topn:
        rest = sorted([x for x in valid if x["code"] not in chosen_codes and x["dailyScore"] > 0],
                      key=lambda z: -z["rankScore"])
        for x in rest:
            if len(chosen) >= topn:
                break
            chosen.append((x, True))
            chosen_codes.add(x["code"])
    # 补位2：全部剩余
    if len(chosen) < topn:
        rest = sorted([x for x in valid if x["code"] not in chosen_codes], key=lambda z: -z["rankScore"])
        for x in rest:
            if len(chosen) >= topn:
                break
            chosen.append((x, True))
            chosen_codes.add(x["code"])
    return chosen, len(strict)
