# -*- coding: utf-8 -*-
"""数据源映射与全局配置。"""

# 项目根目录
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML_PATH = os.path.join(ROOT, "HT_Trading_System.html")
TOOL_DIR = os.path.join(ROOT, "update_tool")
DATA_DIR = os.path.join(TOOL_DIR, "data")
DATA_MIN30_DIR = os.path.join(TOOL_DIR, "data_min30")
LOG_DIR = os.path.join(TOOL_DIR, "logs")
EXCEL_PATH = os.path.join(ROOT, "HT交易系统_数据底稿.xlsx")

# 历史起始日（按页面口径 2015 年至今，实际以接口返回为准）
HIST_START = "20150101"

# 海外指数代码映射：页面 code -> akshare(sina) symbol
OVERSEA_MAP = {
    "IXIC": ".IXIC",   # 纳斯达克综合
    "SPX": ".INX",     # 标普500
    "DJI": ".DJI",     # 道琼斯工业
    "SOX": ".SOX",     # 费城半导体
}

# 数据源类型标识
SRC_FUT = "promax:fut_daily"
SRC_SW = "promax:sw_daily"
SRC_CSI = "promax:index_daily"
SRC_YAHOO_PREFIX = "yahoo:"
