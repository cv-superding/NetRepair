"""网络修复工具 —— 程序入口。

行为：
  1. 检测管理员权限，未提权时自动通过 UAC 重新启动自身（可用 --no-elevate 跳过）。
  2. 启动 PySide6 图形界面。

打包后的 exe 已内嵌 requireAdministrator 清单，双击即会弹出 UAC，
因此第 1 步主要服务于直接运行源码的场景。

Copyright (C) 2026 叶神鼬-丁 <2943629243@qq.com>

This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version. See <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

import os
import sys


def _ensure_admin() -> bool:
    """返回 True 表示应继续运行；False 表示已拉起提权进程，当前进程应退出。"""
    from netfix.sysutil import is_admin, relaunch_as_admin

    if is_admin() or "--no-elevate" in sys.argv:
        return True
    if os.environ.get("NETREPAIR_ELEVATED") == "1":
        return True  # 已尝试过提权但失败，避免无限循环
    os.environ["NETREPAIR_ELEVATED"] = "1"
    if relaunch_as_admin():
        return False
    return True  # 用户拒绝 UAC，仍以受限模式启动，界面会给出提示


def main() -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    if not _ensure_admin():
        return 0

    from netfix.sysutil import LOGGER, ensure_dirs, is_admin

    ensure_dirs()
    LOGGER.info(f"启动环境：{'管理员' if is_admin() else '普通用户'} | "
                f"Python {sys.version.split()[0]} | 冻结={getattr(sys, 'frozen', False)}")

    from netfix.ui import run_app

    return run_app()


if __name__ == "__main__":
    sys.exit(main())
