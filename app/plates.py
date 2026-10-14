"""Immatriculations : normalisation, détection dans un texte et rapprochement tolérant aux erreurs d'OCR."""
import re

# SIV (AB-123-CD) et ancien FNI (1234 AB 56 / 123 ABC 45 / 12 ABC 2A)
SIV_RE = re.compile(r"\b([A-Z0-9]{2})[\s\-.]?([A-Z0-9]{3})[\s\-.]?([A-Z0-9]{2})\b")
SIV_DASHED_RE = re.compile(r"(?<![A-Z])([A-Z0-9][A-Z])\s?-\s?(\d[\dOQDILTZSBG]{2})\s?-\s?([A-Z][A-Z0-9])(?![A-Z0-9])")
FNI_RE = re.compile(r"\b(\d{1,4})[\s\-]?([A-Z]{1,3})[\s\-]?(\d{2}|2A|2B)\b")

TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "T": "1",
                          "Z": "2", "S": "5", "B": "8", "G": "6"})
TO_LETTER = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "4": "A"})

# Paires que l'OCR confond fréquemment (coût de substitution réduit)
CONFUSABLES = {frozenset(p) for p in [
    ("O", "0"), ("Q", "0"), ("D", "0"), ("O", "Q"), ("O", "D"), ("I", "1"), ("L", "1"), ("T", "1"),
    ("Z", "2"), ("S", "5"), ("B", "8"), ("G", "6"), ("A", "4"), ("E", "F"), ("M", "N"),
    ("H", "N"), ("U", "V"), ("C", "G"), ("K", "X"), ("W", "V"), ("P", "R"), ("R", "B"),
]}


def normalize(plate: str | None) -> str:
    """'ab-123 cd' -> 'AB123CD'."""
    return re.sub(r"[^A-Z0-9]", "", (plate or "").upper())


def display(plate: str | None) -> str:
    """'AB123CD' -> 'AB-123-CD' (format SIV), sinon inchangé."""
    p = normalize(plate)
    if re.fullmatch(r"[A-Z]{2}\d{3}[A-Z]{2}", p):
        return f"{p[:2]}-{p[2:5]}-{p[5:]}"
    return p


def _fix_siv(a: str, b: str, c: str) -> str | None:
    a, c = a.translate(TO_LETTER), c.translate(TO_LETTER)
    b = b.translate(TO_DIGIT)
    cand = a + b + c
    return cand if re.fullmatch(r"[A-Z]{2}\d{3}[A-Z]{2}", cand) else None


def find_candidates(text: str) -> list[str]:
    """Toutes les immatriculations plausibles d'un texte (normalisées, sans doublon).
    Les plaques écrites avec tirets (« AB-123-CD », format imprimé sur les avis) passent en premier, même collées à
    un caractère parasite de l'OCR (« 7AB-123-CD ») ; puis les autres formes, dans l'ordre d'apparition."""
    up = text.upper()
    found: list[str] = []
    for m in SIV_DASHED_RE.finditer(up):
        cand = _fix_siv(*m.groups())
        if cand and cand not in found:
            found.append(cand)
    for m in SIV_RE.finditer(up):
        a, b, c = m.groups()
        # au moins un vrai chiffre au milieu et une vraie lettre de chaque côté pour éviter les faux positifs
        if not re.search(r"\d", b) or not re.search(r"[A-Z]", a + c):
            continue
        cand = _fix_siv(a, b, c)
        if cand and cand not in found:
            found.append(cand)
    for m in FNI_RE.finditer(up):
        cand = "".join(m.groups())
        if cand not in found and not re.fullmatch(r"\d+", cand):
            found.append(cand)
    return found


def distance(a: str, b: str) -> float:
    """Levenshtein pondéré : substitutions « confusables » à 0.3."""
    a, b = normalize(a), normalize(b)
    prev = [float(j) for j in range(len(b) + 1)]
    for i, ca in enumerate(a, 1):
        cur = [float(i)]
        for j, cb in enumerate(b, 1):
            if ca == cb:
                sub = 0.0
            elif frozenset((ca, cb)) in CONFUSABLES:
                sub = 0.3
            else:
                sub = 1.0
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + sub))
        prev = cur
    return prev[-1]


def best_match(read: str, fleet: list[str], max_cost: float = 1.0) -> tuple[str | None, float]:
    """Plaque de la flotte la plus proche de `read`. Renvoie (plaque, coût) ou (None, coût) si ambigu/trop loin."""
    read = normalize(read)
    if not read or not fleet:
        return None, 99.0
    if read in fleet:
        return read, 0.0
    scored = sorted((distance(read, p), p) for p in fleet)
    best_cost, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 99.0
    if best_cost <= max_cost and second - best_cost >= 0.5:
        return best, best_cost
    return None, best_cost
