"""悬停动画基础设施。

为什么不用 QSS 的 transition
-----------------------------
Qt Style Sheets 只实现了 CSS2.1 的一个子集，**不支持 `transition` / `animation`**，
写了会被解析器静默丢弃。想要平滑过渡只能靠 QPropertyAnimation 驱动。

为什么不用 QGraphicsDropShadowEffect
------------------------------------
挂载图形效果会强制该控件（及其全部子控件）先渲染到一张离屏 QPixmap 再合成，
悬停期间每帧都要重来一次；频繁 setGraphicsEffect() 还会让 Qt 删除旧 effect 的
C++ 对象，Python 侧残留引用一访问就抛 RuntimeError。因此这里完全不用它。

为什么不用动画改 contentsMargins / geometry
-------------------------------------------
改变尺寸相关属性会让 sizeHint 失效 → 触发父布局重排 → 列表里全部卡片重新布局，
这正是"悬停卡顿"的根因。本模块只动**颜色**，纯 paintEvent 重绘，
且 update() 只脏本控件矩形，不波及兄弟节点。

核心做法
--------
暴露一个真正的 Qt Property `hoverProgress`（0.0~1.0），由 QPropertyAnimation
以 OutCubic 缓动驱动；paintEvent 里按该进度对颜色做线性插值后自绘圆角背景。
"""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton

# 统一动效参数
HOVER_MS = 160          # 悬停淡入淡出时长（稍慢一点更优雅）
PRESS_MS = 100          # 按下反馈时长（更快，保证"跟手"）
EASING = QEasingCurve.Type.OutCubic


def lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    """在两个颜色间做线性插值（含 alpha 通道）。"""
    if t <= 0.0:
        return QColor(a)
    if t >= 1.0:
        return QColor(b)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def c(spec: str) -> QColor:
    """'#RRGGBB' / 'transparent' -> QColor。"""
    if spec == "transparent":
        return QColor(0, 0, 0, 0)
    return QColor(spec)


class HoverAnimMixin:
    """给任意 QWidget 提供 hoverProgress / pressProgress 两条动画轨道。

    使用方式：子类在 __init__ 末尾调用 self._init_hover_anim()，
    并在 paintEvent 中读取 self._hp / self._pp 做颜色插值。
    """

    def _init_hover_anim(self) -> None:
        self._hp = 0.0          # hover progress
        self._pp = 0.0          # press progress
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        # 动画对象复用，避免每次悬停都 new 一个（GC 压力 + C++ 生命周期陷阱）
        self._hover_anim = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_anim.setDuration(HOVER_MS)
        self._hover_anim.setEasingCurve(EASING)

        self._press_anim = QPropertyAnimation(self, b"pressProgress", self)
        self._press_anim.setDuration(PRESS_MS)
        self._press_anim.setEasingCurve(EASING)

    # ---------------- Qt Property：必须是 Property() 而非 @property ----------------
    # QPropertyAnimation 走元对象系统查找属性，Python 的 @property 它看不见，
    # 用 @property 会导致动画静默空转（值永远不变）。

    def _get_hp(self) -> float:
        return self._hp

    def _set_hp(self, v: float) -> None:
        if abs(v - self._hp) < 0.004:   # 小于 1/255 的变化肉眼不可见，跳过重绘
            return
        self._hp = v
        self.update()                   # 只脏本控件

    def _get_pp(self) -> float:
        return self._pp

    def _set_pp(self, v: float) -> None:
        if abs(v - self._pp) < 0.004:
            return
        self._pp = v
        self.update()

    hoverProgress = Property(float, _get_hp, _set_hp)
    pressProgress = Property(float, _get_pp, _set_pp)

    # ---------------- 驱动 ----------------
    def _animate(self, anim: QPropertyAnimation, current: float, target: float) -> None:
        if abs(current - target) < 0.001:
            return
        anim.stop()
        anim.setStartValue(current)     # 从当前值起步 → 快速来回移动时可平滑反向
        anim.setEndValue(target)
        anim.start()

    def _set_hovered(self, on: bool) -> None:
        if not self.isEnabled():
            on = False
        self._animate(self._hover_anim, self._hp, 1.0 if on else 0.0)

    def _set_pressed(self, on: bool) -> None:
        self._animate(self._press_anim, self._pp, 1.0 if on else 0.0)


class BtnStyle:
    """一组按钮配色。"""

    __slots__ = ("bg", "bg_hover", "bg_press", "border", "border_dis", "bg_dis", "radius")

    def __init__(self, bg, bg_hover, bg_press, border="transparent",
                 border_dis="transparent", bg_dis="transparent", radius=8):
        self.bg = c(bg)
        self.bg_hover = c(bg_hover)
        self.bg_press = c(bg_press)
        self.border = c(border)
        self.border_dis = c(border_dis)
        self.bg_dis = c(bg_dis)
        self.radius = radius


# 按 objectName 索引的配色表。键与 theme.py 中的 QSS 选择器一一对应。
BTN_STYLES: dict[str, BtnStyle] = {
    "primaryBtn": BtnStyle("#7B8BBE", "#95A5CC", "#5E70AD",
                           bg_dis="#B8B5CA", radius=8),
    "ghostBtn":   BtnStyle("#FFFFFF", "#F6F3EE", "#EDE7DD",
                           border="#7B8BBE", border_dis="#DDD8CD",
                           bg_dis="#FFFFFF", radius=8),
    "smallBtn":   BtnStyle("#FFFFFF", "#F4F1EA", "#E8E2D6",
                           border="#BFB6A8", border_dis="#EEE9DE",
                           bg_dis="#FFFFFF", radius=7),
    "navBtn":     BtnStyle("transparent", "#EEE8DE", "#E2DBCE",
                           radius=8),   # 圆角悬停背景，与侧边栏柔和感一致
    "winBtn":     BtnStyle("transparent", "#EBE6DC", "#DFD9CE", radius=6),
    # 关闭键用极淡的柔红底
    "winClose":   BtnStyle("transparent", "#FAEEEE", "#F5EAEA", radius=6),
    "linkBtn":    BtnStyle("transparent", "transparent", "transparent", radius=0),
}

# navBtn 选中态——淡薰衣草色
NAV_CHECKED = BtnStyle("#EEEBF4", "#E4DFE8", "#D8D3DC", radius=8)


class AnimatedButton(QPushButton, HoverAnimMixin):
    """自绘背景的按钮，悬停/按下均为平滑过渡。

    与 QSS 的分工：QSS 只负责字体、文字颜色、内边距；
    背景与边框由本类在 paintEvent 中按动画进度自绘
    （theme.py 里对应选择器已设为 background: transparent; border: none）。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_hover_anim()

    # ------------- 事件 -------------
    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self._set_hovered(True)

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self._set_hovered(False)
        self._set_pressed(False)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_pressed(True)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self._set_pressed(False)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        # 变为禁用时立即收起悬停态，避免"禁用了还亮着"
        if event.type() == event.Type.EnabledChange and not self.isEnabled():
            self._hover_anim.stop()
            self._press_anim.stop()
            self._hp = 0.0
            self._pp = 0.0
            self.update()

    # ------------- 绘制 -------------
    def _style(self) -> BtnStyle | None:
        name = self.objectName()
        if name == "navBtn" and self.isChecked():
            return NAV_CHECKED
        return BTN_STYLES.get(name)

    def paintEvent(self, event) -> None:  # noqa: N802
        st = self._style()
        if st is not None and st.radius >= 0:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            if not self.isEnabled():
                bg, border = st.bg_dis, st.border_dis
            else:
                bg = lerp_color(st.bg, st.bg_hover, self._hp)
                if self._pp > 0.0:
                    bg = lerp_color(bg, st.bg_press, self._pp)
                border = st.border

            rect = QRectF(self.rect())
            if border.alpha():
                rect = rect.adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(rect, st.radius, st.radius)

            if bg.alpha():
                p.fillPath(path, bg)
            if border.alpha():
                p.strokePath(path, QPen(border, 1.0))
            p.end()

        # 交给 QSS 样式引擎绘制图标与文字（背景已设为 transparent，不会覆盖）
        super().paintEvent(event)
