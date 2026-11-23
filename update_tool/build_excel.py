# -*- coding: utf-8 -*-
"""生成 Excel 底稿：总表 + 每品种历史日K分表。

总表字段来自 HTML 内嵌 DB（评分/信号/方向等保持不变），
"最新价/最新日期"用本地缓存的实际数据覆盖（即更新后的行情）。
"""
import os
import re
import json
import warnings
from datetime import datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

warnings.filterwarnings("ignore")

from config import HTML_PATH, DATA_DIR, DATA_MIN30_DIR, EXCEL_PATH, SRC_FUT

PERIODS = ["一周", "一个月", "一季度", "半年"]


def load_db():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"const DB=(\{.*?\});", html, re.S)
    return json.loads(m.group(1))


def data_path(code):
    safe = re.sub(r"[^0-9A-Za-z]", "_", code)
    return os.path.join(DATA_DIR, safe + ".csv")


def min30_path(code):
    safe = re.sub(r"[^0-9A-Za-z]", "_", code)
    return os.path.join(DATA_MIN30_DIR, safe + ".csv")


def load_min30(code):
    p = min30_path(code)
    if not os.path.exists(p):
        return None
    try:
        df = pd.read_csv(p, dtype={"datetime": str})
        return df if not df.empty else None
    except Exception:
        return None


def load_cache(code):
    p = data_path(code)
    if not os.path.exists(p):
        return None
    try:
        df = pd.read_csv(p, dtype={"date": str})
        return df if not df.empty else None
    except Exception:
        return None


def sheet_name(item, used):
    """Excel sheet 名 ≤31 字符且不含特殊符号，重名加序号。"""
    name = re.sub(r"[\\/*?:\[\]]", "", item["name"])[:31]
    base = name
    n = 1
    while name in used:
        suffix = f"~{n}"
        name = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(name)
    return name


# ---------- 样式 ----------
HDR_FILL = PatternFill("solid", fgColor="1F3864")
HDR_FONT = Font(color="FFFFFF", bold=True, size=10)
TITLE_FONT = Font(bold=True, size=14, color="1F3864")
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
POS_FONT = Font(color="C00000")   # 中国习惯：涨=红
NEG_FONT = Font(color="008000")   # 跌=绿
POS_FILL = PatternFill("solid", fgColor="FCE4E4")
NEG_FILL = PatternFill("solid", fgColor="E2F0D9")


def style_header(ws, row, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HDR_FILL
        cell.font = HDR_FONT
        cell.alignment = CENTER
        cell.border = BORDER


def build_summary(wb, db):
    ws = wb.active
    ws.title = "总表"
    headers = [
        "序号", "板块", "品种", "代码", "数据源",
        "最新价", "最新日期", "数据条数",
        "一周评分", "一个月评分", "一季度评分", "半年评分",
        "一周方向", "一个月方向", "一季度方向", "半年方向",
        "支撑位", "压力位", "综合提示",
    ]
    ws.append(headers)
    style_header(ws, 1, len(headers))

    items = db["items"]
    for idx, item in enumerate(items, 1):
        code = item["code"]
        df = load_cache(code)
        if df is not None and len(df):
            last = df.iloc[-1]
            latest_close = last["close"]
            latest_date = last["date"]
            nrows = len(df)
        else:
            latest_close = item.get("close")
            latest_date = item.get("end")
            nrows = item.get("rowCount", 0)

        per = item.get("periods", {}) or {}
        def sc(p):
            return (per.get(p) or {}).get("composite_score")
        def dr(p):
            return (per.get(p) or {}).get("direction")

        ws.append([
            idx, item.get("category"), item.get("name"), code, item.get("source"),
            latest_close, latest_date, nrows,
            sc("一周"), sc("一个月"), sc("一季度"), sc("半年"),
            dr("一周"), dr("一个月"), dr("一季度"), dr("半年"),
            item.get("support"), item.get("resistance"), item.get("note"),
        ])

    # 列宽
    widths = [6, 12, 14, 14, 20, 12, 12, 10, 10, 11, 11, 10,
              12, 13, 13, 10, 11, 11, 50]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # 评分着色（红涨绿跌）+ 边框
    score_cols = [9, 10, 11, 12]
    for r in range(2, ws.max_row + 1):
        for c in score_cols:
            cell = ws.cell(row=r, column=c)
            v = cell.value
            if isinstance(v, (int, float)):
                if v >= 15:
                    cell.font = POS_FONT
                    cell.fill = POS_FILL
                elif v <= -15:
                    cell.font = NEG_FONT
                    cell.fill = NEG_FILL
        for c in range(1, len(headers) + 1):
            ws.cell(row=r, column=c).border = BORDER
            if c not in (19,):
                ws.cell(row=r, column=c).alignment = CENTER

    ws.freeze_panes = "F2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws.max_row}"
    return ws


def build_detail(wb, db):
    used = set()
    detail_headers = ["日期", "开盘", "最高", "最低", "收盘", "成交量"]
    min30_hdr_fill = PatternFill("solid", fgColor="2E5A88")
    min30_title_font = Font(bold=True, size=11, color="1F3864")
    for item in db["items"]:
        df = load_cache(item["code"])
        if df is None or df.empty:
            continue
        name = sheet_name(item, used)
        ws = wb.create_sheet(name)
        ws.append(detail_headers)
        style_header(ws, 1, len(detail_headers))
        for _, row in df.iterrows():
            ws.append([
                row.get("date"), row.get("open"), row.get("high"),
                row.get("low"), row.get("close"), row.get("volume"),
            ])
        for i, w in enumerate([13, 12, 12, 12, 12, 16], 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:F{ws.max_row}"

        # 期货品种：在 H 列起追加 30 分钟 K 线区块（与日K并列，不覆盖）
        if item.get("source") == SRC_FUT:
            m30 = load_min30(item["code"])
            if m30 is not None and not m30.empty:
                # 分隔标题（H1）
                title = ws.cell(row=1, column=8, value="30分钟K线（新浪源·最近约4个月滚动）")
                title.font = min30_title_font
                # 表头（H2:N2）
                m30_headers = ["datetime", "open", "high", "low", "close", "volume", "hold"]
                for j, h in enumerate(m30_headers):
                    c = ws.cell(row=2, column=8 + j, value=h)
                    c.fill = min30_hdr_fill
                    c.font = HDR_FONT
                    c.alignment = CENTER
                    c.border = BORDER
                # 数据（H3 起）
                for ridx, (_, row) in enumerate(m30.iterrows(), start=3):
                    for j, h in enumerate(m30_headers):
                        ws.cell(row=ridx, column=8 + j, value=row.get(h))
                for j, w in enumerate([20, 11, 11, 11, 11, 15, 14]):
                    ws.column_dimensions[get_column_letter(8 + j)].width = w


def main():
    db = load_db()
    wb = Workbook()
    build_summary(wb, db)
    build_detail(wb, db)
    wb.save(EXCEL_PATH)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"已生成：{EXCEL_PATH}")
    print(f"工作表数：{len(wb.sheetnames)}（含总表），生成时间：{stamp}")


if __name__ == "__main__":
    main()
