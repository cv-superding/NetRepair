"""自动截图脚本：为 README 生成 5 张界面截图（v1.2.0）。

修复要点（相对旧版）：
  1. 调用 setTheme(Theme.LIGHT) —— 否则 FluentWindow 背景不填，grab() 会把
     透明区域也截下来（旧图左右大黑边的根因）。
  2. 切页前先关掉所有 InfoBar（含"当前不是管理员权限"提示条）。
  3. 切页后多跑 processEvents 并加一次单次定时器等待，确保页面真正渲染完成
     （旧版 about 截图实际上是修复页 = 导航没生效就 grab 了）。
  4. 显式 setThemeColor 选一个统一主题色（与 app 默认一致），最后一张切到
     蓝绿色作为"主题色切换"对照。

用法：
    venv\\Scripts\\python.exe screenshot.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# 跳过管理员提权检查（截图不需要）
sys.argv.append("--no-elevate")

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from qfluentwidgets import InfoBar, setTheme, setThemeColor, Theme

from netfix.ui import MainWindow

SHOTS_DIR = os.path.join(ROOT, "shots")
os.makedirs(SHOTS_DIR, exist_ok=True)

# 与 app 默认一致的主题色（_ACCENTS[0]）
DEFAULT_ACCENT = "#0094BC"

# 截图配置：(文件名, MainWindow 上的页面属性, 说明)
# 用 switchTo(页面对象) 导航，比 navigationInterface.setCurrentItem(routeKey)
# 稳定得多（旧版 routeKey 切换在沙箱里完全不生效，5 张都截到首页）。
SHOTS = [
    ("fluent-repair.png",   "repairPage",   "一键修复（首页）"),
    ("fluent-diagnose.png", "diagnosePage", "网络诊断"),
    ("fluent-backup.png",   "backupPage",   "备份还原"),
    ("fluent-about.png",    "aboutPage",    "关于"),
]


def setup_chinese_font(app: QApplication) -> None:
    fallbacks = [
        "Microsoft YaHei UI", "Microsoft YaHei", "SimHei",
        "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Micro Hei",
    ]
    families = QFontDatabase.families()
    for name in fallbacks:
        if name in families:
            app.setFont(QFont(name, 9))
            print(f"Font: {name}")
            return
    print(f"WARN: no CN font, sample: {families[:8]}")
    f = app.font()
    f.setFamilies(["Microsoft YaHei UI", "Sans Serif"])
    app.setFont(f)


def close_all_infobars(window: QApplication) -> None:
    """清掉所有 InfoBar（主要是 _greet 弹的'非管理员'提示条）。"""
    for w in window.allWidgets():
        if isinstance(w, InfoBar):
            w.close()


def wait_ms(ms: int) -> None:
    """跑 processEvents 并真实等待 ms 毫秒（用 QEventLoop + QTimer）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def grab(window: MainWindow, filename: str) -> None:
    """截图并把透明区域合成为白底（消除沙箱里 grab 出来的黑边伪影）。"""
    window.repaint()
    wait_ms(120)
    raw = window.grab()
    # 合成白底：透明区域填成浅灰白（Fluent Design LIGHT 主题底色）
    bg = QPixmap(raw.size())
    bg.fill(QColor("#F5F5F5"))
    painter = QPainter(bg)
    painter.drawPixmap(0, 0, raw)
    painter.end()
    path = os.path.join(SHOTS_DIR, filename)
    bg.save(path, "PNG")
    print(f"  OK {filename}  {bg.width()}x{bg.height()}  "
          f"{os.path.getsize(path)//1024} KB")


def switch_to(window: MainWindow, page_attr: str) -> None:
    """用 FluentWindow.switchTo(页面对象) 切换——比 routeKey 稳。"""
    page = getattr(window, page_attr)
    window.switchTo(page)
    wait_ms(300)  # 给导航 + 页面渲染留时间


def main() -> int:
    app = QApplication(sys.argv)
    setup_chinese_font(app)

    # 关键：设置 LIGHT 主题，让 FluentWindow 有不透明背景
    setTheme(Theme.LIGHT)
    # 统一主题色（与 app 默认一致）；最后一张切到蓝绿色对比
    setThemeColor(QColor(DEFAULT_ACCENT))

    window = MainWindow()
    window.resize(1180, 760)
    window.show()
    wait_ms(400)  # 等 _greet InfoBar 弹出来，然后再清掉

    # 1) 关闭"当前不是管理员权限"提示条（screenshot 进程非管理员）
    close_all_infobars(app)
    wait_ms(120)

    print("== screenshots ==\n")
    for filename, page_attr, desc in SHOTS:
        switch_to(window, page_attr)
        close_all_infobars(app)  # 某些页切换可能再触发
        grab(window, filename)
        print(f"   ({desc})\n")

    # 第 5 张：切到纯蓝色主题色 + 修复页（与默认青绿形成对比，演示"主题色切换"）
    print("== accent color ==\n")
    setThemeColor(QColor("#3B82F6"))  # 纯蓝（与默认青绿 #0094BC 形成对比）
    wait_ms(150)
    switch_to(window, "repairPage")
    close_all_infobars(app)
    grab(window, "fluent-accent-blue.png")
    print("   (主题色: 纯蓝 #3B82F6 + 修复页，与默认青绿对比)\n")

    window.close()
    print("done -> shots/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
