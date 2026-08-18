"""自动截图脚本：为 README 生成 5 张界面截图。

用法：
    venv\\Scripts\\python.exe screenshot.py

输出：
    shots/fluent-about.png
    shots/fluent-repair.png
    shots/fluent-diagnose.png
    shots/fluent-backup.png
    shots/fluent-accent-blue.png（主题色切换页）
"""
from __future__ import annotations

import os
import sys

# ---- 路径设置 ----
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# 跳过管理员提权，截图不需要
sys.argv.append("--no-elevate")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setThemeColor

from netfix.ui import MainWindow

SHOTS_DIR = os.path.join(ROOT, "shots")
os.makedirs(SHOTS_DIR, exist_ok=True)

# 截图配置：(文件名, routeKey, 说明)
SHOTS = [
    ("fluent-repair.png",   "repairInterface",   "一键修复（首页）"),
    ("fluent-diagnose.png", "diagnoseInterface", "网络诊断"),
    ("fluent-backup.png",   "backupInterface",   "备份还原"),
    ("fluent-about.png",    "aboutInterface",    "关于"),
]


def setup_chinese_font(app: QApplication) -> None:
    """强制使用系统中文字体，解决 offscreen/沙箱中文渲染为方框的问题。"""
    # 优先级列表：Windows 常见中文字体
    fallbacks = [
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "SimHei",
        "PingFang SC",
        "Noto Sans CJK SC",
        "WenQuanYi Micro Hei",
    ]

    # 尝试从系统字体库查找第一个可用的中文字体
    families = QFontDatabase.families()
    chosen = None
    for font_name in fallbacks:
        if font_name in families:
            chosen = font_name
            break

    if chosen:
        font = QFont(chosen, 9)
        app.setFont(font)
        print(f"Font set: {chosen}")
    else:
        print(f"WARNING: No Chinese font found. Available sample: {families[:10]}")
        # 退而求其次：用默认字体但设大一点
        font = app.font()
        font.setFamilies(["Microsoft YaHei UI", "Sans Serif"])
        app.setFont(font)


def grab_window(window: MainWindow, path: str) -> None:
    window.repaint()
    QApplication.processEvents()

    pixmap = window.grab()
    full_path = os.path.join(SHOTS_DIR, path)
    pixmap.save(full_path, "PNG")
    size_kb = os.path.getsize(full_path) / 1024
    print(f"  OK {path} ({pixmap.width()}x{pixmap.height()}, {size_kb:.0f} KB)")


def main() -> int:
    app = QApplication(sys.argv)
    setup_chinese_font(app)

    window = MainWindow()
    window.resize(1080, 760)
    window.show()
    QApplication.processEvents()

    for _ in range(30):
        QApplication.processEvents()

    print("Screenshot start...\n")

    nav = window.navigationInterface

    for filename, route_key, desc in SHOTS:
        nav.setCurrentItem(route_key)
        QApplication.processEvents()
        for _ in range(15):
            QApplication.processEvents()

        grab_window(window, filename)
        print(f"  -> {desc}\n")

    # === 第 5 张：蓝色主题色 + 修复页 ===
    print("Switching to BLUE theme...")
    setThemeColor(QColor("#0094BC"))
    QApplication.processEvents()
    for _ in range(20):
        QApplication.processEvents()

    nav.setCurrentItem("repairInterface")
    QApplication.processEvents()
    for _ in range(15):
        QApplication.processEvents()

    grab_window(window, "fluent-accent-blue.png")
    print("  -> Theme color (BLUE) + Repair page\n")

    window.close()
    print("All done! Screenshots saved to shots/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
