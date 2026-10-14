"""Génère assets/icon.ico (dessiné avec Qt, aucune dépendance)."""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen

app = QGuiApplication(sys.argv)
size = 256
img = QImage(size, size, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
p.setBrush(QColor("#1F3A5F"))
p.setPen(Qt.NoPen)
p.drawRoundedRect(QRectF(8, 8, 240, 240), 48, 48)
# feuille d'avis
p.setBrush(QColor("white"))
p.drawRoundedRect(QRectF(64, 40, 128, 168), 12, 12)
p.setPen(QPen(QColor("#9FB2C9"), 10, Qt.SolidLine, Qt.RoundCap))
for y in (84, 112, 140):
    p.drawLine(88, y, 168, y)
# pastille « tampon »
p.setPen(Qt.NoPen)
p.setBrush(QColor("#E8772E"))
p.drawEllipse(QRectF(140, 140, 92, 92))
p.setPen(QColor("white"))
f = QFont("Segoe UI", 44, QFont.Bold)
p.setFont(f)
p.drawText(QRectF(140, 136, 92, 92), Qt.AlignCenter, "€")
p.end()
out = Path(__file__).resolve().parent.parent / "assets"
out.mkdir(exist_ok=True)
img.save(str(out / "icon.ico"))
img.save(str(out / "icon.png"))
print("ok", out)
