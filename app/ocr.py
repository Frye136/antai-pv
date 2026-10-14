"""Lecture du texte des pages : couche texte du PDF si présente, sinon OCR Windows (moteur intégré, fr-FR).

Scans « biscornus » : avant l'OCR, l'image est rendue à au moins 300 dpi (les scans plus faibles sont agrandis),
le contraste est renforcé, une page tournée (90° / 180°) est remise à l'endroit et une page penchée est redressée
d'après l'angle mesuré par le moteur Windows. La lecture qui trouve le plus d'informations utiles est conservée.
"""
import asyncio
import io
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pymupdf
from PIL import Image, ImageFilter, ImageOps

MIN_TEXT_CHARS = 60
MIN_DPI = 300           # en dessous, les caractères sont trop petits pour le moteur Windows
MAX_DPI = 400
MAX_PIXELS = 9500       # limite du moteur Windows : 10 000 px sur le plus grand côté
DESKEW_MIN_ANGLE = 0.4  # degrés
GOOD_SCORE = 12         # au-delà, inutile d'essayer d'autres orientations


@dataclass
class PageOcr:
    text: str
    rotation: int = 0     # rotation appliquée pour remettre la page à l'endroit (0, 90, 180, 270)
    angle: float = 0.0    # inclinaison corrigée (degrés)
    score: float = 0.0


def _ocr_image(img: Image.Image) -> tuple[str, float]:
    """OCR Windows d'une image PIL. Renvoie (texte, angle d'inclinaison mesuré)."""
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png = buf.getvalue()

    async def run() -> tuple[str, float]:
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(png)
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_language(Language("fr-FR")) \
            or OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError("Aucun moteur OCR Windows disponible (installez le pack de langue Français).")
        result = await engine.recognize_async(bitmap)
        return "\n".join(line.text for line in result.lines), float(result.text_angle or 0.0)

    # Exécuté dans un thread dédié : sur le thread graphique (COM en mode STA) l'attente WinRT bloquerait.
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, run()).result(timeout=120)


def _score(text: str) -> float:
    """Indice de qualité d'une lecture : présence des éléments attendus sur un avis."""
    low = text.lower()
    s = min(len(text), 4000) / 1000
    s += 3 if re.search(r"(?<!\d)\d{10}(?!\d)", text) else 0
    s += 2 * min(len(re.findall(r"\d{2}/\d{2}/\d{4}", text)), 3)
    s += 2 if re.search(r"\b[A-Z]{2}-\d{3}-[A-Z]{2}\b", text) else 0
    s += sum(2 for kw in ("contravention", "infraction", "immatriculation", "amende", "représentant") if kw in low)
    return s


def _source_dpi(page: "pymupdf.Page") -> float:
    """Résolution de l'image scannée contenue dans la page (0 si aucune)."""
    best = 0.0
    for im in page.get_images(full=True):
        w, h = im[2], im[3]
        best = max(best, w / max(page.rect.width / 72, 0.1), h / max(page.rect.height / 72, 0.1))
    return best


def _complete(text: str) -> bool:
    """Lecture jugée complète : n° d'avis, plaque et au moins trois dates lisibles."""
    return bool(re.search(r"(?<!\d)\d{10}(?!\d)", text) and re.search(r"\b[A-Z]{2}-\d{3}-[A-Z]{2}\b", text)
                and len(re.findall(r"\d{2}/\d{2}/\d{4}", text)) >= 3)


def render(page: "pymupdf.Page", enhance: bool = True) -> Image.Image:
    """Image en niveaux de gris prête pour l'OCR : résolution remontée à 300 dpi minimum, contraste renforcé.
    `enhance=False` : rendu brut à 300 dpi (seconde lecture quand la première est incomplète)."""
    if not enhance:
        pix = page.get_pixmap(dpi=MIN_DPI, colorspace=pymupdf.csGRAY)
        return Image.frombytes("L", (pix.width, pix.height), pix.samples)
    src = _source_dpi(page)
    dpi = min(max(src or MIN_DPI, MIN_DPI), MAX_DPI)
    longest = max(page.rect.width, page.rect.height) / 72
    dpi = min(dpi, MAX_PIXELS / longest)
    pix = page.get_pixmap(dpi=int(dpi), colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    img = ImageOps.autocontrast(img, cutoff=1)
    if src and src < MIN_DPI * 0.9:  # scan basse résolution agrandi : on rend les contours plus nets
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))
    return img


def _fit(img: Image.Image) -> Image.Image:
    if max(img.size) <= MAX_PIXELS:
        return img
    ratio = MAX_PIXELS / max(img.size)
    return img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)


def analyse(page: "pymupdf.Page") -> PageOcr:
    """OCR robuste d'une page scannée (orientation + redressement + amélioration d'image)."""
    img = render(page)
    text, angle = _ocr_image(img)
    best = PageOcr(text, 0, 0.0, _score(text))
    best_img, best_angle = img, angle

    # Page tournée ou à l'envers : on essaie les autres orientations si la lecture est pauvre
    if best.score < GOOD_SCORE:
        for rot, op in ((180, Image.ROTATE_180), (90, Image.ROTATE_270), (270, Image.ROTATE_90)):
            cand_img = img.transpose(op)
            t, a = _ocr_image(cand_img)
            sc = _score(t)
            if sc > best.score + 2:
                best, best_img, best_angle = PageOcr(t, rot, 0.0, sc), cand_img, a
            if best.score >= GOOD_SCORE:
                break

    # Page penchée : redressement d'après l'angle mesuré par le moteur, conservé s'il améliore la lecture
    if abs(best_angle) >= DESKEW_MIN_ANGLE:
        straight = _fit(best_img.rotate(best_angle, resample=Image.BICUBIC, expand=True, fillcolor=255))
        t, _ = _ocr_image(straight)
        sc = _score(t)
        if sc >= best.score:
            best = PageOcr(t, best.rotation, best_angle, sc)

    # Lecture incomplète : seconde lecture sur un rendu brut (l'OCR ne se trompe pas aux mêmes endroits)
    if not _complete(best.text):
        raw = render(page, enhance=False)
        if best.rotation:
            raw = raw.transpose({180: Image.ROTATE_180, 90: Image.ROTATE_270, 270: Image.ROTATE_90}[best.rotation])
        if abs(best.angle) >= DESKEW_MIN_ANGLE:
            raw = _fit(raw.rotate(best.angle, resample=Image.BICUBIC, expand=True, fillcolor=255))
        t, _ = _ocr_image(raw)
        sc = _score(t)
        if sc > best.score:
            best = PageOcr(t, best.rotation, best.angle, sc)
    return best


def read_page(page: "pymupdf.Page", force_ocr: bool = False) -> PageOcr:
    """Texte natif du PDF s'il existe, sinon OCR robuste."""
    if not force_ocr:
        txt = page.get_text("text") or ""
        if len(txt.strip()) >= MIN_TEXT_CHARS:
            return PageOcr(txt)
    return analyse(page)


def page_text(page: "pymupdf.Page", force_ocr: bool = False) -> str:
    return read_page(page, force_ocr).text


def open_as_pdf(path: str) -> "pymupdf.Document":
    """Ouvre un PDF ou une image (jpg/png/tif, multi-pages) sous forme de document PDF."""
    doc = pymupdf.open(path)
    if doc.is_pdf:
        return doc
    pdf = pymupdf.open("pdf", doc.convert_to_pdf())
    doc.close()
    return pdf
