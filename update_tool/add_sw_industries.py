# -*- coding: utf-8 -*-
"""向 HTML 的 DB 中补齐申万 31 个一级行业指数（已存在的不动）。

新增条目的行情/评分字段留空，由后续 build_html.py 填充，K线由 build_bars.py 生成。
"""
import os
import re
import json
import shutil
import datetime as dt

from config import HTML_PATH, TOOL_DIR

# 申万 31 个一级行业：代码 -> 名称
SW_LEVEL1 = {
    "801010": "农林牧渔", "801030": "基础化工", "801040": "钢铁", "801050": "有色金属",
    "801080": "电子", "801110": "家用电器", "801120": "食品饮料", "801130": "纺织服饰",
    "801140": "轻工制造", "801150": "医药生物", "801160": "公用事业", "801170": "交通运输",
    "801180": "房地产", "801200": "商贸零售", "801210": "社会服务", "801230": "综合",
    "801710": "建筑材料", "801720": "建筑装饰", "801730": "电力设备", "801740": "国防军工",
    "801750": "计算机", "801760": "传媒", "801770": "通信", "801780": "银行",
    "801790": "非银金融", "801880": "汽车", "801890": "机械设备", "801950": "煤炭",
    "801960": "石油石化", "801970": "环保", "801980": "美容护理",
}

# 已有品种沿用原名（不覆盖），避免打乱用户习惯
EXISTING_ALIAS = {
    "801010": "申万农产品", "801030": "申万化工", "801730": "申万电新",
    "801890": "申万机械", "801110": "申万家电",
}


def new_item(code, name):
    safe = code
    return {
        "category": "A股行业指数",
        "name": name,
        "code": f"{code}.SI",
        "status": "ok",
        "error": None,
        "rowCount": 0,
        "start": None,
        "end": None,
        "close": None,
        "support": None,
        "resistance": None,
        "score": None,
        "source": "promax:sw_daily",
        "direction": None,
        "note": None,
        "periods": {},
        "volumeCount": 0,
        "volumeCoverage": 0.0,
        "dataFile": f"HT_Trading_System_data/{safe}_SI.js",
        "bars": [],
    }


def main():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"const DB=(\{.*?\});", html, re.S)
    if not m:
        raise RuntimeError("无法定位 DB")
    db = json.loads(m.group(1))

    existing = {it["code"] for it in db["items"]}
    added = []
    for code, fullname in SW_LEVEL1.items():
        csi = f"{code}.SI"
        if csi in existing:
            continue
        name = EXISTING_ALIAS.get(code, f"申万{fullname}")
        db["items"].append(new_item(code, name))
        added.append(f"{name}({code})")

    if not added:
        print("31个一级行业已齐全，无需新增")
        return

    db["generatedAt"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M 中国标准时间")
    new_json = json.dumps(db, ensure_ascii=False, separators=(",", ":"))
    new_html = html[:m.start(1)] + new_json + html[m.end(1):]

    # 写前校验
    json.loads(re.search(r"const DB=(\{.*?\});", new_html, re.S).group(1))

    shutil.copyfile(HTML_PATH, os.path.join(TOOL_DIR, "backup_before_addsw.html"))
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"新增 {len(added)} 个一级行业（现共 {len(db['items'])} 个品种）：")
    for a in added:
        print("  +", a)


if __name__ == "__main__":
    main()
