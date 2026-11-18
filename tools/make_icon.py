"""Creates src/bmpe/resources/icon.ico (Windows) and icon.png (Linux), once before building."""

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath

RES = Path(__file__).resolve().parents[1] / "src" / "bmpe" / "resources"
# free font (Bitstream Vera license, see fonts/LICENSE-DejaVu.txt), shipped so the icon looks the same everywhere
FONT_FILE = Path(__file__).resolve().parent / "fonts" / "DejaVuSans-Bold.ttf"


def render(size: int, family: str) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    grad = QLinearGradient(r.topLeft(), r.bottomRight())
    grad.setColorAt(0, QColor("#2b88d8"))
    grad.setColorAt(1, QColor("#0f5aa8"))
    path = QPainterPath()
    path.addRoundedRect(r, size * 0.2, size * 0.2)
    p.fillPath(path, grad)
    # hint of a film strip
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 60))
    hole, step, count = size * 0.1, size * 0.2, 4
    first = r.center().x() - ((count - 1) * step + hole) / 2  # centred horizontally
    for i in range(count):
        x = first + i * step
        p.drawRoundedRect(QRectF(x, r.top() + size * 0.1, size * 0.1, size * 0.08), 2, 2)
        p.drawRoundedRect(QRectF(x, r.bottom() - size * 0.18, size * 0.1, size * 0.08), 2, 2)
    p.setPen(QColor("white"))
    f = QFont(family)
    f.setPixelSize(max(1, int(size * 0.30)))
    f.setBold(True)
    p.setFont(f)
    p.drawText(r, Qt.AlignCenter, "MKV")
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    font_id = QFontDatabase.addApplicationFont(str(FONT_FILE))
    if font_id < 0:
        sys.exit(f"Cannot load {FONT_FILE}")
    family = QFontDatabase.applicationFontFamilies(font_id)[0]
    RES.mkdir(parents=True, exist_ok=True)
    img = render(256, family)
    for name, fmt in (("icon.ico", "ICO"), ("icon.png", "PNG")):
        out = RES / name
        print(out, "ok" if img.save(str(out), fmt) else "ERROR")
