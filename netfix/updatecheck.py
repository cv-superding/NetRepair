"""检查更新：查询 GitHub 最新 Release 并与本地版本做语义比较。

设计原则：
- 只用标准库（urllib / json），不引入任何第三方 HTTP 依赖；
- 纯逻辑、不依赖 Qt，便于单独测试；
- 任何网络 / 解析异常都静默返回 None，由调用方决定是否提示用户，
  绝不因为「检查更新」失败而打扰正在排障的用户。

Copyright (C) 2026 叶神鼬-丁 <2943629243@qq.com>
Licensed under the GNU General Public License v3.0.
"""

from __future__ import annotations

import json
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
        return {
            "tag": tag,
            "name": str(data.get("name") or tag),
            "body": str(data.get("body") or "").strip(),
            "url": str(data.get("html_url") or RELEASES_PAGE),
            "published_at": str(data.get("published_at") or ""),
        }
    except Exception:  # noqa: BLE001 —— 检查更新失败必须静默
        return None
