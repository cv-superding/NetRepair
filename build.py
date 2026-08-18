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
EXE_NAME = "网络修复工具"

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

EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtPrintSupport", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtWebSockets", "PySide6.QtWebChannel",
    "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech", "PySide6.QtStateMachine", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtHttpServer",
    "tkinter", "unittest", "pydoc", "doctest", "test", "email", "http", "xmlrpc",
    "pdb", "sqlite3", "numpy", "PIL", "setuptools", "pkg_resources",
]


def build_exe() -> None:
    ico = build_ico()
    ver = build_version_file()

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        # "--clean",  # 已手动清理 build/，避免沙箱删除拦截
        "--onefile",
        "--windowed",
        "--uac-admin",
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
