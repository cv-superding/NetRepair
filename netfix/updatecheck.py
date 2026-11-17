"""检查更新：查询 GitHub 最新 Release、语义版本比较、应用内下载与替换。

设计原则：
- 只用标准库（urllib / json / subprocess），不引入任何第三方 HTTP 依赖；
- 纯逻辑、不依赖 Qt，便于单独测试；
- 任何网络 / 解析异常都静默返回 None，由调用方决定是否提示用户，
  绝不因为「检查更新」失败而打扰正在排障的用户。

实际应用内更新流程（由 UI 层编排）：
  1. fetch_latest_release() 拿到最新 release 及其 assets；
  2. find_asset() 挑出 .exe 的下载地址；
  3. download_file() 流式下载到临时目录（带进度回调）；
  4. write_update_script() 生成 PowerShell 替换脚本：等待当前进程退出 →
     备份旧 exe → 用新 exe 覆盖 → 重新启动；
  5. 启动脚本后退出当前进程，由脚本完成替换与重启。

Copyright (C) 2026 叶神鼬-丁 <2943629243@qq.com>
Licensed under the GNU General Public License v3.0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen

from . import APP_VERSION

LATEST_RELEASE_API = (
    "https://api.github.com/repos/cv-superding/NetRepair/releases/latest"
)
RELEASES_PAGE = "https://github.com/cv-superding/NetRepair/releases/latest"

#: 请求超时（秒）。检查更新在后台线程执行，短超时避免用户长时间无响应感。
TIMEOUT = 6


def version_tuple(v: str) -> tuple[int, ...]:
    """把版本号字符串规范化为可比较的整数元组。

    兼容 ``"v1.3.1"`` / ``"1.3.1-beta"`` / ``"1.3"`` 等写法：
    去掉 v 前缀与预发布/构建后缀，按 `.` 分段取数字，非数字段记为 0。
    """
    text = (v or "").strip().lstrip("vV")
    text = text.split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for seg in text.split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def has_new_version(latest: str, current: str = APP_VERSION) -> bool:
    """latest 是否新于 current。无法解析时保守返回 False，不误报。"""
    try:
        return version_tuple(latest) > version_tuple(current)
    except (TypeError, ValueError):
        return False


def fetch_latest_release(timeout: int = TIMEOUT) -> dict | None:
    """获取最新 Release 信息。

    返回字段：``tag``（如 ``v1.3.1``）、``name``、``body``（更新说明）、
    ``url``（浏览器打开地址）、``published_at``。
    任何失败（断网、超时、API 限流、字段缺失）一律返回 None。
    """
    try:
        req = Request(
            LATEST_RELEASE_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "NetRepair-UpdateCheck",
            },
        )
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8", "replace"))
        tag = str(data.get("tag_name") or "").strip()
        if not tag:
            return None
        assets = []
        for a in data.get("assets") or []:
            try:
                assets.append({
                    "name": str(a.get("name") or ""),
                    "size": int(a.get("size") or 0),
                    "url": str(a.get("browser_download_url") or ""),
                })
            except (TypeError, ValueError):  # noqa: PERF203
                continue
        return {
            "tag": tag,
            "name": str(data.get("name") or tag),
            "body": str(data.get("body") or "").strip(),
            "url": str(data.get("html_url") or RELEASES_PAGE),
            "published_at": str(data.get("published_at") or ""),
            "assets": assets,
        }
    except Exception:  # noqa: BLE001 —— 检查更新失败必须静默
        return None


def find_asset(release: dict, suffix: str = ".exe") -> dict | None:
    """从 release 的 assets 中挑出文件名以 suffix 结尾的可下载项。"""
    for asset in release.get("assets") or []:
        if asset.get("name", "").lower().endswith(suffix.lower()) and asset.get("url"):
            return asset
    return None


def is_frozen() -> bool:
    """当前是否运行在 PyInstaller 打包的 exe 中（而非源码 python main.py）。"""
    return bool(getattr(sys, "frozen", False))


def current_exe() -> str:
    """当前可执行文件路径。冻结态为 exe 自身，源码态为 python.exe。"""
    return os.path.abspath(sys.executable)


def download_file(url: str, dest: str, progress=None, timeout: int = 30,
                  chunk: int = 256 * 1024) -> str:
    """流式下载文件到 dest，返回 dest 路径。

    progress: 可选回调 ``f(downloaded_bytes, total_bytes)``，total 可能为 0（未知）。
    失败时抛出异常，由调用方处理（这个阶段需要让用户知道失败）。
    """
    req = Request(url, headers={"User-Agent": "NetRepair-UpdateCheck"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310
        total = 0
        try:
            total = int(resp.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        done = 0
        with open(dest, "wb") as fh:
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                fh.write(buf)
                done += len(buf)
                if progress:
                    try:  # noqa: SIM105
                        progress(done, total)
                    except Exception:  # noqa: BLE001
                        pass
    return dest


def write_update_script(exe_path: str, new_exe: str, script_path: str) -> str:
    """生成 PowerShell 替换脚本，返回脚本路径。

    脚本在**当前进程退出之后**执行：等待进程结束 → 备份旧 exe 为 .bak →
    用新 exe 覆盖 → 重新启动新 exe → 自删除。用 PowerShell 而非 bat，避免中文
    路径乱码。所有路径以单引号字面量写入并做单引号转义。

    exe_path: 正在运行的旧 exe 路径（将被替换）；
    new_exe:  已下载的新 exe 路径（临时目录）；
    script_path: 脚本输出路径（建议放系统临时目录）。
    """
    def ps(s: str) -> str:
        return s.replace("'", "''")

    script = f"""$ErrorActionPreference = 'Stop'
$target = '{ps(exe_path)}'
$source = '{ps(new_exe)}'
$oldPid = $args[0]
# 等待旧进程退出（最多 30 秒），确保 exe 文件不再被占用
for ($i = 0; $i -lt 60; $i++) {{
  $p = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
  if (-not $p) {{ break }}
  Start-Sleep -Milliseconds 500
}}
# 备份旧版本，失败则中止替换（宁可不更新也不损坏原程序）
$bak = "$target.bak"
try {{
  Copy-Item -LiteralPath $target -Destination $bak -Force -ErrorAction Stop
}} catch {{
  exit 1
}}
# 用新版本覆盖；失败则尝试从备份还原
try {{
  Copy-Item -LiteralPath $source -Destination $target -Force -ErrorAction Stop
}} catch {{
  Copy-Item -LiteralPath $bak -Destination $target -Force -ErrorAction SilentlyContinue
  exit 2
}}
# 启动新版本
try {{
  Start-Process -FilePath $target
}} catch {{
  exit 3
}}
# 清理临时下载
Remove-Item -LiteralPath $source -Force -ErrorAction SilentlyContinue
"""
    with open(script_path, "w", encoding="utf-8-sig") as fh:
        fh.write(script)
    return script_path


def launch_update_script(script_path: str, pid: int) -> None:
    """以分离进程启动替换脚本，传入当前进程 PID 供其等待退出。"""
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", script_path, str(pid)],
        creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NO_WINDOW
        close_fds=True,
    )


def temp_update_dir() -> str:
    """创建并返回用于存放下载文件与更新脚本的临时目录。"""
    path = os.path.join(tempfile.gettempdir(), "NetRepairUpdate")
    os.makedirs(path, exist_ok=True)
    return path
