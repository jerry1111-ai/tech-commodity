# -*- coding: utf-8 -*-
"""从 all_screen.js 的"有色金属"行业结果，同步生成申万有色选股页数据。

目的：让"申万有色选股"与"全行业选股-有色金属"完全一致（同一口径、同一排名），
避免两处因缓存长度/数据源差异导致排名不同。
"""
import os
import re
import json

from config import ROOT

DATA = os.path.join(ROOT, "HT_Trading_System_data")
SW_DIR = os.path.join(DATA, "sw_nonferrous")
ALL_SCREEN = os.path.join(DATA, "all_screen.js")
ALL_BARS = os.path.join(DATA, "all_bars", "801050.js")


def load_js_var(path, var):
    """从 window.X=...; 文件里取出 JSON。"""
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    m = re.search(re.escape(var) + r"=(.*);\s*$", txt, re.S)
    if not m:
        raise RuntimeError(f"{path} 中未找到 {var}")
    return json.loads(m.group(1))


def main():
    if not os.path.exists(ALL_SCREEN):
        raise RuntimeError("缺少 all_screen.js，请先运行 build_stock_all.py")
    screen_all = load_js_var(ALL_SCREEN, "window.HT_ALL_SCREEN")
    ind = next((x for x in screen_all["industries"] if x["name"] == "有色金属"), None)
    if not ind:
        raise RuntimeError("all_screen.js 中没有有色金属行业")

    # 读取该行业前20的K线（HT_ALL_BARS["801050"] = {code: [[date,o,h,l,c,v],...]}）
    bars_map = {}
    if os.path.exists(ALL_BARS):
        bars_map = load_js_var(ALL_BARS, 'window.HT_ALL_BARS["801050"]')

    os.makedirs(SW_DIR, exist_ok=True)
    items = []
    for x in ind["items"]:
        code = x["code"]
        bars = bars_map.get(code, [])
        # 生成个股分片（页面用 window.HT_STOCK_BARS[code]）
        js = (f'window.HT_STOCK_BARS=window.HT_STOCK_BARS||{{}};'
              f'window.HT_STOCK_BARS[{json.dumps(code)}]='
              + json.dumps(bars, ensure_ascii=False, separators=(",", ":")) + ";")
        with open(os.path.join(SW_DIR, f"{code}.js"), "w", encoding="utf-8") as f:
            f.write(js)
        items.append({
            "rank": x["rank"], "code": code, "name": x["name"],
            "dailyScore": x["dailyScore"], "weeklyScore": x["weeklyScore"],
            "rankScore": x["rankScore"], "justStarted": x["justStarted"],
            "strictMatch": x["strictMatch"], "reason": x["reason"],
            "close": x["close"], "lastDate": x["lastDate"],
            "dataFile": f"HT_Trading_System_data/sw_nonferrous/{code}.js",
            "substitute": x.get("substitute", False),
        })

    out = {
        "constituents": ind["total"],
        "analyzed": ind["analyzed"],
        "strictMatches": ind["strict"],
        "insufficient": ind["total"] - ind["analyzed"],
        "failed": 0,
        "generatedAt": screen_all["generatedAt"],
        "items": items,
    }
    with open(os.path.join(SW_DIR, "screen.js"), "w", encoding="utf-8") as f:
        f.write("window.HT_SW_SCREEN=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";")

    print(f"已同步申万有色选股：成分{out['constituents']} 分析{out['analyzed']} 严格{out['strictMatches']}")
    print("前3：" + "、".join(f"{i['name']}({i['rankScore']})" for i in items[:3]))


if __name__ == "__main__":
    main()
