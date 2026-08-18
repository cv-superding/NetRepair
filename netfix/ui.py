"""网络修复工具 —— Fluent Design 界面层。

基于 QFluentWidgets 构建 Windows 11 风格界面：
云母(Mica)背景、亚克力侧边导航、卡片式布局、明暗主题自适应。

业务逻辑全部复用 engine / diagnose / sysutil，本模块只负责呈现与交互。

Copyright (C) 2026 叶神鼬-丁 <2943629243@qq.com>
Licensed under the GNU General Public License v3.0.
"""

from __future__ import annotations

import html
import os
import sys

from PySide6.QtCore import (
    QObject,
    QSettings,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    FluentIcon as FIF,
    FluentWindow,
    IndeterminateProgressBar,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    NavigationItemPosition,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    SimpleCardWidget,
    StrongBodyLabel,
    SubtitleLabel,
    TextEdit,
    Theme,
    TitleLabel,
    TransparentPushButton,
    TransparentToolButton,
    isDarkTheme,
    qconfig,
    setFont,
    setTheme,
    setThemeColor,
)

from . import (
    APP_AUTHOR,
    APP_COPYRIGHT,
    APP_EMAIL,
    APP_LICENSE,
    APP_LICENSE_SHORT,
    APP_NAME,
    APP_RELEASE_DATE,
    APP_VERSION,
    diagnose,
    engine,
)
from .icons import app_icon, make_pixmap
from . import sysutil
from .sysutil import LOGGER, is_admin, open_in_explorer

# ==================================================================== 配色

#: 返回当前主题色的浅色/深色版本（hex 字符串）
def _accent() -> str:
    """返回当前主题色（自动适配明暗主题）。"""
    c: QColor = qconfig.themeColor.value  # type: ignore[union-attr]
    if isDarkTheme():
        return c.lighter(140).name()
    return c.name()


#: 风险等级 -> (浅色主题文字, 浅色底, 深色主题文字, 深色底)
_RISK_PALETTE = {
    engine.RISK_SAFE:   ("#0B6A0B", "#DFF6DD", "#6CCB5F", "#28331F"),
    engine.RISK_MEDIUM: ("#8A5300", "#FFF4CE", "#FCE100", "#3B3419"),
    engine.RISK_HIGH:   ("#B42318", "#FDE7E9", "#FF99A4", "#3B2326"),
}

#: 诊断等级 -> (图标名, 浅色, 深色)
_LEVEL_PALETTE = {
    diagnose.LEVEL_OK:    ("check", "#0F7B0F", "#6CCB5F"),
    diagnose.LEVEL_WARN:  ("alert", "#B26A00", "#FCE100"),
    diagnose.LEVEL_ERROR: ("alert", "#C42B1C", "#FF99A4"),
}

#: 日志级别 -> (浅色, 深色)
_LOG_PALETTE = {
    "INFO":  ("#5A6270", "#9AA3B2"),
    "OK":    ("#0F7B0F", "#6CCB5F"),
    "WARN":  ("#B26A00", "#F0C000"),
    "ERROR": ("#C42B1C", "#FF99A4"),
}

_ACCENTS = [
    ("经典蓝", "#0078D4"),
    ("石墨青", "#0E7C86"),
    ("鸢尾紫", "#7B68C4"),
    ("松林绿", "#107C41"),
    ("落日橙", "#CA5010"),
]


def _pick(light: str, dark: str) -> str:
    return dark if isDarkTheme() else light


def _style_text(widget, *, line_height: float = 1.7, letter: float = 0.35) -> None:
    """为文本标签设置字间距与行高，使排版更舒展、不拥挤。

    - 字间距通过 ``QFont.setLetterSpacing`` 实现，单行 / 多行均生效。
    - 行高仅对开启 ``wordWrap`` 的多行文本生效，借助富文本 ``<p>`` 实现；
      颜色由 QFluentWidgets 的 ``setTextColor`` 经样式表级联到富文本，主题切换仍生效。
    """
    f = widget.font()
    f.setLetterSpacing(QFont.AbsoluteSpacing, letter)
    widget.setFont(f)
    if line_height and getattr(widget, "wordWrap", lambda: False)():
        safe = html.escape(widget.text())
        widget.setTextFormat(Qt.RichText)
        widget.setText(f'<p style="line-height:{line_height};margin:0;">{safe}</p>')


def _fmt_size(num: int) -> str:
    if num < 1024:
        return f"{num} B"
    if num < 1024 * 1024:
        return f"{num / 1024:.1f} KB"
    return f"{num / 1024 / 1024:.1f} MB"


def _saved_index(settings: QSettings, key: str, count: int) -> int:
    """读取 QSettings 里保存的下拉框索引，钳制到有效范围，防止脏数据导致启动崩溃。"""
    try:
        idx = int(settings.value(key, 0))
    except (TypeError, ValueError):
        idx = 0
    return min(max(idx, 0), count - 1)


# ==================================================================== 通用控件

class RiskBadge(QLabel):
    """风险等级小标签（自绘样式，随主题变色）。"""

    def __init__(self, risk: str, parent: QWidget | None = None) -> None:
        super().__init__(engine.RISK_TEXT.get(risk, risk), parent)
        self._risk = risk
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(20)
        self.setContentsMargins(0, 0, 0, 0)
        self.refresh()

    def refresh(self) -> None:
        lt, lb, dt, db = _RISK_PALETTE.get(
            self._risk, ("#5A6270", "#EEEEEE", "#9AA3B2", "#2B2B2B"))
        fg, bg = (dt, db) if isDarkTheme() else (lt, lb)
        self.setStyleSheet(
            f"QLabel{{color:{fg};background:{bg};border-radius:10px;"
            f"padding:0 9px;font-size:12px;font-weight:600;}}")


class StatusDot(QLabel):
    """诊断结果状态图标。"""

    def __init__(self, level: str = diagnose.LEVEL_OK,
                 size: int = 20, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._level = level
        self._size = size
        self.setFixedSize(size + 4, size + 4)
        self.setAlignment(Qt.AlignCenter)
        self.refresh()

    def setLevel(self, level: str) -> None:
        self._level = level
        self.refresh()

    def refresh(self) -> None:
        name, light, dark = _LEVEL_PALETTE.get(
            self._level, ("info", "#5A6270", "#9AA3B2"))
        self.setPixmap(make_pixmap(name, _pick(light, dark), self._size, 2.0))


class BaseInterface(ScrollArea):
    """所有页面的基类：可滚动 + 透明背景 + 统一留白。"""

    def __init__(self, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)

        self.view = QWidget(self)
        self.view.setObjectName("interfaceView")
        self.vbox = QVBoxLayout(self.view)
        self.vbox.setContentsMargins(28, 12, 28, 24)
        self.vbox.setSpacing(14)
        self.vbox.setAlignment(Qt.AlignTop)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 0, 0, 0)
        if hasattr(self, "enableTransparentBackground"):
            self.enableTransparentBackground()
        self.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "#interfaceView{background:transparent;}")

    def add_header(self, title: str, subtitle: str) -> None:
        box = QVBoxLayout()
        box.setSpacing(2)
        t = TitleLabel(title, self.view)
        s = CaptionLabel(subtitle, self.view)
        s.setTextColor("#61666D", "#9AA3B2")
        box.addWidget(t)
        box.addWidget(s)
        wrap = QWidget(self.view)
        wrap.setLayout(box)
        self.vbox.addWidget(wrap)


# ==================================================================== 后台线程

class RepairWorker(QThread):
    itemStarted = Signal(str)
    itemFinished = Signal(str, object)
    progressed = Signal(int, int)
    allFinished = Signal(bool, int, int)

    def __init__(self, items: list, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.items = items
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def run(self) -> None:  # noqa: D102
        total = len(self.items)
        ok_n = fail_n = 0
        reboot = False
        for idx, item in enumerate(self.items, start=1):
            if self._abort:
                break
            self.itemStarted.emit(item.key)
            LOGGER.info(f"===== 开始修复：{item.name} =====")
            try:
                res = item.action()
            except Exception as exc:  # noqa: BLE001
                res = engine.RepairResult(ok=False, summary=f"执行异常：{exc}")
                LOGGER.error(f"{item.name} 执行异常：{exc}")
            if res.ok:
                ok_n += 1
            else:
                fail_n += 1
            if item.need_reboot or res.need_reboot:
                reboot = True
            self.itemFinished.emit(item.key, res)
            self.progressed.emit(idx, total)
        self.allFinished.emit(reboot, ok_n, fail_n)


class DiagnoseWorker(QThread):
    progressed = Signal(int, int, str)
    resultReady = Signal(object)

    def run(self) -> None:  # noqa: D102
        def cb(done: int, total: int, msg: str) -> None:
            self.progressed.emit(done, total, msg)

        try:
            results = diagnose.run_all(progress=cb)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(f"诊断异常：{exc}")
            results = []
        self.resultReady.emit(results)


class LogBridge(QObject):
    """把子线程日志安全地转发到 GUI 线程。"""

    line = Signal(str, str)


# ==================================================================== 修复页

class RepairCard(CardWidget):
    """单个修复项卡片。"""

    fixRequested = Signal(object)

    def __init__(self, item, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self._busy = False
        self.setClickEnabled(True)
        self.clicked.connect(self._on_card_clicked)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 12, 14, 12)
        root.setSpacing(12)

        self.check = CheckBox(self)
        self.check.setChecked(item.default_checked)
        self.check.setFixedWidth(20)
        root.addWidget(self.check, 0, Qt.AlignTop)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        mid.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.nameLabel = StrongBodyLabel(item.name, self)
        self.badge = RiskBadge(item.risk, self)
        top.addWidget(self.nameLabel)
        top.addWidget(self.badge)
        if item.need_reboot:
            reboot = CaptionLabel("需重启", self)
            reboot.setTextColor("#8A5300", "#FCE100")
            top.addWidget(reboot)
        top.addStretch(1)
        mid.addLayout(top)

        self.descLabel = CaptionLabel(item.desc, self)
        self.descLabel.setWordWrap(True)
        self.descLabel.setTextColor("#61666D", "#9AA3B2")
        mid.addWidget(self.descLabel)

        if item.note:
            self.noteLabel = CaptionLabel(f"提示：{item.note}", self)
            self.noteLabel.setWordWrap(True)
            self.noteLabel.setTextColor("#8A5300", "#E3B341")
            mid.addWidget(self.noteLabel)

        self.resultLabel = CaptionLabel("", self)
        self.resultLabel.setWordWrap(True)
        self.resultLabel.hide()
        mid.addWidget(self.resultLabel)

        root.addLayout(mid, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        self.statusLabel = CaptionLabel("待执行", self)
        self.statusLabel.setTextColor("#8A8F99", "#7C838F")
        self.statusLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.fixBtn = PushButton(FIF.PLAY, "单独修复", self)
        self.fixBtn.setFixedHeight(30)
        self.fixBtn.clicked.connect(lambda: self.fixRequested.emit(self.item))
        right.addWidget(self.statusLabel, 0, Qt.AlignRight)
        right.addWidget(self.fixBtn, 0, Qt.AlignRight)
        right.addStretch(1)
        root.addLayout(right, 0)

    # ---------------------------------------------------------------- 交互
    def _on_card_clicked(self) -> None:
        if not self._busy and self.check.isEnabled():
            self.check.setChecked(not self.check.isChecked())

    def isChecked(self) -> bool:
        return self.check.isChecked()

    def setChecked(self, value: bool) -> None:
        self.check.setChecked(value)

    def setInteractive(self, enabled: bool) -> None:
        self.check.setEnabled(enabled)
        self.fixBtn.setEnabled(enabled)
        self.setClickEnabled(enabled)

    def markRunning(self) -> None:
        self._busy = True
        self.statusLabel.setText("修复中…")
        self.statusLabel.setTextColor(_accent(), _accent())
        self.resultLabel.hide()

    def markResult(self, res) -> None:
        self._busy = False
        if res.ok:
            self.statusLabel.setText("✓ 已完成")
            self.statusLabel.setTextColor("#0F7B0F", "#6CCB5F")
            self.resultLabel.setTextColor("#0F7B0F", "#6CCB5F")
        else:
            self.statusLabel.setText("✗ 未完成")
            self.statusLabel.setTextColor("#C42B1C", "#FF99A4")
            self.resultLabel.setTextColor("#C42B1C", "#FF99A4")
        text = res.summary or ("执行完成" if res.ok else "执行失败")
        failed = [s for s in res.steps if not s.ok]
        if failed:
            text += "｜失败步骤：" + "、".join(s.title for s in failed[:3])
        self.resultLabel.setText(text)
        self.resultLabel.show()

    def reset(self) -> None:
        self._busy = False
        self.statusLabel.setText("待执行")
        self.statusLabel.setTextColor("#8A8F99", "#7C838F")
        self.resultLabel.hide()

    def refreshTheme(self) -> None:
        self.badge.refresh()


class RepairInterface(BaseInterface):
    """一键修复页。"""

    logRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("repairInterface", parent)
        self.items = engine.build_items()
        self.cards: dict[str, RepairCard] = {}
        self.worker: RepairWorker | None = None
        self.diagWorker: DiagnoseWorker | None = None

        self.add_header("一键修复", "选择需要处理的项目，程序会按顺序逐项执行并记录每一步结果")
        self._build_hero()
        self._build_toolbar()
        self._build_list()

    # ---------------------------------------------------------------- 构建
    def _build_hero(self) -> None:
        card = SimpleCardWidget(self.view)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(16)

        self.heroIcon = QLabel(card)
        self.heroIcon.setFixedSize(44, 44)
        self.heroIcon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.heroIcon, 0, Qt.AlignVCenter)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.heroTitle = SubtitleLabel("准备就绪", card)
        self.heroDesc = CaptionLabel(
            f"共 {len(self.items)} 个修复项，默认已勾选风险较低的常用项目", card)
        self.heroDesc.setTextColor("#61666D", "#9AA3B2")
        self.progress = ProgressBar(card)
        self.progress.setFixedHeight(4)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        mid.addWidget(self.heroTitle)
        mid.addWidget(self.heroDesc)
        mid.addWidget(self.progress)
        lay.addLayout(mid, 1)

        self.smartBtn = PushButton(FIF.SEARCH, "智能勾选", card)
        self.smartBtn.setFixedHeight(34)
        self.smartBtn.clicked.connect(self.smart_select)
        self.runBtn = PrimaryPushButton(FIF.PLAY, "开始修复", card)
        self.runBtn.setFixedHeight(34)
        self.runBtn.setMinimumWidth(120)
        self.runBtn.clicked.connect(self.start_repair)
        lay.addWidget(self.smartBtn, 0, Qt.AlignVCenter)
        lay.addWidget(self.runBtn, 0, Qt.AlignVCenter)

        self.heroCard = card
        self.vbox.addWidget(card)
        self._refresh_hero_icon()

    def _refresh_hero_icon(self, name: str = "shield", color: str | None = None) -> None:
        self._heroIconName = name
        col = color or _accent()
        self.heroIcon.setPixmap(make_pixmap(name, col, 40, 1.8))

    def _build_toolbar(self) -> None:
        bar = QWidget(self.view)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(8)

        self.countLabel = CaptionLabel("", bar)
        self.countLabel.setTextColor("#61666D", "#9AA3B2")

        allBtn = TransparentPushButton("全选", bar)
        noneBtn = TransparentPushButton("全不选", bar)
        recBtn = TransparentPushButton("仅推荐项", bar)
        allBtn.clicked.connect(lambda: self._set_all(True))
        noneBtn.clicked.connect(lambda: self._set_all(False))
        recBtn.clicked.connect(self._select_recommended)

        lay.addWidget(self.countLabel)
        lay.addStretch(1)
        for b in (allBtn, noneBtn, recBtn):
            b.setFixedHeight(30)
            lay.addWidget(b)
        self.vbox.addWidget(bar)

    def _build_list(self) -> None:
        for item in self.items:
            card = RepairCard(item, self.view)
            card.fixRequested.connect(self._run_single)
            card.check.stateChanged.connect(self._update_count)
            self.cards[item.key] = card
            self.vbox.addWidget(card)
        self._update_count()

    # ---------------------------------------------------------------- 勾选
    def _set_all(self, value: bool) -> None:
        for c in self.cards.values():
            c.setChecked(value)

    def _select_recommended(self) -> None:
        for item in self.items:
            self.cards[item.key].setChecked(item.default_checked)

    def _update_count(self) -> None:
        n = sum(1 for c in self.cards.values() if c.isChecked())
        self.countLabel.setText(f"已选择 {n} / {len(self.cards)} 项")

    def checked_items(self) -> list:
        return [i for i in self.items if self.cards[i.key].isChecked()]

    # ---------------------------------------------------------------- 智能勾选
    def smart_select(self) -> None:
        if self._is_busy():
            return
        self.smartBtn.setEnabled(False)
        self.runBtn.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self.heroTitle.setText("正在诊断…")
        self.heroDesc.setText("正在检测网络状态，稍后会自动勾选真正需要的修复项")
        self._refresh_hero_icon("activity")

        self.diagWorker = DiagnoseWorker(self)
        self.diagWorker.progressed.connect(self._on_smart_progress)
        self.diagWorker.resultReady.connect(self._on_smart_done)
        self.diagWorker.start()

    def _on_smart_progress(self, done: int, total: int, msg: str) -> None:
        self.progress.setValue(int(done * 100 / max(total, 1)))
        self.heroDesc.setText(f"{msg}（{done}/{total}）")

    def _on_smart_done(self, results: list) -> None:
        self.progress.hide()
        self.smartBtn.setEnabled(True)
        self.runBtn.setEnabled(True)
        if not results:
            self.heroTitle.setText("诊断失败")
            self.heroDesc.setText("未能完成检测，请查看运行日志")
            return

        keys = diagnose.collect_suggestions(results)
        level, text = diagnose.diagnose_conclusion(results)
        for c in self.cards.values():
            c.setChecked(False)
        hit = 0
        for k in keys:
            if k in self.cards:
                self.cards[k].setChecked(True)
                hit += 1

        self.heroTitle.setText("诊断完成")
        self.heroDesc.setText(text)
        icon, light, dark = _LEVEL_PALETTE.get(level, ("shield", _accent(), _accent()))
        self._refresh_hero_icon(icon, _pick(light, dark))

        if hit:
            self._info(f"已根据诊断结果勾选 {hit} 项", text, "warning")
        else:
            self._select_recommended()
            self._info("网络状态良好", "未发现明确故障，已恢复为默认推荐勾选", "success")

    # ---------------------------------------------------------------- 执行
    def _is_busy(self) -> bool:
        if self.worker and self.worker.isRunning():
            self._info("正在修复中", "请等待当前任务完成", "warning")
            return True
        if self.diagWorker and self.diagWorker.isRunning():
            self._info("正在诊断中", "请稍候", "warning")
            return True
        return False

    def _run_single(self, item) -> None:
        if self._is_busy():
            return
        self._start([item])

    def start_repair(self) -> None:
        if self._is_busy():
            return
        items = self.checked_items()
        if not items:
            self._info("未选择项目", "请至少勾选一个修复项", "warning")
            return
        risky = [i.name for i in items if i.risk == engine.RISK_HIGH]
        if risky:
            box = MessageBox(
                "确认执行高风险项目",
                "以下项目会清除你的自定义配置（已自动备份，可在「备份还原」页恢复）：\n\n"
                + "\n".join(f"· {n}" for n in risky)
                + "\n\n确定继续吗？",
                self.window())
            box.yesButton.setText("继续修复")
            box.cancelButton.setText("再想想")
            if not box.exec():
                return
        self._start(items)

    def _start(self, items: list) -> None:
        for c in self.cards.values():
            c.reset()
            c.setInteractive(False)
        self.runBtn.setEnabled(False)
        self.smartBtn.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self.heroTitle.setText("正在修复…")
        self.heroDesc.setText(f"共 {len(items)} 项，请勿关闭窗口")
        self._refresh_hero_icon("rotate")

        self.worker = RepairWorker(items, self)
        self.worker.itemStarted.connect(self._on_item_started)
        self.worker.itemFinished.connect(self._on_item_finished)
        self.worker.progressed.connect(self._on_progress)
        self.worker.allFinished.connect(self._on_all_finished)
        self.worker.start()

    def _on_item_started(self, key: str) -> None:
        card = self.cards.get(key)
        if card:
            card.markRunning()
            self.heroDesc.setText(f"正在执行：{card.item.name}")

    def _on_item_finished(self, key: str, res) -> None:
        card = self.cards.get(key)
        if card:
            card.markResult(res)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setValue(int(done * 100 / max(total, 1)))

    def _on_all_finished(self, reboot: bool, ok_n: int, fail_n: int) -> None:
        self.progress.hide()
        for c in self.cards.values():
            c.setInteractive(True)
        self.runBtn.setEnabled(True)
        self.smartBtn.setEnabled(True)

        if fail_n == 0:
            self.heroTitle.setText("修复完成")
            self._refresh_hero_icon("check", _pick("#0F7B0F", "#6CCB5F"))
            tail = "，建议重启计算机使部分改动生效" if reboot else ""
            self.heroDesc.setText(f"{ok_n} 项全部成功{tail}")
            self._info("修复完成", f"{ok_n} 项全部成功{tail}", "success", 5000)
        else:
            self.heroTitle.setText("部分项目未完成")
            self._refresh_hero_icon("alert", _pick("#B26A00", "#FCE100"))
            self.heroDesc.setText(f"成功 {ok_n} 项，失败 {fail_n} 项，可在运行日志查看详情")
            self._info("部分项目未完成",
                       f"成功 {ok_n} 项，失败 {fail_n} 项，详情见运行日志", "warning", 6000)

        if reboot:
            QTimer.singleShot(600, self._ask_reboot)

    def _ask_reboot(self) -> None:
        box = MessageBox(
            "需要重启计算机",
            "本次修复包含 Winsock / TCP-IP 协议栈重置，必须重启后才能完全生效。\n\n"
            "是否现在重启？（请先保存好正在编辑的文件）",
            self.window())
        box.yesButton.setText("立即重启")
        box.cancelButton.setText("稍后自行重启")
        if box.exec():
            os.system("shutdown /r /t 5 /c \"网络修复完成，系统即将重启\"")  # noqa: S605

    def _info(self, title: str, content: str, kind: str = "info",
              duration: int = 4000) -> None:
        fn = {"success": InfoBar.success, "warning": InfoBar.warning,
              "error": InfoBar.error}.get(kind, InfoBar.info)
        fn(title=title, content=content, orient=Qt.Horizontal, isClosable=True,
           position=InfoBarPosition.TOP_RIGHT, duration=duration,
           parent=self.window())

    def refreshTheme(self) -> None:
        for c in self.cards.values():
            c.refreshTheme()
        self._refresh_hero_icon(getattr(self, "_heroIconName", "shield"))


# ==================================================================== 诊断页

class CheckCard(CardWidget):
    """单条诊断结果卡片。"""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._level = diagnose.LEVEL_OK
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)

        self.dot = StatusDot(diagnose.LEVEL_OK, 20, self)
        lay.addWidget(self.dot, 0, Qt.AlignTop)

        mid = QVBoxLayout()
        mid.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.nameLabel = StrongBodyLabel(name, self)
        self.levelLabel = CaptionLabel("待检测", self)
        self.levelLabel.setTextColor("#8A8F99", "#7C838F")
        top.addWidget(self.nameLabel)
        top.addWidget(self.levelLabel)
        top.addStretch(1)
        mid.addLayout(top)

        self.detailLabel = CaptionLabel("—", self)
        self.detailLabel.setWordWrap(True)
        self.detailLabel.setTextColor("#61666D", "#9AA3B2")
        mid.addWidget(self.detailLabel)
        lay.addLayout(mid, 1)

    def setPending(self) -> None:
        self.levelLabel.setText("检测中…")
        self.levelLabel.setTextColor(_accent(), _accent())
        self.detailLabel.setText("正在检测…")

    def setResult(self, res) -> None:
        self._level = res.level
        self.dot.setLevel(res.level)
        self.levelLabel.setText(diagnose.LEVEL_TEXT.get(res.level, res.level))
        _, light, dark = _LEVEL_PALETTE.get(res.level, ("info", "#61666D", "#9AA3B2"))
        self.levelLabel.setTextColor(light, dark)
        self.detailLabel.setText(res.detail or "—")

    def refreshTheme(self) -> None:
        self.dot.refresh()


class DiagnoseInterface(BaseInterface):
    """网络诊断页。"""

    suggestionsReady = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("diagnoseInterface", parent)
        self.cards: dict[str, CheckCard] = {}
        self.worker: DiagnoseWorker | None = None
        self.lastResults: list = []

        self.add_header("网络诊断", "逐项检测网络链路，定位真正的故障点，再有针对性地修复")
        self._build_hero()
        self._build_list()

    def _build_hero(self) -> None:
        card = SimpleCardWidget(self.view)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(16)

        self.heroIcon = QLabel(card)
        self.heroIcon.setFixedSize(44, 44)
        self.heroIcon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.heroIcon, 0, Qt.AlignVCenter)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.heroTitle = SubtitleLabel("尚未检测", card)
        self.heroDesc = CaptionLabel(
            f"共 {len(diagnose.CHECKS)} 项检查，全程只读不修改任何配置", card)
        self.heroDesc.setTextColor("#61666D", "#9AA3B2")
        self.progress = ProgressBar(card)
        self.progress.setFixedHeight(4)
        self.progress.setRange(0, 100)
        self.progress.hide()
        mid.addWidget(self.heroTitle)
        mid.addWidget(self.heroDesc)
        mid.addWidget(self.progress)
        lay.addLayout(mid, 1)

        self.runBtn = PrimaryPushButton(FIF.SEARCH, "开始检测", card)
        self.runBtn.setFixedHeight(34)
        self.runBtn.setMinimumWidth(120)
        self.runBtn.clicked.connect(self.start)
        lay.addWidget(self.runBtn, 0, Qt.AlignVCenter)

        self.vbox.addWidget(card)
        self._set_hero_icon("wifi")

    def _set_hero_icon(self, name: str, color: str | None = None) -> None:
        self._heroIconName = name
        self.heroIcon.setPixmap(
            make_pixmap(name, color or _accent(), 40, 1.8))

    def _build_list(self) -> None:
        for label, _fn in diagnose.CHECKS:
            card = CheckCard(label, self.view)
            self.cards[label] = card
            self.vbox.addWidget(card)

        self.suggestCard = SimpleCardWidget(self.view)
        sl = QVBoxLayout(self.suggestCard)
        sl.setContentsMargins(18, 14, 18, 14)
        sl.setSpacing(6)
        sl.addWidget(StrongBodyLabel("修复建议", self.suggestCard))
        self.suggestLabel = BodyLabel("—", self.suggestCard)
        self.suggestLabel.setWordWrap(True)
        sl.addWidget(self.suggestLabel)
        self.gotoBtn = PushButton(FIF.BROOM, "去修复页并自动勾选", self.suggestCard)
        self.gotoBtn.setFixedHeight(32)
        sl.addWidget(self.gotoBtn, 0, Qt.AlignLeft)
        self.suggestCard.hide()
        self.vbox.addWidget(self.suggestCard)

    # ---------------------------------------------------------------- 执行
    def start(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        for c in self.cards.values():
            c.setPending()
        self.suggestCard.hide()
        self.runBtn.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.heroTitle.setText("正在检测…")
        self._set_hero_icon("activity")

        self.worker = DiagnoseWorker(self)
        self.worker.progressed.connect(self._on_progress)
        self.worker.resultReady.connect(self._on_done)
        self.worker.start()

    def _on_progress(self, done: int, total: int, msg: str) -> None:
        self.progress.setValue(int(done * 100 / max(total, 1)))
        self.heroDesc.setText(f"{msg}（{done}/{total}）")

    def _on_done(self, results: list) -> None:
        self.progress.hide()
        self.runBtn.setEnabled(True)
        self.lastResults = results
        if not results:
            self.heroTitle.setText("检测失败")
            self.heroDesc.setText("未能完成检测，请查看运行日志")
            self._set_hero_icon("alert", _pick("#C42B1C", "#FF99A4"))
            return

        # 结果与 CHECKS 顺序一一对应；不能按名称查找——部分检查项返回的
        # name 带后缀（如「外网直连（绕过代理）」），与卡片标题「外网直连」不一致，
        # 按名称匹配会让这些卡片永远停在「检测中…」。
        for card, res in zip(self.cards.values(), results):
            card.setResult(res)

        level, text = diagnose.diagnose_conclusion(results)
        self.heroTitle.setText({
            diagnose.LEVEL_OK: "网络正常",
            diagnose.LEVEL_WARN: "存在可优化项",
            diagnose.LEVEL_ERROR: "发现故障",
        }.get(level, "检测完成"))
        self.heroDesc.setText(text)
        icon, light, dark = _LEVEL_PALETTE.get(level, ("wifi", _accent(), _accent()))
        self._set_hero_icon(icon, _pick(light, dark))

        keys = diagnose.collect_suggestions(results)
        if keys:
            name_of = {i.key: i.name for i in engine.build_items()}
            self.suggestLabel.setText(
                "建议执行以下修复：\n" +
                "\n".join(f"· {name_of.get(k, k)}" for k in keys))
            try:
                self.gotoBtn.clicked.disconnect()
            except RuntimeError:
                pass
            self.gotoBtn.clicked.connect(
                lambda: self.suggestionsReady.emit(list(keys)))
            self.suggestCard.show()

    def refreshTheme(self) -> None:
        for c in self.cards.values():
            c.refreshTheme()
        self._set_hero_icon(getattr(self, "_heroIconName", "wifi"))


# ==================================================================== 日志页

class LogInterface(BaseInterface):
    """运行日志页。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("logInterface", parent)
        self._autoscroll = True
        self.add_header("运行日志", "记录每一条命令的执行结果，可导出排查问题")

        bar = QWidget(self.view)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(8)
        self.pathLabel = CaptionLabel(f"日志文件：{LOGGER.path}", bar)
        self.pathLabel.setTextColor("#61666D", "#9AA3B2")
        lay.addWidget(self.pathLabel)
        lay.addStretch(1)

        openBtn = TransparentPushButton(FIF.FOLDER, "打开目录", bar)
        copyBtn = TransparentPushButton(FIF.COPY, "复制全部", bar)
        clearBtn = TransparentPushButton(FIF.DELETE, "清空显示", bar)
        openBtn.clicked.connect(lambda: open_in_explorer(sysutil.LOG_DIR))
        copyBtn.clicked.connect(self._copy_all)
        clearBtn.clicked.connect(lambda: self.logView.clear())
        for b in (openBtn, copyBtn, clearBtn):
            b.setFixedHeight(30)
            lay.addWidget(b)
        self.vbox.addWidget(bar)

        card = SimpleCardWidget(self.view)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        self.logView = TextEdit(card)
        self.logView.setReadOnly(True)
        self.logView.setMinimumHeight(460)
        self.logView.setLineWrapMode(TextEdit.LineWrapMode.NoWrap)
        font = self.logView.font()
        font.setFamilies(["Cascadia Mono", "Consolas", "Microsoft YaHei UI"])
        font.setPointSize(9)
        self.logView.setFont(font)
        cl.addWidget(self.logView)
        self.vbox.addWidget(card)

        for line in LOGGER.lines:
            self.append(line, "INFO")

    def append(self, line: str, level: str = "INFO") -> None:
        light, dark = _LOG_PALETTE.get(level, _LOG_PALETTE["INFO"])
        color = _pick(light, dark)
        self.logView.append(
            f'<span style="color:{color};white-space:pre;">{html.escape(line)}</span>')
        if self._autoscroll:
            sb = self.logView.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _copy_all(self) -> None:
        QApplication.clipboard().setText(LOGGER.text())
        InfoBar.success(title="已复制", content="全部日志已复制到剪贴板",
                        orient=Qt.Horizontal, isClosable=True,
                        position=InfoBarPosition.TOP_RIGHT, duration=2500,
                        parent=self.window())


# ==================================================================== 备份页

class BackupCard(CardWidget):
    restoreRequested = Signal(dict)

    def __init__(self, info: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.info = info
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 14, 12)
        lay.setSpacing(12)

        self.icon = QLabel(self)
        self.icon.setFixedSize(24, 24)
        self.icon.setPixmap(make_pixmap("archive", _accent(), 22, 1.8))
        lay.addWidget(self.icon, 0, Qt.AlignVCenter)

        mid = QVBoxLayout()
        mid.setSpacing(2)
        mid.addWidget(StrongBodyLabel(info["label"], self))
        sub = CaptionLabel(f"{info['time']}　·　{_fmt_size(info['size'])}　·　{info['name']}", self)
        sub.setTextColor("#61666D", "#9AA3B2")
        sub.setWordWrap(True)
        mid.addWidget(sub)
        lay.addLayout(mid, 1)

        restorable = info["kind"] in ("hosts", "proxy")
        btn = PushButton(FIF.SYNC, "还原", self)
        btn.setFixedHeight(30)
        btn.setEnabled(restorable)
        if not restorable:
            btn.setToolTip("该类型备份需手动还原")
        btn.clicked.connect(lambda: self.restoreRequested.emit(self.info))
        lay.addWidget(btn, 0, Qt.AlignVCenter)

    def refreshTheme(self) -> None:
        self.icon.setPixmap(make_pixmap("archive", _accent(), 22, 1.8))


class BackupInterface(BaseInterface):
    """备份还原页。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("backupInterface", parent)
        self.cards: list[BackupCard] = []
        self.add_header("备份还原", "修复前自动保存的配置快照，随时可以一键回滚")

        bar = QWidget(self.view)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(8)
        self.countLabel = CaptionLabel("", bar)
        self.countLabel.setTextColor("#61666D", "#9AA3B2")
        lay.addWidget(self.countLabel)
        lay.addStretch(1)
        refreshBtn = TransparentPushButton(FIF.SYNC, "刷新", bar)
        openBtn = TransparentPushButton(FIF.FOLDER, "打开备份目录", bar)
        refreshBtn.clicked.connect(self.reload)
        openBtn.clicked.connect(lambda: open_in_explorer(sysutil.BACKUP_DIR))
        for b in (refreshBtn, openBtn):
            b.setFixedHeight(30)
            lay.addWidget(b)
        self.vbox.addWidget(bar)

        self.listBox = QVBoxLayout()
        self.listBox.setSpacing(10)
        holder = QWidget(self.view)
        holder.setLayout(self.listBox)
        self.vbox.addWidget(holder)

        self.emptyCard = SimpleCardWidget(self.view)
        el = QVBoxLayout(self.emptyCard)
        el.setContentsMargins(20, 26, 20, 26)
        el.setSpacing(6)
        el.setAlignment(Qt.AlignCenter)
        tip = SubtitleLabel("暂无备份记录", self.emptyCard)
        tip.setAlignment(Qt.AlignCenter)
        tip2 = CaptionLabel("执行「重置 Hosts」「重置代理」等项目时会自动生成备份",
                            self.emptyCard)
        tip2.setAlignment(Qt.AlignCenter)
        tip2.setTextColor("#61666D", "#9AA3B2")
        el.addWidget(tip)
        el.addWidget(tip2)
        self.vbox.addWidget(self.emptyCard)

        self.reload()

    def reload(self) -> None:
        while self.listBox.count():
            item = self.listBox.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.cards.clear()

        data = engine.list_backups()
        self.countLabel.setText(f"共 {len(data)} 个备份文件")
        self.emptyCard.setVisible(not data)
        for info in data:
            card = BackupCard(info, self.view)
            card.restoreRequested.connect(self._restore)
            self.listBox.addWidget(card)
            self.cards.append(card)

    def _restore(self, info: dict) -> None:
        box = MessageBox(
            "确认还原",
            f"即将把「{info['label']}」还原到 {info['time']} 的状态。\n\n"
            f"文件：{info['name']}\n\n当前配置会先被自动备份一次，确定继续吗？",
            self.window())
        box.yesButton.setText("立即还原")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        ok, msg = engine.restore_backup(info["path"])
        LOGGER.write(f"还原备份 {info['name']} -> {msg}", "OK" if ok else "ERROR")
        fn = InfoBar.success if ok else InfoBar.error
        fn(title="还原成功" if ok else "还原失败", content=msg,
           orient=Qt.Horizontal, isClosable=True,
           position=InfoBarPosition.TOP_RIGHT, duration=5000, parent=self.window())
        self.reload()

    def refreshTheme(self) -> None:
        for c in self.cards:
            c.refreshTheme()


# ==================================================================== 关于页

class AboutInterface(BaseInterface):
    """关于与设置页。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("aboutInterface", parent)
        self._settings = QSettings("NetRepair", "NetRepair")
        self.vbox.setSpacing(20)
        self.vbox.setContentsMargins(28, 16, 28, 30)
        self.add_header("关于", "版本信息、外观设置与开源许可说明")

        # ---- 应用信息
        card = SimpleCardWidget(self.view)
        card.setBorderRadius(12)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(26, 24, 26, 24)
        lay.setSpacing(22)
        logo = QLabel(card)
        logo.setFixedSize(78, 78)
        logo.setPixmap(app_icon().pixmap(78, 78))
        lay.addWidget(logo, 0, Qt.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(8)
        nameLabel = TitleLabel(APP_NAME, card)
        _style_text(nameLabel, letter=0.6)
        info.addWidget(nameLabel)
        ver = BodyLabel(f"版本 {APP_VERSION}　·　Fluent Design 界面", card)
        ver.setTextColor("#61666D", "#9AA3B2")
        _style_text(ver, letter=0.3)
        info.addWidget(ver)
        desc = BodyLabel(
            "一个纯本地运行的 Windows 网络故障排查与修复工具。\n"
            "全部操作基于系统自带的 netsh / ipconfig / PowerShell 命令，"
            "不上传任何数据，不联网校验，不捆绑任何组件。", card)
        desc.setWordWrap(True)
        desc.setTextColor("#3B4250", "#C6CBD5")
        _style_text(desc, line_height=1.85, letter=0.3)
        info.addWidget(desc)
        copy = CaptionLabel(f"{APP_COPYRIGHT}　·　{APP_LICENSE_SHORT}", card)
        copy.setTextColor("#8A8F99", "#7C838F")
        _style_text(copy, letter=0.2)
        info.addWidget(copy)
        lay.addLayout(info, 1)
        self.vbox.addWidget(card)

        # ---- 作者信息
        author_card = SimpleCardWidget(self.view)
        author_card.setBorderRadius(12)
        al = QVBoxLayout(author_card)
        al.setContentsMargins(26, 20, 26, 20)
        al.setSpacing(6)
        section = StrongBodyLabel("作者信息", author_card)
        _style_text(section, letter=0.5)
        al.addWidget(section)
        al.addSpacing(6)

        rows = (
            ("作者", APP_AUTHOR, None),
            ("联系邮箱", APP_EMAIL, f"mailto:{APP_EMAIL}"),
            ("发布日期", APP_RELEASE_DATE, None),
            ("开源许可", APP_LICENSE, None),
        )
        for i, (label, value, action) in enumerate(rows):
            row = QHBoxLayout()
            row.setSpacing(14)
            key = BodyLabel(label, author_card)
            key.setFixedWidth(84)
            key.setTextColor("#5A6270", "#9AA3B2")
            _style_text(key, letter=0.4)
            row.addWidget(key)
            row.addSpacing(6)
            if action:
                link = TransparentPushButton(FIF.MAIL, value, author_card)
                link.setFixedHeight(32)
                link.setToolTip("点击发送邮件")
                link.clicked.connect(
                    lambda _=False, u=action: QDesktopServices.openUrl(u))
                row.addWidget(link, 0, Qt.AlignLeft)
                copyBtn = TransparentToolButton(FIF.COPY, author_card)
                copyBtn.setToolTip("复制邮箱地址")
                copyBtn.clicked.connect(self._copy_email)
                row.addWidget(copyBtn, 0, Qt.AlignLeft)
            else:
                val = BodyLabel(value, author_card)
                val.setWordWrap(True)
                _style_text(val, letter=0.3)
                row.addWidget(val, 0, Qt.AlignLeft)
            row.addStretch(1)
            al.addLayout(row)
            if i != len(rows) - 1:
                sep = QFrame(author_card)
                sep.setFrameShape(QFrame.HLine)
                sep.setFixedHeight(1)
                sep.setStyleSheet("QFrame{border:none;background:rgba(128,128,128,0.22);}")
                al.addSpacing(8)
                al.addWidget(sep)
                al.addSpacing(8)

        tip = CaptionLabel(
            "使用中遇到问题、发现误报或有功能建议，欢迎通过上方邮箱反馈。", author_card)
        tip.setWordWrap(True)
        tip.setTextColor("#61666D", "#9AA3B2")
        _style_text(tip, line_height=1.7, letter=0.3)
        al.addSpacing(6)
        al.addWidget(tip)
        self.vbox.addWidget(author_card)

        # ---- 外观设置
        theme_card = SimpleCardWidget(self.view)
        theme_card.setBorderRadius(12)
        tl = QVBoxLayout(theme_card)
        tl.setContentsMargins(26, 20, 26, 20)
        tl.setSpacing(14)
        section = StrongBodyLabel("外观", theme_card)
        _style_text(section, letter=0.5)
        tl.addWidget(section)

        row1 = QHBoxLayout()
        row1.setSpacing(12)
        lbl = BodyLabel("主题模式", theme_card)
        self.themeCombo = ComboBox(theme_card)
        self.themeCombo.addItems(["跟随系统", "浅色", "深色"])
        self.themeCombo.setFixedWidth(160)
        self.themeCombo.currentIndexChanged.connect(self._on_theme_changed)
        self.themeCombo.setCurrentIndex(_saved_index(self._settings, "theme", 3))
        row1.addWidget(lbl)
        row1.addStretch(1)
        row1.addWidget(self.themeCombo)
        tl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.addWidget(BodyLabel("主题色", theme_card))
        row2.addStretch(1)
        self.accentCombo = ComboBox(theme_card)
        self.accentCombo.addItems([n for n, _ in _ACCENTS])
        self.accentCombo.setFixedWidth(160)
        self.accentCombo.currentIndexChanged.connect(self._on_accent_changed)
        self.accentCombo.setCurrentIndex(
            _saved_index(self._settings, "accent", len(_ACCENTS)))
        row2.addWidget(self.accentCombo)
        tl.addLayout(row2)
        self.vbox.addWidget(theme_card)

        # ---- 目录（可自定义）
        dir_card = SimpleCardWidget(self.view)
        dir_card.setBorderRadius(12)
        dl = QVBoxLayout(dir_card)
        dl.setContentsMargins(26, 20, 26, 20)
        dl.setSpacing(12)
        section = StrongBodyLabel("数据目录", dir_card)
        _style_text(section, letter=0.5)
        dl.addWidget(section)
        hint = CaptionLabel(
            "修改路径后点击「应用」生效，已有的日志和备份不会自动迁移。",
            dir_card)
        hint.setWordWrap(True)
        hint.setTextColor("#61666D", "#9AA3B2")
        _style_text(hint, line_height=1.7, letter=0.3)
        dl.addWidget(hint)

        self._custom_dir = self._settings.value("dataDir", "", type=str)

        self._dirEdits: dict[str, "LineEdit"] = {}
        for key, text, default in (
            ("logDir", "运行日志", sysutil.LOG_DIR),
            ("backupDir", "配置备份", sysutil.BACKUP_DIR),
        ):
            row = QHBoxLayout()
            row.setSpacing(10)
            name = BodyLabel(text, dir_card)
            name.setFixedWidth(84)
            _style_text(name, letter=0.3)
            row.addWidget(name)

            edit = LineEdit(dir_card)
            edit.setText(default if not self._custom_dir else
                         os.path.join(self._custom_dir, "logs" if key == "logDir" else "backups"))
            edit.setClearButtonEnabled(True)
            edit.setPlaceholderText(f"留空则使用默认路径：{default}")
            row.addWidget(edit, 1)
            self._dirEdits[key] = edit

            browse = TransparentToolButton(FIF.FOLDER, dir_card)
            browse.setToolTip("浏览选择文件夹")
            browse.clicked.connect(lambda _=False, k=key, e=edit: self._browse_dir(k, e))
            row.addWidget(browse)
            openBtn = TransparentToolButton(FIF.LINK, dir_card)
            openBtn.setToolTip("在资源管理器中打开当前目录")
            openBtn.clicked.connect(
                lambda _=False, e=edit: open_in_explorer(e.text() or default))
            row.addWidget(openBtn)
            dl.addLayout(row)

        applyRow = QHBoxLayout()
        applyRow.addStretch(1)
        applyBtn = PrimaryPushButton(FIF.SAVE, "应用路径设置", dir_card)
        applyBtn.setFixedHeight(32)
        applyBtn.clicked.connect(self._apply_custom_dirs)
        resetBtn = PushButton(FIF.REMOVE, "恢复默认", dir_card)
        resetBtn.setFixedHeight(32)
        resetBtn.clicked.connect(self._reset_dirs)
        applyRow.addWidget(applyBtn)
        applyRow.addWidget(resetBtn)
        dl.addLayout(applyRow)
        self.vbox.addWidget(dir_card)

        # ---- 开源许可
        lic_card = SimpleCardWidget(self.view)
        lic_card.setBorderRadius(12)
        ll = QVBoxLayout(lic_card)
        ll.setContentsMargins(26, 20, 26, 20)
        ll.setSpacing(12)
        section = StrongBodyLabel("开源许可", lic_card)
        _style_text(section, letter=0.5)
        ll.addWidget(section)
        lic = BodyLabel(
            f"{APP_COPYRIGHT}\n\n"
            "本程序为自由软件：你可以依据自由软件基金会发布的 GNU 通用公共许可证"
            "（第 3 版或任何更新版本）的条款重新发布或修改它。\n"
            "本程序基于「希望它有用」的目的发布，但不提供任何担保。\n\n"
            "界面基于 PySide6 (LGPLv3) 与 QFluentWidgets (GPLv3) 构建；"
            "对外分发时需一并提供完整源代码，仅自己使用则不受此约束。", lic_card)
        lic.setWordWrap(True)
        lic.setTextColor("#3B4250", "#C6CBD5")
        _style_text(lic, line_height=1.9, letter=0.3)
        ll.addWidget(lic)

        links = QHBoxLayout()
        links.setSpacing(8)
        for text, url in (
            ("QFluentWidgets", "https://qfluentwidgets.com"),
            ("GPLv3 全文", "https://www.gnu.org/licenses/gpl-3.0.html"),
            ("Qt for Python", "https://doc.qt.io/qtforpython/"),
        ):
            b = TransparentPushButton(FIF.LINK, text, lic_card)
            b.setFixedHeight(30)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(u))
            links.addWidget(b)
        links.addStretch(1)
        ll.addLayout(links)
        self.vbox.addWidget(lic_card)

        # ---- 免责声明
        warn_card = SimpleCardWidget(self.view)
        warn_card.setBorderRadius(12)
        wl = QVBoxLayout(warn_card)
        wl.setContentsMargins(26, 20, 26, 20)
        wl.setSpacing(12)
        section = StrongBodyLabel("使用须知", warn_card)
        _style_text(section, letter=0.5)
        wl.addWidget(section)
        warn = BodyLabel(
            "· 标记为「谨慎」的项目会清除自定义配置，执行前请确认；\n"
            "· 涉及协议栈的修复需要重启计算机才能完全生效；\n"
            "· 程序需要管理员权限才能修改系统网络配置；\n"
            "· 若修复后仍无法上网，多为运营商线路或路由器故障，请联系宽带客服。",
            warn_card)
        warn.setWordWrap(True)
        warn.setTextColor("#61666D", "#9AA3B2")
        _style_text(warn, line_height=1.9, letter=0.3)
        wl.addWidget(warn)
        self.vbox.addWidget(warn_card)

    def _copy_email(self) -> None:
        QApplication.clipboard().setText(APP_EMAIL)
        InfoBar.success(title="已复制", content=f"邮箱地址 {APP_EMAIL} 已复制到剪贴板",
                        orient=Qt.Horizontal, isClosable=True,
                        position=InfoBarPosition.TOP_RIGHT, duration=2500,
                        parent=self.window())

    def _browse_dir(self, key: str, edit) -> None:
        """弹出文件夹选择对话框。"""
        current = edit.text().strip()
        d = QFileDialog.getExistingDirectory(
            self.window(), "选择数据目录", current,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks)
        if d:
            edit.setText(d)

    def _apply_custom_dirs(self) -> None:
        """保存自定义数据目录并立即生效。"""
        log_path = self._dirEdits["logDir"].text().strip()
        bak_path = self._dirEdits["backupDir"].text().strip()

        # 检测是否指向同一个根目录
        if log_path and bak_path:
            log_root = os.path.dirname(log_path)
            bak_root = os.path.dirname(bak_path)
            if log_root != bak_root:
                InfoBar.warning(
                    title="路径不一致",
                    content="日志和备份的父目录应保持一致，建议只修改根目录后让子目录自动生成。",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT, duration=5000,
                    parent=self.window())
                return

        base = log_path or bak_path
        if base:
            self._custom_dir = os.path.dirname(base) if log_path else os.path.dirname(bak_path)
        else:
            self._custom_dir = ""

        # 保存到 QSettings
        self._settings.setValue("dataDir", self._custom_dir)
        self._settings.sync()

        # 动态更新 sysutil 模块的目录变量（热生效）。
        # 注意：engine / ui 均通过 sysutil.BACKUP_DIR 实时读取，
        # 不能在导入时 from ... import BACKUP_DIR 拷贝值，否则这里改了也不生效。
        if self._custom_dir:
            sysutil.DATA_DIR = self._custom_dir
            sysutil.LOG_DIR = os.path.join(self._custom_dir, "logs")
            sysutil.BACKUP_DIR = os.path.join(self._custom_dir, "backups")
        else:
            sysutil.DATA_DIR = sysutil._base_data_dir()
            sysutil.LOG_DIR = os.path.join(sysutil.DATA_DIR, "logs")
            sysutil.BACKUP_DIR = os.path.join(sysutil.DATA_DIR, "backups")

        sysutil.ensure_dirs()

        # 让备份页立即从新目录读取列表
        backup_page = getattr(self.window(), "backupPage", None)
        if backup_page is not None:
            backup_page.reload()

        InfoBar.success(
            title="已保存",
            content=f"数据目录已更新为 {sysutil.DATA_DIR}",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP_RIGHT, duration=4000,
            parent=self.window())

    def _reset_dirs(self) -> None:
        """恢复默认路径。"""
        self._custom_dir = ""
        self._settings.remove("dataDir")
        self._settings.sync()

        sysutil.DATA_DIR = sysutil._base_data_dir()
        sysutil.LOG_DIR = os.path.join(sysutil.DATA_DIR, "logs")
        sysutil.BACKUP_DIR = os.path.join(sysutil.DATA_DIR, "backups")
        sysutil.ensure_dirs()

        self._dirEdits["logDir"].setText(sysutil.LOG_DIR)
        self._dirEdits["backupDir"].setText(sysutil.BACKUP_DIR)

        backup_page = getattr(self.window(), "backupPage", None)
        if backup_page is not None:
            backup_page.reload()

        InfoBar.success(title="已恢复默认",
                       content=f"数据目录已恢复为 {sysutil.DATA_DIR}",
                       orient=Qt.Horizontal, isClosable=True,
                       position=InfoBarPosition.TOP_RIGHT, duration=3000,
                       parent=self.window())

    def _on_theme_changed(self, idx: int) -> None:
        setTheme([Theme.AUTO, Theme.LIGHT, Theme.DARK][idx])
        self._settings.setValue("theme", idx)

    def _on_accent_changed(self, idx: int) -> None:
        setThemeColor(_ACCENTS[idx][1])
        self._settings.setValue("accent", idx)


# ==================================================================== 主窗口

class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1080, 760)
        self.setMinimumSize(940, 640)

        # 云母(Mica)背景在部分 Qt 版本 / 系统组合下会让窗口渲染成透明而「看不见」。
        # 为保证「双击一定能看到窗口」，默认关闭；如需恢复云母效果，
        # 把下方环境变量设为 1 即可：NETREPAIR_MICA=1
        if os.environ.get("NETREPAIR_MICA") == "1":
            try:
                self.setMicaEffectEnabled(True)
            except Exception:  # noqa: BLE001
                pass

        self.repairPage = RepairInterface(self)
        self.diagnosePage = DiagnoseInterface(self)
        self.logPage = LogInterface(self)
        self.backupPage = BackupInterface(self)
        self.aboutPage = AboutInterface(self)

        self.addSubInterface(self.repairPage, FIF.BROOM, "一键修复")
        self.addSubInterface(self.diagnosePage, FIF.WIFI, "网络诊断")
        self.addSubInterface(self.logPage, FIF.HISTORY, "运行日志")
        self.addSubInterface(self.backupPage, FIF.FOLDER, "备份还原")
        self.addSubInterface(self.aboutPage, FIF.INFO, "关于",
                             NavigationItemPosition.BOTTOM)

        self.navigationInterface.setExpandWidth(200)
        self.navigationInterface.setCollapsible(True)

        # 诊断页 -> 修复页 联动
        self.diagnosePage.suggestionsReady.connect(self._apply_suggestions)

        # 日志桥接
        self.bridge = LogBridge()
        self.bridge.line.connect(self.logPage.append)
        LOGGER.add_sink(lambda line, level: self.bridge.line.emit(line, level))

        qconfig.themeChanged.connect(self._on_theme_changed)
        qconfig.themeColorChanged.connect(self._on_theme_color_changed)

        self._center()
        QTimer.singleShot(400, self._greet)

    # ---------------------------------------------------------------- 辅助
    def _center(self) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  geo.center().y() - self.height() // 2)

    def _apply_suggestions(self, keys: list) -> None:
        for c in self.repairPage.cards.values():
            c.setChecked(False)
        hit = 0
        for k in keys:
            card = self.repairPage.cards.get(k)
            if card:
                card.setChecked(True)
                hit += 1
        self.switchTo(self.repairPage)
        InfoBar.success(
            title="已自动勾选", content=f"根据诊断结果勾选了 {hit} 个修复项，确认后点击「开始修复」",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP_RIGHT, duration=5000, parent=self)

    def _on_theme_changed(self, *_args) -> None:
        for page in (self.repairPage, self.diagnosePage, self.backupPage):
            if hasattr(page, "refreshTheme"):
                page.refreshTheme()

    def _on_theme_color_changed(self, color: QColor) -> None:
        """主题色切换时刷新所有使用主题色的自定义元素。"""
        for page in (self.repairPage, self.diagnosePage, self.backupPage):
            if hasattr(page, "refreshTheme"):
                page.refreshTheme()

    def _greet(self) -> None:
        if is_admin():
            InfoBar.success(
                title="已获取管理员权限",
                content="可以执行全部修复项目。建议先做一次「网络诊断」再针对性修复。",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=5000, parent=self)
        else:
            InfoBar.warning(
                title="当前不是管理员权限",
                content="部分修复项会失败，建议右键以管理员身份重新运行本程序。",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=8000, parent=self)

    def closeEvent(self, event) -> None:  # noqa: N802
        worker = self.repairPage.worker
        if worker and worker.isRunning():
            box = MessageBox("修复尚未完成",
                             "正在执行修复任务，强行关闭可能导致网络配置处于中间状态。\n\n"
                             "确定要退出吗？", self)
            box.yesButton.setText("强制退出")
            box.cancelButton.setText("继续等待")
            if not box.exec():
                event.ignore()
                return
            worker.abort()
            worker.wait(3000)
        # 诊断线程只读不改配置，无需询问；但退出前需等待其结束，
        # 避免 QThread 仍在运行时被销毁导致进程崩溃
        for diag_worker in (self.repairPage.diagWorker, self.diagnosePage.worker):
            if diag_worker and diag_worker.isRunning():
                diag_worker.wait(3000)
        LOGGER.info("===== 程序退出 =====")
        super().closeEvent(event)


# ==================================================================== 入口

def run_app() -> int:
    if hasattr(Qt, "AA_DontCreateNativeWidgetSiblings"):
        QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())

    # 全局字体：拉丁文用 Segoe UI，中文回退到更精致的雅黑 / 苹方 / 思源黑体
    app_font = QFont()
    app_font.setFamilies([
        "Segoe UI", "Microsoft YaHei UI", "PingFang SC",
        "Source Han Sans SC", "Noto Sans CJK SC", "微软雅黑",
    ])
    app_font.setPointSize(10)
    app_font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(app_font)

    # 恢复用户上次选择的主题与主题色（保存在 QSettings），避免每次启动被重置
    settings = QSettings("NetRepair", "NetRepair")
    setTheme([Theme.AUTO, Theme.LIGHT, Theme.DARK][_saved_index(settings, "theme", 3)])
    setThemeColor(_ACCENTS[_saved_index(settings, "accent", len(_ACCENTS))][1])

    window = MainWindow()
    window.show()
    return app.exec()
