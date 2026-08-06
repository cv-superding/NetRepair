"""界面配色与样式表 —— 莫奈印象派风格（Monet Impressionist Theme）

设计灵感
--------
取自克劳德·莫奈的调色板：睡莲池的淡紫倒影、干草堆在暮光中的玫瑰金、
鲁昂大教堂薄雾中的灰蓝、罂粟花田的柔和红绿。
整体追求：低饱和度、暖底色、朦胧边界、如画般的宁静感。

色彩原则
--------
  · 一切颜色都带微暖底调（yellow-bias），拒绝冷峻的纯蓝/纯灰
  · 饱和度控制在 15~35% 之间，模拟油画颜料在画布上的调和效果
  · 相邻色相差 ≤ 20° 色相，避免刺眼的对比冲突
  · 边框用极淡的暖灰，让组件像"浮"在背景上而非硬切割

关于动画的重要说明
------------------
Qt Style Sheets **不支持 CSS 的 `transition` / `animation` 属性**，
写进 QSS 会被解析器静默丢弃。所有平滑过渡由 `netfix/anim.py` 的
QPropertyAnimation 驱动（见该文件文档）。

因此下列选择器的 background / border 被刻意设为透明或省略，
交由 Python 侧按动画进度逐帧绘制；QSS 只保留字体、文字颜色、内边距等
不参与动画的静态属性。改配色时请同步 anim.py 与 ui.py 的自绘常量。
"""

# ==========================================================================
# 莫奈调色板 —— 每个颜色都像从印象派画作中提取的
# ==========================================================================
C = {
    # ---- 主色系：睡莲池倒影的淡紫蓝 ----
    "primary":        "#7B8BBE",       # 薄雾中的灰蓝（主操作色）
    "primary_hover":  "#95A5CC",       # 稍亮一点的雾蓝
    "primary_press":  "#5E70AD",       # 加深的暮色蓝
    "primary_soft":   "#EEEBF4",       # 极淡的薰衣草底
    "primary_ultra":  "#F5F2F8",       # 几乎不可见的淡紫

    # ---- 语义色：莫奈花园的低饱和版本 ----
    "success":        "#7A9E82",       # 睡莲叶的灰绿
    "success_soft":   "#EDF5EF",       # 极淡绿底
    "warning":        "#C49A6C",       # 干草堆的金棕
    "warning_soft":   "#FDF6ED",       # 极淡金底
    "danger":         "#C47D7D",       # 罂粟花的柔红
    "danger_soft":    "#FCEDED",       # 极淡玫红底

    # ---- 背景层：画布与画框的层次 ----
    "bg_base":        "#F2EDE5",       # 最底层——泛黄的画布
    "bg_sidebar":     "#F7F3EC",       # 侧栏——温暖的象牙白
    "bg_content":     "#FCFAF7",       # 内容区——近乎白的暖底
    "bg_card_hover":  "#F8F4EE",       # 卡片悬停——极淡的暖灰
    "bg_input":       "#F3EFE8",       # 输入区

    # ---- 边界：朦胧如水彩边缘 ----
    "border":         "#E2DACE",       # 暖灰边框（几乎不可见）
    "border_light":   "#EAe5DC",       # 更淡的分隔线
    "border_focus":   "#7B8BBE",       # 聚焦时用主色

    # ---- 文字：墨与炭的温暖版本 ----
    "text":           "#2D2A26",       # 温暖的黑（非纯黑）
    "text_sub":       "#6B665C",       # 暖褐灰
    "text_dim":       "#A09588",       # 泛黄的中性灰
    "text_on_primary":"#FFFFFF",

    # ---- 侧边栏 ----
    "sidebar":        "#F7F3EC",
    "sidebar_hover":  "#EEE8DE",
    "sidebar_active": "#EEEBF4",       # 选中带一丝淡紫
}

# 字体：衬线感 + 可读性的平衡
FONT = '"Segoe UI Variable", "Microsoft YaHei UI", "PingFang SC", sans-serif'
FONT_MONO = '"Cascadia Mono", "Consolas", "Menlo", monospace'

# ==========================================================================
# 全局样式表 —— 如水彩般轻盈
# ==========================================================================
QSS = f"""
* {{
    font-family: {FONT};
    outline: none;
}}

/* ==================== 标题栏 —— 画框上沿 ==================== */
#titleBar {{
    background: #FCFAF7;
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
    border-bottom: 1px solid {C['border_light']};
}}
#titleText {{
    font-size: 14px;
    font-weight: 700;
    color: {C['text']};
    letter-spacing: 0.4px;
}}
#adminBadge {{
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 10px;
    background: {C['success_soft']};
    color: {C['success']};
    font-weight: 500;
}}
#adminBadgeWarn {{
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 10px;
    background: {C['warning_soft']};
    color: {C['warning']};
    font-weight: 500;
}}
QPushButton#winBtn, QPushButton#winClose {{
    border: none; background: transparent;
}}

/* ==================== 侧边栏 —— 画框左侧 ==================== */
#sidebar {{
    background: {C['sidebar']};
    /* 左下随窗口圆角；右侧与内容区无硬分割线，自然融合 */
    border-bottom-left-radius: 14px;
}}

/* ==================== 内容区 —— 浮于画布之上的圆角面板 ==================== */
/* 包一层圆角面板：与窗口底色同为 #FCFAF7，
   圆角处被裁掉后透出的是窗口底色（同色），故与窗口圆角无缝衔接；
   左侧与侧边栏分界线相交处亦呈圆角，呼应「分界点也要圆角」。 */
#contentPanel {{
    background: {C['bg_content']};
    border-radius: 14px;
}}
QPushButton#navBtn {{
    border: none; background: transparent; text-align: left;
    padding: 0 16px 0 18px; font-size: 13.5px;
    color: {C['text_sub']}; font-weight: 400;
    border-left: 3px solid transparent; border-radius: 8px;
}}
QPushButton#navBtn:hover {{ color: {C['text']}; background: {C['sidebar_hover']}; }}
QPushButton#navBtn:checked {{
    color: {C['primary']}; font-weight: 600;
    background: {C['sidebar_active']};
    border-left-color: {C['primary']};
}}

/* ==================== 卡片 —— 浮于画布之上 ==================== */
#statusCard, #card {{
    background: {C['bg_content']};
    border: 1px solid {C['border']};
    border-radius: 12px;
}}
#statusTitle {{
    font-size: 17px; font-weight: 700; color: {C['text']};
}}
#statusDesc {{
    font-size: 12.5px; color: {C['text_sub']}; line-height: 1.5;
}}
#sectionTitle {{
    font-size: 15px; font-weight: 700; color: {C['text']};
    letter-spacing: 0.4px;
}}
#hintText {{
    font-size: 12px; color: {C['text_dim']}; line-height: 1.4;
}}

/* ==================== 修复项卡片（背景/边框由 paintEvent 自绘）*/
#itemName {{
    font-size: 13.5px; font-weight: 600; color: {C['text']};
}}
#itemDesc {{
    font-size: 12px; color: {C['text_sub']}; line-height: 1.45;
}}
#itemNote {{
    font-size: 11.5px; color: {C['warning']}; line-height: 1.35;
}}
#riskSafe {{
    font-size: 11px; padding: 2px 8px; border-radius: 10px;
    background: {C['success_soft']}; color: {C['success']}; font-weight: 500;
}}
#riskMedium {{
    font-size: 11px; padding: 2px 8px; border-radius: 10px;
    background: {C['primary_soft']}; color: {C['primary']}; font-weight: 500;
}}
#riskHigh {{
    font-size: 11px; padding: 2px 8px; border-radius: 10px;
    background: {C['warning_soft']}; color: {C['warning']}; font-weight: 500;
}}
#stateIdle   {{ font-size: 12px; color: {C['text_dim']}; }}
#stateRunning{{ font-size: 12px; color: {C['primary']}; font-weight: 600; }}
#stateOk     {{ font-size: 12px; color: {C['success']}; font-weight: 600; }}
#stateFail   {{ font-size: 12px; color: {C['danger']}; font-weight: 600; }}

/* ==================== 按钮（背景由 AnimatedButton 自绘）*/
QPushButton#primaryBtn {{
    background: transparent; color: #FFFFFF; border: none;
    font-size: 13.5px; font-weight: 600; padding: 0 22px;
    letter-spacing: 0.3px;
}}
QPushButton#primaryBtn:disabled {{ color: #C5CBE5; }}

QPushButton#ghostBtn {{
    background: transparent; color: {C['primary']}; border: none;
    font-size: 13.5px; font-weight: 500; padding: 0 18px;
}}
QPushButton#ghostBtn:disabled {{ color: #B8BAC8; }}

QPushButton#smallBtn {{
    background: transparent; color: {C['primary']}; border: none;
    font-size: 12.5px; font-weight: 500; padding: 0 14px;
}}
QPushButton#smallBtn:disabled {{ color: {C['text_dim']}; }}

QPushButton#linkBtn {{
    background: transparent; border: none; color: {C['primary']};
    font-size: 12.5px; font-weight: 500; padding: 0 4px;
}}
QPushButton#linkBtn:hover {{ color: {C['primary_hover']}; text-decoration: underline; }}

/* ==================== 复选框 ==================== */
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 1.5px solid #D0C9BC; background: {C['bg_content']};
}}
QCheckBox::indicator:hover {{ border-color: {C['primary']}; }}
QCheckBox::indicator:checked {{
    background: {C['primary']}; border-color: {C['primary']};
    image: url("__CHECK_ICON__");
}}
QCheckBox::indicator:disabled {{ background: #F0EDE6; border-color: #DDD8CD; }}
QCheckBox::indicator:checked:disabled {{ background: #B8B5CA; border-color: #B8B5CA; }}

/* ==================== 进度条 —— 柔和渐变 ==================== */
QProgressBar {{
    border: none; border-radius: 5px;
    background: #E6E0D5; height: 6px;
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{
    border-radius: 5px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {C['primary']}, stop:1 {C['primary_hover']});
}}

/* ==================== 滚动条 —— 隐形处理 ==================== */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    border: none; background: transparent; width: 8px;
    margin: 2px 2px 2px 0;
}}
QScrollBar::handle:vertical {{
    background: #D4CCC0; border-radius: 4px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: #C2B8AA; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

/* ==================== 日志终端 —— 暖色调暗色主题 ==================== */
QPlainTextEdit#logView {{
    background: #252220; color: #D0CBC3; border: none;
    border-radius: 10px; font-family: {FONT_MONO}; font-size: 12px;
    padding: 12px; selection-background-color: #4A4660;
    line-height: 1.4;
}}

/* ==================== 关于页面 ==================== */
QLabel#aboutText {{
    font-size: 13px; color: {C['text_sub']}; line-height: 1.7;
}}
"""
