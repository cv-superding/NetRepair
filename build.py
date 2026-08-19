"""打包脚本：生成图标、版本信息并调用 PyInstaller 输出单文件 exe。

用法：
    python build.py            # 完整打包
    python build.py --icon     # 仅生成图标

Copyright (C) 2026 叶神鼬-丁 <2943629243@qq.com>

This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version. See <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
ICO_PATH = os.path.join(ASSETS, "app.ico")
VERSION_FILE = os.path.join(ASSETS, "version_info.txt")
# 必须用 ASCII 文件名！实测：PyInstaller onefile 在本机（Win11 26200）对中文
# 文件名有 bug——程序能启动到窗口构建阶段，然后静默退出（无任何报错记录）。
# 同一份二进制：NetRepair-win.exe 能开，改名「网络修复工具-改名测试.exe」就死。
# 窗口标题/关于页仍显示中文「网络修复工具」，仅磁盘文件名用英文。
EXE_NAME = "NetRepair"

# 注意：不要在此处设置 QT_QPA_PLATFORM=offscreen。
# 打包阶段不需要显示器，PyInstaller 仅做静态分析；若设了 offscreen，
# PySide6 的 PyInstaller hook 在收集 Qt 平台插件时可能被该环境变量干扰，
# 导致最终 exe 在真实 Windows 上缺少 qwindows 平台插件而静默无法启动。

sys.path.insert(0, ROOT)


# ------------------------------------------------------------------ 图标

def build_ico() -> str:
    """从 Midjourney 源图缩放生成多尺寸 ICO（与关于页图标同源）。"""
    from PIL import Image

    os.makedirs(ASSETS, exist_ok=True)

    src = Image.open(os.path.join(ASSETS, "app-icon-source.png")).convert("RGBA")

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images: dict[int, Image.Image] = {s: src.resize((s, s), Image.LANCZOS) for s in sizes}

    # 必须用最大尺寸(256)作基准图，其余尺寸以 append_images 提供
    images[256].save(
        ICO_PATH,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=[images[s] for s in sizes if s != 256],
    )

    # 校验实际写入的条目数
    with open(ICO_PATH, "rb") as fh:
        head = fh.read(6)
    count = struct.unpack("<HHH", head)[2]
    if count != len(sizes):
        raise RuntimeError(f"ICO 生成异常：期望 {len(sizes)} 个尺寸，实际 {count} 个")

    print(f"[icon] 已生成 {ICO_PATH}（{count} 个尺寸，{os.path.getsize(ICO_PATH)} 字节）")
    return ICO_PATH


# ------------------------------------------------------------------ 版本信息

def build_version_file() -> str:
    from netfix import (
        APP_AUTHOR,
        APP_COPYRIGHT,
        APP_EMAIL,
        APP_LICENSE_SHORT,
        APP_NAME,
        APP_VERSION,
    )

    parts = APP_VERSION.split(".")
    while len(parts) < 4:
        parts.append("0")
    nums = ", ".join(parts[:4])

    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({nums}), prodvers=({nums}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404B0', [
        StringStruct('CompanyName', '{APP_AUTHOR}'),
        StringStruct('FileDescription', '{APP_NAME} - Windows 网络一键诊断与修复'),
        StringStruct('FileVersion', '{APP_VERSION}'),
        StringStruct('InternalName', 'NetRepair'),
        StringStruct('LegalCopyright', '{APP_COPYRIGHT}. Licensed under {APP_LICENSE_SHORT}.'),
        StringStruct('OriginalFilename', '{EXE_NAME}.exe'),
        StringStruct('ProductName', '{APP_NAME}'),
        StringStruct('ProductVersion', '{APP_VERSION}'),
        StringStruct('Comments', '作者：{APP_AUTHOR}　联系：{APP_EMAIL}')])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    os.makedirs(ASSETS, exist_ok=True)
    with open(VERSION_FILE, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"[version] 已生成 {VERSION_FILE}")
    return VERSION_FILE


# ------------------------------------------------------------------ 打包

# 不再排除任何模块：
# 1) 排查已确认「双击无窗口」的元凶是中文 exe 文件名（PyInstaller onefile bug），
#    与 excludes 无关；
# 2) 排除 PySide6 模块虽有体积收益（67MB→49MB），但为 100% 兼容不再冒任何风险；
# 3) 启动慢的问题由 onedir 目录版解决（build.py --onedir），单文件版保留给分享用。
EXCLUDES: list[str] = []


def build_exe() -> None:
    ico = build_ico()
    ver = build_version_file()

    mode = "--onedir" if "--onedir" in sys.argv else "--onefile"
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        # "--clean",  # 已手动清理 build/，避免沙箱删除拦截
        mode,
        "--windowed",
        # 注意：不要加 --uac-admin！实测（Win11 26200）管理员清单 + windowed 下
        # PySide6 在 Qt 窗口初始化时原生崩溃（0xC0000005），表现为双击无窗口。
        # 提权改由程序内 is_admin 判断 + 界面提示，用户可右键以管理员身份运行。
        f"--name={EXE_NAME}",
        f"--icon={ico}",
        f"--version-file={ver}",
        f"--distpath={os.path.join(ROOT, 'dist')}",
        f"--workpath={os.path.join(ROOT, 'build')}",
        f"--specpath={os.path.join(ROOT, 'build')}",
        "--hidden-import=PySide6.QtSvg",
        "--hidden-import=PySide6.QtSvgWidgets",
    ]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    args.append(os.path.join(ROOT, "main.py"))

    print("[build] " + " ".join(args[:8]) + " …")
    rc = subprocess.call(args, cwd=ROOT)
    if rc != 0:
        print(f"[build] 打包失败，返回码 {rc}")
        sys.exit(rc)

    exe = os.path.join(ROOT, "dist", f"{EXE_NAME}.exe")
    if os.path.isfile(exe):
        size = os.path.getsize(exe) / 1024 / 1024
        print(f"[build] 完成：{exe}（{size:.1f} MB）")
    else:
        print("[build] 未找到输出文件")
        sys.exit(1)


if __name__ == "__main__":
    if "--icon" in sys.argv:
        build_ico()
        build_version_file()
    else:
        build_exe()
