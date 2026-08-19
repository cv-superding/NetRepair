"""网络修复工具 —— 程序入口。

行为：
  1. 直接以当前权限启动（不自动提权；实测 Win11 26200 上管理员清单 + PySide6
     会在 Qt 窗口初始化时原生崩溃，表现为双击无窗口）。
  2. 启动 PySide6 图形界面；非管理员时界面显示提示。
  3. 任何启动阶段的异常 / Qt 致命错误 / 原生崩溃（SEH 过滤器）都会：写日志到
     %TEMP%/NetRepair_diag.log，并弹出一个可见的 Win32 错误框（不依赖 Qt），
     便于「双击无窗口」时直接看到原因。

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


def _install_crash_filter() -> None:
    """安装 Windows 原生（SEH）异常过滤器。

    若 Qt / C 扩展在原生层崩溃（最常见就是 0xC0000005 访问冲突，例如显卡驱动 /
    Windows DWM / ANGLE 后端在你的 Windows 版本上不兼容），Python 的 try/except
    和 excepthook 都抓不到，进程会直接消失、什么都不显示。这里用 Win32 API 在
    崩溃的瞬间弹一个框 + 写日志，把「双击无窗口、连报错都没有」变成可见的提示。
    """
    try:
        kernel32 = ctypes.windll.kernel32
    except Exception:  # noqa: BLE001
        return

    # 过滤器回调：返回 1(EXCEPTION_EXECUTE_HANDLER) 表示已处理，进程随之终止
    _HandlerT = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)

    def _handler(exception_info_ptr: int, _unused) -> int:
        try:
            # EXCEPTION_POINTERS->ExceptionRecord(偏移0) 指向的 ExceptionCode(偏移0)
            code = ctypes.c_ulong.from_address(exception_info_ptr).value
        except Exception:  # noqa: BLE001
            code = 0xC0000005
        try:
            elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # noqa: BLE001
            elevated = False
        msg = (
            "NetRepair 发生原生层崩溃（异常码 0x%08X，当前%s权限）。\n\n"
            "这意味着图形子系统在你的系统上初始化失败，常见原因：\n"
            "· 显卡驱动 / Windows DWM / ANGLE 后端不兼容\n"
            "· 缺少 Visual C++ 运行库\n"
            "· 以管理员权限运行时 Qt 窗口初始化冲突\n\n"
            "请运行 dist\\run_diag.bat 获取详细诊断，\n"
            "并把生成的 diag_result.txt 与 %%TEMP%%\\NetRepair_diag.log 发给我。"
        ) % (code, "管理员" if elevated else "普通用户")
        try:
            ctypes.windll.user32.MessageBoxW(0, msg, "NetRepair 崩溃", 0x10)
        except Exception:  # noqa: BLE001
            pass
        try:
            with open(os.path.join(tempfile.gettempdir(), "NetRepair_crash.log"),
                      "a", encoding="utf-8") as fh:
                fh.write("CRASH exception 0x%08X elevated=%s\n" % (code, elevated))
        except Exception:  # noqa: BLE001
            pass
        return 1

    try:
        kernel32.SetUnhandledExceptionFilter(_HandlerT(_handler))
    except Exception:  # noqa: BLE001
        pass


# 模块一加载就记录，确认 Python/冻结引导是否到达本文件
_diag("=== boot: main.py 已加载, frozen=%s, py=%s ===" % (
    getattr(sys, "frozen", False), sys.version.split()[0]))
sys.excepthook = _global_except
_install_crash_filter()  # 原生崩溃也要可见



# ------------------------------------------------------------------ Qt 预检子进程
if "--_qtcheck" in sys.argv:
    # 仅在「子进程预检」时进入：创建最小 QApplication 验证图形环境可用。
    # 不创建/显示任何窗口（静默预检，避免每次启动都闪现一个测试窗口）。
    # 若 Qt 在原生层崩溃（0xC0000005），子进程会非正常退出，父进程（未加载 Qt）
    # 据此弹错误框，避免「双击无窗口、连报错都没有」的静默失败。
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    import sys as _sys
    _a = QApplication(_sys.argv)
    QTimer.singleShot(300, _a.quit)
    _sys.exit(_a.exec())


def _qt_smoke_check() -> bool:
    """子进程预检 Qt 能否正常初始化。

    子进程会重新加载一份冻结环境并创建一个最小 QApplication+QWidget。
    若 Qt 在原生层崩溃（segfault），子进程以非 0 退出；本进程（尚未加载 Qt）
    据此判定失败并弹错误框，把静默崩溃变成可见提示。
    """
    import subprocess
    _diag("qt_smoke: 启动子进程预检")
    try:
        env = os.environ.copy()
        env["NETREPAIR_SMOKE"] = "1"
        rc = subprocess.run(
            [sys.executable, "--_qtcheck"], env=env, timeout=15
        ).returncode
    except subprocess.TimeoutExpired:
        _diag("qt_smoke: 子进程超时（可能卡在事件循环或原生崩溃）")
        return False
    except Exception as exc:  # noqa: BLE001
        _diag("qt_smoke: 启动异常 " + repr(exc))
        return False
    _diag(f"qt_smoke: 子进程返回 rc={rc}")
    return rc == 0


# ------------------------------------------------------------------ 权限
def _ensure_admin() -> bool:
    """返回 True 表示应继续运行。

    注意：不再自动提权。实测（Windows 11 构建 26200）中，以管理员清单
    （--uac-admin）或 UAC 提权启动的 PySide6/QFluentWidgets 程序会在 Qt 窗口
    初始化时原生崩溃（0xC0000005），表现为「双击无窗口、连报错都没有」。
    因此改为普通权限直接启动；界面会显示「非管理员」提示，需要完整修复能力时
    可右键「以管理员身份运行」。
    """
    from netfix.sysutil import is_admin

    _diag("提权策略：直接启动（不自动提权）")
    if is_admin():
        _diag("当前已是管理员权限")
    else:
        _diag("当前为普通权限，界面将显示非管理员提示")
    return True


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

    # Qt 原生层预检：默认不启用（进程自拉子进程易被安全软件误判，且多 ~2s 启动）。
    # 仅在显式设置 NETREPAIR_SMOKE=1 时运行，用于排查「Qt 核心初始化 vs 界面初始化」
    # 到底哪一步崩。日常启动依赖 SEH 崩溃过滤器 + 诊断日志兜底即可。
    if os.environ.get("NETREPAIR_SMOKE") == "1":
        if not _qt_smoke_check():
            _show_error(
                "NetRepair 启动失败",
                "Qt 图形环境预检未通过：子进程在创建 QApplication 时异常退出，\n"
                "很可能是显卡 / DWM / ANGLE 后端不兼容，或缺少运行库。\n\n"
                "请运行 dist\\run_diag.bat 获取详细诊断并反馈。",
            )
            return 1
        _diag("qt_smoke: 预检通过")

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
