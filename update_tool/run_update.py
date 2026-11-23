# -*- coding: utf-8 -*-
"""一键更新：拉取增量数据 -> 生成 Excel 底稿。

定时自动化 / Windows 计划任务只需执行：
    python run_update.py

所有输出写入 logs/run_latest.log，便于无人值守排查。
"""
import os
import sys
import time
import socket
import subprocess
import traceback
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "logs", "run_latest.log")


def wait_for_network(timeout=90):
    """开机补更时等待网络就绪，避免刚登录时拉取失败。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection(("223.5.5.5", 53), timeout=3).close()
            return True
        except Exception:
            time.sleep(3)
    return False


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run(script, *args):
    path = os.path.join(BASE, script)
    cmd = [sys.executable, path, *args]
    log("执行: " + " ".join(cmd))
    r = subprocess.run(cmd, cwd=BASE)
    return r.returncode


def in_trading_window(now):
    """定时任务专用：交易日白天 08:50-16:10 或夜盘 20:50-23:30 才更新。"""
    if now.weekday() >= 5:  # 周六周日（夜盘周五晚已包含在周五）
        return False
    t = now.hour * 100 + now.minute
    return (850 <= t <= 1610) or (2050 <= t <= 2330)


def main():
    args = sys.argv[1:]
    scheduled = "--scheduled" in args
    onlogon = "--onlogon" in args
    args = [a for a in args if a not in ("--scheduled", "--onlogon")]

    t0 = datetime.now()
    tag = "（登录补更）" if onlogon else ("（定时）" if scheduled else "（手动）")
    log("=" * 50)
    log(f"更新开始 {t0:%Y-%m-%d %H:%M:%S}{tag}")

    # 登录补更：等网络就绪，且不受交易时段限制（目的就是补齐最新数据）
    if onlogon:
        if not wait_for_network():
            log("网络在90秒内未就绪，放弃本次补更。")
            sys.exit(1)
        log("网络已就绪，开始补更。")
    elif scheduled and not in_trading_window(t0):
        log("非交易时段，跳过本次更新。")
        return

    try:
        rc = run("fetch_data.py", *args)
        log(f"日K数据拉取返回码 {rc}")
        rc_m30 = run("fetch_min30.py")
        log(f"30分钟K线拉取返回码 {rc_m30}")
        rc3 = run("build_bars.py")
        log(f"K线分片生成返回码 {rc3}")
        rc30 = run("build_bars30.py")
        log(f"30分钟分片返回码 {rc30}")
        rc4 = run("build_html.py")
        log(f"HTML行情+评分同步返回码 {rc4}")
        rc2 = run("build_excel.py")
        log(f"Excel 生成返回码 {rc2}")
        rc_macro = run("build_macro.py")
        log(f"宏观评分返回码 {rc_macro}")
        rc_ext = run("build_external.py")
        log(f"外盘数据返回码 {rc_ext}")
        rc_stock = run("build_stock.py")
        log(f"有色选股返回码 {rc_stock}")
        if rc2 != 0:
            log("Excel 生成失败")
            sys.exit(1)
        t1 = datetime.now()
        log(f"更新完成，用时 {(t1-t0).total_seconds():.1f}s")
    except Exception:
        log("更新异常:\n" + traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
