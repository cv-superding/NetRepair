"""底层系统工具：命令执行、权限、日志、备份目录。

设计要点：
- 所有子进程均使用 CREATE_NO_WINDOW，避免打包成 GUI exe 后闪黑框。
- 中文 Windows 下 netsh/ipconfig 输出为 OEM 代码页（cp936），需要多编码回退解码。
- PowerShell 调用统一强制 UTF-8 输出，避免解析中文时乱码。

Copyright (C) 2026 叶神鼬-丁 <2943629243@qq.com>

This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version. See <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

import ctypes
import datetime as _dt
import os
import subprocess
import sys
import threading

CREATE_NO_WINDOW = 0x08000000

# ---------------------------------------------------------------- 路径

def _base_data_dir() -> str:
    root = os.environ.get("ProgramData") or os.environ.get("ALLUSERSPROFILE") or os.path.expanduser("~")
    return os.path.join(root, "NetRepairTool")


DATA_DIR = _base_data_dir()
LOG_DIR = os.path.join(DATA_DIR, "logs")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")


def ensure_dirs() -> None:
    for d in (DATA_DIR, LOG_DIR, BACKUP_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass


def hosts_path() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.join(root, "System32", "drivers", "etc", "hosts")


# ---------------------------------------------------------------- 权限

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """以管理员身份重新启动自身。成功返回 True（调用方应立刻退出）。"""
    try:
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, ""
        else:
            exe = sys.executable
            params = " ".join(f'"{a}"' for a in sys.argv)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return int(rc) > 32
    except Exception:
        return False


# ---------------------------------------------------------------- 解码

_DECODE_ORDER = ("oem", "mbcs", "gbk", "utf-8")


def decode_output(raw: bytes) -> str:
    if not raw:
        return ""
    for enc in _DECODE_ORDER:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- 命令执行

class CmdResult:
    __slots__ = ("cmd", "code", "output", "timeout")

    def __init__(self, cmd: str, code: int, output: str, timeout: bool = False):
        self.cmd = cmd
        self.code = code
        self.output = (output or "").strip()
        self.timeout = timeout

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timeout

    def first_line(self, limit: int = 160) -> str:
        for line in self.output.splitlines():
            line = line.strip()
            if line:
                return line[:limit]
        return ""


def run_cmd(args, timeout: int = 90) -> CmdResult:
    """执行外部命令（args 为列表）。"""
    shown = " ".join(args) if isinstance(args, (list, tuple)) else str(args)
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            shell=False,
        )
        return CmdResult(shown, proc.returncode, decode_output(proc.stdout))
    except subprocess.TimeoutExpired:
        return CmdResult(shown, -1, f"命令执行超时（>{timeout}s）", timeout=True)
    except FileNotFoundError:
        return CmdResult(shown, -2, "找不到该命令，系统可能缺少对应组件")
    except Exception as exc:  # noqa: BLE001
        return CmdResult(shown, -3, f"执行异常：{exc}")


def run_shell(command: str, timeout: int = 90) -> CmdResult:
    """通过 cmd /c 执行（需要通配符等 shell 语义时使用，例如 arp -d *）。"""
    return run_cmd(["cmd", "/c", command], timeout=timeout)


_PS_PREFIX = (
    "$ErrorActionPreference='SilentlyContinue';"
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
    "$ProgressPreference='SilentlyContinue';"
)


def run_ps(script: str, timeout: int = 120) -> CmdResult:
    """执行 PowerShell 片段，输出强制 UTF-8。"""
    args = [
        "powershell", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-Command", _PS_PREFIX + script,
    ]
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            shell=False,
        )
        try:
            out = proc.stdout.decode("utf-8")
        except UnicodeDecodeError:
            out = decode_output(proc.stdout)
        return CmdResult("powershell: " + script[:80], proc.returncode, out)
    except subprocess.TimeoutExpired:
        return CmdResult("powershell", -1, f"PowerShell 执行超时（>{timeout}s）", timeout=True)
    except Exception as exc:  # noqa: BLE001
        return CmdResult("powershell", -3, f"PowerShell 执行异常：{exc}")


# ---------------------------------------------------------------- 日志

class Logger:
    """线程安全的文件 + 内存日志。"""

    def __init__(self) -> None:
        ensure_dirs()
        self._lock = threading.Lock()
        stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.path = os.path.join(LOG_DIR, f"repair_{stamp}.log")
        self.lines: list[str] = []
        self._sinks: list = []
        self.write(f"===== 网络修复工具 日志开始 {stamp} =====", "INFO")

    def add_sink(self, fn) -> None:
        self._sinks.append(fn)

    def write(self, message: str, level: str = "INFO") -> str:
        ts = _dt.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {message}"
        with self._lock:
            self.lines.append(line)
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass
        for fn in list(self._sinks):
            try:
                fn(line, level)
            except Exception:  # noqa: BLE001
                pass
        return line

    def info(self, msg: str) -> None:
        self.write(msg, "INFO")

    def ok(self, msg: str) -> None:
        self.write(msg, "OK")

    def warn(self, msg: str) -> None:
        self.write(msg, "WARN")

    def error(self, msg: str) -> None:
        self.write(msg, "ERROR")

    def text(self) -> str:
        with self._lock:
            return "\n".join(self.lines)


LOGGER = Logger()


def open_in_explorer(path: str) -> None:
    try:
        if os.path.isdir(path):
            os.startfile(path)  # noqa: S606
        else:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)],
                             creationflags=CREATE_NO_WINDOW)
    except Exception:  # noqa: BLE001
        pass
