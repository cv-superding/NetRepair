"""构建期：把程序主图标预处理成透明 PNG 并改写 netfix/icons.py。

背景：icons.py 内嵌的是 JPG（无透明通道），运行时用纯 Python 逐像素去白底
（约 1.3s，是启动慢的主因）。本脚本在构建期用 PIL+numpy 把去白底做好
（毫秒级），替换成带 alpha 的 PNG base64，运行时只解码+缩放。

用法：invest-agent venv 的 python gen_icon_b64.py
"""
import base64
import io
import re

import numpy as np
from PIL import Image

SRC = "assets/app-icon-source.png"
TARGET = "netfix/icons.py"
PREVIEW = "assets/icon_preview_whitekey.png"
THRESHOLD = 240
OUT_SIZE = 512


def white_key(img: Image.Image) -> Image.Image:
    """与旧运行时逻辑一致：RGB 均 >240 的像素按 (avg-240)/15 渐变透明。"""
    a = np.asarray(img.convert("RGBA")).astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    avg = (r + g + b) / 3.0
    mask = (r > THRESHOLD) & (g > THRESHOLD) & (b > THRESHOLD)
    alpha = np.full_like(avg, 255.0)
    alpha[mask] = np.clip((avg[mask] - THRESHOLD) / (255 - THRESHOLD), 0.0, 1.0) * 255.0
    a[..., 3] = alpha
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def main() -> None:
    src = Image.open(SRC)
    assert src.size == (1024, 1024), f"源图尺寸异常: {src.size}"
    out = white_key(src).resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)

    out.save(PREVIEW)
    print(f"[icon] 预览已保存: {PREVIEW}")

    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    print(f"[icon] PNG base64 长度: {len(b64)} 字符 ({len(buf.getvalue())//1024} KB)")

    text = open(TARGET, encoding="utf-8").read()
    new_text, n1 = re.subn(
        r"(_APP_ICON_B64: str = )'[^']*'",
        lambda m: m.group(1) + "'" + b64 + "'",
        text,
        count=1,
    )
    if n1 != 1:
        raise RuntimeError("未找到 _APP_ICON_B64 定义")

    new_func = '''def app_icon_pixmap(size: int = 128) -> QPixmap:
    """程序主图标：从内嵌 base64 解码、缩放（透明通道已在构建期处理好，运行时零像素循环）。"""
    raw = _base64.b64decode(_APP_ICON_B64)
    src = QPixmap()
    if not src.loadFromData(raw, "PNG"):
        return QPixmap(size, size)
    if not hasattr(app_icon_pixmap, "_cache"):
        app_icon_pixmap._cache = src  # type: ignore[attr-defined]
    return app_icon_pixmap._cache.scaled(  # type: ignore[attr-defined]
        size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


'''
    start = new_text.index("def app_icon_pixmap")
    end = new_text.index("def app_icon(")
    new_text = new_text[:start] + new_func + new_text[end:]

    open(TARGET, "w", encoding="utf-8").write(new_text)
    print(f"[icon] 已改写 {TARGET}")


if __name__ == "__main__":
    main()
