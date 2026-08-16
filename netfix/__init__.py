"""网络修复工具 NetRepair —— 包元信息。

ui.py 与 build.py 从本模块读取应用名称 / 版本 / 作者 / 许可等信息，
请勿删除本文件，否则程序无法启动、打包脚本无法运行。

Copyright (C) 2026 叶神鼬-丁 <2943629243@qq.com>

This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version. See <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

APP_NAME = "网络修复工具 NetRepair"
APP_VERSION = "1.1.0"
APP_AUTHOR = "叶神鼬-丁"
APP_EMAIL = "2943629243@qq.com"
APP_RELEASE_DATE = "2026-08-06"
APP_LICENSE = "GNU General Public License v3.0"
APP_LICENSE_SHORT = "GPLv3"
APP_COPYRIGHT = "Copyright (C) 2026 叶神鼬-丁"

__version__ = APP_VERSION
__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "APP_AUTHOR",
    "APP_EMAIL",
    "APP_RELEASE_DATE",
    "APP_LICENSE",
    "APP_LICENSE_SHORT",
    "APP_COPYRIGHT",
]
