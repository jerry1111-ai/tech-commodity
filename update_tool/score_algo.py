# -*- coding: utf-8 -*-
"""HT 全品种技术评分 —— 严格实现 SKILL.md (ht-market-scoring) 规格。

输入：按日期升序的 OHLCV 序列（list[dict] 或 DataFrame）
输出：四个周期各自的 chan/tsai/dow/composite/direction，加总分、总方向、
      支撑/压力、防守位/结构位、跨周期结论、文字描述。
"""
import math


# ---------------- 基础工具 ----------------
def _sign(x):
    return 1 if x > 0 else (-1 if x < 0 else 0)


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def ema(values, n):
    """标准 EMA，alpha=2/(n+1)，首值作为种子。"""
    if not values:
        return []
    alpha = 2.0 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def _rnd_int(x):
    """四舍五入到整数（Python 银行家舍入需修正：远离零方向）。"""
    return int(math.floor(x + 0.5)) if x >= 0 else int(math.ceil(x - 0.5))


def _round2(x):
    return None if x is None else round(float(x), 2)


# ---------------- 分型（摆动点） ----------------
def find_swings(highs, lows, n):
    """左右各2根识别局部高低点，相邻同类保留更极端，保证 H/L 交替。
    返回 [(index, 'H'|'L', price), ...]"""
    raw = []
    for i in range(2, n - 2):
        h = highs[i]
        if (h >= highs[i-1] and h >= highs[i-2] and
                h >= highs[i+1] and h >= highs[i+2]):
            raw.append([i, "H", h])
        l = lows[i]
        if (l <= lows[i-1] and l <= lows[i-2] and
                l <= lows[i+1] and l <= lows[i+2]):
            raw.append([i, "L", l])
    # 按索引排序
    raw.sort(key=lambda x: x[0])
    # 合并相邻同类：连续 H 保留更高，连续 L 保留更低
    merged = []
    for it in raw:
        if merged and merged[-1][1] == it[1]:
            prev = merged[-1]
            if it[1] == "H":
                if it[2] > prev[2]:
                    merged[-1] = it
            else:
                if it[2] < prev[2]:
                    merged[-1] = it
        else:
            merged.append(it)
    return [(x[0], x[1], x[2]) for x in merged]


def swings_in_window(swings, n, w):
    """评分只用最近 max(30, 2w) 根内最后 8 个有效摆动点。"""
    span = max(30, 2 * w)
    lo_idx = n - span
    inw = [s for s in swings if s[0] >= lo_idx]
    return inw[-8:]


# ---------------- 单周期评分 ----------------
def score_period(bars, w_orig, label, swings_all=None):
    """bars: list of dict(date,open,high,low,close,volume)。返回该周期结果 dict。"""
    n = len(bars)
    if n < 3:
        return None
    w = min(w_orig, n - 2)
    if w < 2:
        return None

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    vols = [b.get("volume") or 0 for b in bars]

    c = closes[-1]

    # 均线长度（用实际 w）
    short_n = max(3, w // 4)
    med_n = max(5, w // 2)
    long_n = max(10, w)

    def ma(arr, k):
        k = min(k, len(arr))
        return sum(arr[-k:]) / k

    ma_s = ma(closes, short_n)
    ma_m = ma(closes, med_n)
    ma_l = ma(closes, long_n)

    # ATR：最近14根 high-low 均值
    m14 = min(14, n)
    atr = sum(highs[-m14+i] - lows[-m14+i] for i in range(m14)) / m14

    # 周期收益
    base_i = n - 1 - w
    ret = (closes[-1] / closes[base_i] - 1) if base_i >= 0 and closes[base_i] != 0 else 0.0

    # 价格位置
    win_low = min(lows[-w:])
    win_high = max(highs[-w:])
    denom = win_high - win_low
    if denom == 0:
        denom = 1
    position = (c - win_low) / denom

    # 波动标准化动量
    vol_unit = atr / c * math.sqrt(w) if c else 0
    denom_norm = max(vol_unit, 0.004)
    norm = _clip(ret / denom_norm if denom_norm else 0, -1, 1)

    # 摆动点（可复用预计算结果）
    if swings_all is None:
        swings_all = find_swings(highs, lows, n)
    sw = swings_in_window(swings_all, n, w)

    # ============ 缠论 ============
    chan = 0.0
    chan_parts = []
    last_dir = None
    if sw:
        last = sw[-1]
        last_dir = last[1]
        if last[1] == "L":
            chan += 22
        else:
            chan -= 22

    # 中枢：用"最近至少4个摆动点"（即取最后4个）构造相邻区间
    zone_pos_text = None
    zg = zd = None
    stable = False
    if len(sw) >= 4:
        pts = sw[-4:]
        intervals = []
        for k in range(len(pts) - 1):
            a, b = pts[k], pts[k + 1]
            intervals.append((min(a[2], b[2]), max(a[2], b[2])))
        if intervals:
            zg = max(iv[0] for iv in intervals)  # 各区间下沿的最大值
            zd = min(iv[1] for iv in intervals)  # 各区间上沿的最小值
            stable = zg <= zd
            if stable:
                if c > zd:
                    chan += 28
                    zone_pos_text = "运行于中枢上方"
                elif c < zg:
                    chan -= 28
                    zone_pos_text = "运行于中枢下方"
                else:
                    zone_pos_text = "仍在中枢内部"
            else:
                zone_pos_text = "近期无稳定中枢"
    else:
        zone_pos_text = "近期无稳定中枢"

    # MACD
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(n)]
    dea = ema(dif, 9)
    macd_bar = [2 * (dif[i] - dea[i]) for i in range(n)]
    cur_bar = macd_bar[-1]
    prev_bar = macd_bar[-5] if n >= 5 else macd_bar[0]
    macd_contrib = (_sign(cur_bar) + _sign(cur_bar - prev_bar)) * 12
    chan += macd_contrib
    macd_text = "MACD动能偏多" if cur_bar > 0 else "MACD动能偏空"

    # 动量与区间位置
    chan += _rnd_int(norm * 20)
    if position > 0.65:
        chan += 8
    elif position < 0.35:
        chan -= 8

    chan = _clip(_rnd_int(chan), -100, 100)

    # ============ 蔡森 ============
    tsai = (position - 0.5) * 80 + norm * 32
    breakout_up = breakout_down = False
    if n >= w + 1:
        prior_high = max(highs[n-1-w:n-1])
        prior_low = min(lows[n-1-w:n-1])
        if c > prior_high:
            tsai += 25
            breakout_up = True
        if c < prior_low:
            tsai -= 25
            breakout_down = True

    w_bottom = m_head = False
    # 最近两个低点 / 两个高点（来自全摆动点）
    swing_lows = [s for s in sw if s[1] == "L"]
    swing_highs = [s for s in sw if s[1] == "H"]
    if len(swing_lows) >= 2:
        l1, l2 = swing_lows[-2], swing_lows[-1]
        if abs(l1[2] - l2[2]) <= 2 * atr:
            seg = highs[l1[0]:l2[0]+1]
            if seg and c > max(seg):
                tsai += 22
                w_bottom = True
    if len(swing_highs) >= 2:
        h1, h2 = swing_highs[-2], swing_highs[-1]
        if abs(h1[2] - h2[2]) <= 2 * atr:
            seg = lows[h1[0]:h2[0]+1]
            if seg and c < min(seg):
                tsai -= 22
                m_head = True

    tsai = _clip(_rnd_int(tsai), -100, 100)

    # ============ 道氏 ============
    alignment = _sign(c - ma_s) + _sign(ma_s - ma_m) + _sign(ma_m - ma_l)
    dow = alignment * 16 + norm * 32

    swing_contrib = 0
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        sw_h = _sign(swing_highs[-1][2] - swing_highs[-2][2])
        sw_l = _sign(swing_lows[-1][2] - swing_lows[-2][2])
        swing_contrib = (sw_h + sw_l) * 14
        dow += swing_contrib

    # 量能确认
    vol_confirm = False
    win_vols = [v for v in vols[-w:] if v]
    if win_vols and n >= w + 3:
        recent3 = sum(vols[-3:]) / 3
        prior = vols[n-3-w:n-3]
        prior_avg = sum(v for v in prior if v) / len(prior) if prior else 0
        if prior_avg > 0 and recent3 > prior_avg:
            dow += _sign(ret) * 8
            vol_confirm = True

    dow = _clip(_rnd_int(dow), -100, 100)

    # ============ 综合 ============
    composite = _clip(_rnd_int(chan * 0.36 + tsai * 0.32 + dow * 0.32), -100, 100)
    direction = _direction(composite)

    # 防守位 / 结构位
    mode = "多" if "偏多" in direction else ("空" if "偏空" in direction else "等")
    defense = structure = None
    if mode == "多":
        defense = c - 1.2 * atr
        k = max(5, w // 3)
        structure = min(lows[-k:]) - 0.3 * atr
    elif mode == "空":
        defense = c + 1.2 * atr
        k = max(5, w // 3)
        structure = max(highs[-k:]) + 0.3 * atr

    # ============ 文字描述 ============
    chan_text = _chan_text(last_dir, zone_pos_text, macd_text)
    tsai_text = _tsai_text(position, breakout_up, breakout_down, w_bottom, m_head)
    dow_text = _dow_text(alignment, swing_contrib, vol_confirm)

    return {
        "label": label,
        "window": w,
        "chan_score": chan,
        "tsai_score": tsai,
        "dow_score": dow,
        "composite_score": composite,
        "direction": direction,
        "period_return": ret,
        "atr": atr,
        "chan_text": chan_text,
        "tsai_text": tsai_text,
        "dow_text": dow_text,
        "mode": mode,
        "defense": _round2(defense),
        "structure": _round2(structure),
    }


def _direction(score):
    if score >= 35:
        return "偏多"
    if score >= 15:
        return "震荡偏多"
    if score >= -14:
        return "中性"
    if score >= -34:
        return "震荡偏空"
    return "偏空"


def _chan_text(last_dir, zone_pos_text, macd_text):
    parts = []
    if last_dir == "L":
        parts.append("底分型后向上笔")
    elif last_dir == "H":
        parts.append("顶分型后向下笔")
    if zone_pos_text:
        parts.append(zone_pos_text)
    parts.append(macd_text)
    return "；".join(parts)


def _tsai_text(position, breakout_up, breakout_down, w_bottom, m_head):
    if breakout_up:
        pos = "突破区间上沿"
    elif breakout_down:
        pos = "跌破区间下沿"
    elif position > 0.6:
        pos = "位于整理区上半部"
    elif position < 0.4:
        pos = "位于整理区下半部"
    else:
        pos = "仍在整理区中部"
    parts = [pos]
    if w_bottom:
        parts.append("近似W底突破")
    if m_head:
        parts.append("近似M头跌破")
    return "；".join(parts)


def _dow_text(alignment, swing_contrib, vol_confirm):
    if alignment >= 2:
        ma_txt = "均线多头排列"
    elif alignment <= -2:
        ma_txt = "均线空头排列"
    else:
        ma_txt = "均线层级分歧"
    parts = [ma_txt]
    if swing_contrib > 0:
        parts.append("高低点同步抬升")
    elif swing_contrib < 0:
        parts.append("高低点同步下移")
    else:
        parts.append("高低点尚未共振")
    if vol_confirm:
        parts.append("量能确认")
    return "；".join(parts)


# ---------------- 全局支撑 / 压力 ----------------
def global_support_resistance(bars):
    n = len(bars)
    seg = bars[-120:] if n > 120 else bars
    highs = [b["high"] for b in seg]
    lows = [b["low"] for b in seg]
    c = bars[-1]["close"]
    # 下方最近低点：取 close 下方最接近的低点价
    below = [lo for lo in lows if lo < c]
    above = [hi for hi in highs if hi > c]
    support = max(below) if below else min(lows)
    resistance = min(above) if above else max(highs)
    return _round2(support), _round2(resistance)


# ---------------- 跨周期结论 ----------------
def cross_conclusion(periods):
    """periods: dict 四周期。返回 note 文本。"""
    if not periods:
        return ""
    p1 = periods.get("一周", {}).get("direction", "")
    p6 = periods.get("半年", {}).get("direction", "")
    all_dirs = [p.get("direction", "") for p in periods.values()]

    all_bull = all("偏多" in d for d in all_dirs)
    all_bear = all("偏空" in d for d in all_dirs)
    if all_bull:
        return "四个周期共同偏多，趋势一致性较强。"
    if all_bear:
        return "四个周期共同偏空，反弹仍受趋势压制。"
    if "偏多" in p1 and "偏空" in p6:
        return "短线反弹，但半年结构仍偏空，按修复行情处理。"
    if "偏空" in p1 and "偏多" in p6:
        return "短线回落，但半年结构仍偏多，关注支撑承接。"
    return "不同周期信号分化，等待方向共振。"


# ---------------- 品种级总分 ----------------
def score_symbol(bars):
    """对单个品种计算全部四周期 + 总分。返回 dict 或 {'status':'data_insufficient'}。"""
    n = len(bars)
    if n < 80:
        return {"status": "insufficient", "rowCount": n}

    windows = [("一周", 5), ("一个月", 20), ("一季度", 60), ("半年", 120)]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    swings_all = find_swings(highs, lows, n)
    periods = {}
    composites = []
    for label, w in windows:
        r = score_period(bars, w, label, swings_all=swings_all)
        if r is None:
            continue
        periods[label] = r
        composites.append(r["composite_score"])

    if not periods:
        return {"status": "insufficient", "rowCount": n}

    total = _clip(_rnd_int(sum(composites) / len(composites)), -100, 100)
    total_dir = _direction(total)
    support, resistance = global_support_resistance(bars)
    note = cross_conclusion(periods)
    return {
        "status": "ok",
        "periods": periods,
        "score": total,
        "direction": total_dir,
        "support": support,
        "resistance": resistance,
        "note": note,
        "rowCount": n,
    }
