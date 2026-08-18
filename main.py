"""网络修复工具 —— 程序入口。

行为：
  1. 检测管理员权限，未提权时自动通过 UAC 重新启动自身（可用 --no-elevate 跳过）。
  2. 启动 PySide6 图形界面。
  3. 任何启动阶段的异常 / Qt 致命错误都会：写日志到 %TEMP%/NetRepair_diag.log，
     并弹出一个可见的 Win32 错误框（不依赖 Qt），便于「双击无窗口」时直接看到原因。

Copyright (C) 2026 叶神鼬-丁 <2943629243@qq.com>

This program is free software: you can redistribute it/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version. See <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import traceback


# ------------------------------------------------------------------ 诊断
def _diag(msg: str) -> None:
    """把启动每一步写进 %TEMP%/NetRepair_diag.log，便于排查「双击无窗口」类问题。"""
    try:
        path = os.path.join(tempfile.gettempdir(), "NetRepair_diag.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except Exception:  # noqa: BLE001
        pass


def _show_error(title: str, text: str) -> None:
    """用 Win32 MessageBox 弹出错误（不依赖 Qt，Qt 崩溃时也能用）。"""
    try:
        ctypes.windll.user32.MessageBoxW(0, str(text)[:3000], str(title)[:100], 0x10)
    except Exception:  # noqa: BLE001
        pass


def _install_qt_handler() -> None:
    """把 Qt 自身的错误/警告（含平台插件缺失、Mica/DWM 失败）也写进探针日志并弹窗。"""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler

        _levels = {
            QtMsgType.QtDebugMsg: "Debug",
            QtMsgType.QtInfoMsg: "Info",
            QtMsgType.QtWarningMsg: "Warning",
            QtMsgType.QtCriticalMsg: "Critical",
            QtMsgType.QtFatalMsg: "Fatal",
        }

        def _handler(msg_type: QtMsgType, _ctx, msg: str) -> None:
            line = f"[Qt {_levels.get(msg_type, '?')}] {msg}"
            _diag(line)
            if msg_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                _show_error("NetRepair 启动错误 (Qt)", line)

        qInstallMessageHandler(_handler)
    except Exception:  # noqa: BLE001
        pass


def _global_except(exc_type, exc_value, exc_tb) -> None:
    """未捕获异常的全局处理：写日志 + 弹窗。"""
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _diag("UNCAUGHT: " + text)
    _show_error("NetRepair 启动失败", "未捕获异常：\n\n" + text)


# 模块一加载就记录，确认 Python/冻结引导是否到达本文件
_diag("=== boot: main.py 已加载, frozen=%s, py=%s ===" % (
    getattr(sys, "frozen", False), sys.version.split()[0]))
sys.excepthook = _global_except


# ------------------------------------------------------------------ 权限
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
    _install_qt_handler()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    if not _ensure_admin():
        _diag("已请求提权并退出当前进程")
        return 0
    _diag("提权检查通过，继续")

    from netfix.sysutil import LOGGER, ensure_dirs, is_admin

    ensure_dirs()
    LOGGER.info(f"启动环境：{'管理员' if is_admin() else '普通用户'} | "
                f"Python {sys.version.split()[0]} | 冻结={getattr(sys, 'frozen', False)}")
    _diag(f"环境：{'管理员' if is_admin() else '普通用户'} | 冻结={getattr(sys, 'frozen', False)}")

    from netfix.ui import run_app

    _diag("导入 netfix.ui 成功，准备 run_app()")
    try:
        rc = run_app()
        _diag(f"run_app() 正常返回，rc={rc}")
        return rc
    except Exception:  # noqa: BLE001
        _diag("run_app() 抛出异常：\n" + traceback.format_exc())
        _show_error("NetRepair 启动失败", "run_app() 异常：\n\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    sys.exit(main())
