# -*- coding: utf-8 -*-
"""每日选股流水线：全行业选股 → 同步申万有色选股（保证两页口径一致）。

由计划任务 HT_StockAllScreen 每日 17:30 调用。
用法：
    python run_stock_all.py            # 正常（增量拉取）
    python run_stock_all.py --cached   # 只读缓存重算（不拉网络，用于口径调整后快速重算）
"""
import subprocess
import sys
import os
from datetime import datetime

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))


def run(script, *args):
    cmd = [sys.executable, os.path.join(TOOL_DIR, script)] + list(args)
    print(f"[{datetime.now():%H:%M:%S}] 执行 {script} {' '.join(args)}", flush=True)
    return subprocess.call(cmd, cwd=TOOL_DIR)


def main():
    args = [a for a in sys.argv[1:] if a == "--cached"]
    rc1 = run("build_stock_all.py", *args)
    print(f"[{datetime.now():%H:%M:%S}] 全行业选股返回码 {rc1}", flush=True)
    rc4 = run("enrich_bars.py")
    print(f"[{datetime.now():%H:%M:%S}] 长历史日K返回码 {rc4}", flush=True)
    rc3 = run("build_stock_all_30m.py")
    print(f"[{datetime.now():%H:%M:%S}] 个股30分钟返回码 {rc3}", flush=True)
    rc5 = run("build_fundamentals.py")
    print(f"[{datetime.now():%H:%M:%S}] 基本面返回码 {rc5}", flush=True)
    rc2 = run("sync_sw_screen.py")
    print(f"[{datetime.now():%H:%M:%S}] 有色选股同步返回码 {rc2}", flush=True)
    if rc1 != 0 or rc2 != 0:
        sys.exit(1)
    print(f"[{datetime.now():%H:%M:%S}] 选股流水线完成", flush=True)


if __name__ == "__main__":
    main()
