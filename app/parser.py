"""Extraction des informations d'un avis de contravention à partir de son texte (OCR ou PDF natif).

Les avis ANTAI varient selon le type (radar, PVe, FPS, majorée) : chaque champ est cherché d'abord
via son libellé, puis par heuristique. Tout reste corrigeable à la main dans l'écran de vérification.
"""
import re
import unicodedata
from datetime import date, datetime

from . import plates

MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
        "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}

DATE_NUM = r"(?<![\d/])(\d\s\d|\d{1,2})\s?[/.\-]\s?(\d{1,2})\s?[/.\-]\s?(\d{4}|\d{2})"  # « 1 5/05 » : jour coupé par l'OCR
DATE_TXT = r"(\d{1,2})(?:er)?\s+(" + "|".join(MOIS) + r")\s+(\d{4})"
HEURE = r"(\d{1,2})\s?[hH:]\s?(\d{2})"

AVIS_PATTERNS = [
    r"n(?:um(?:e|é)ro)?\s*[°o]?\s*(?:de\s+l['’ ]?\s*)?avis(?:\s+de\s+contravention)?\s*[:.]?\s*((?:\d[\s.]?){10,14})",
    r"avis\s+de\s+contravention\s*n\s*[°o]?\s*[:.]?\s*((?:\d[\s.]?){10,14})",
    r"avis\s*n\s*[°o]?\s*[:.]?\s*((?:\d[\s.]?){10,14})",
    r"n\s*[°o]\s*(?:du\s+)?(?:pv|proc[eè]s[\s-]verbal)\s*[:.]?\s*((?:\d[\s.]?){10,14})",
    r"reference\s+de\s+l.avis\s*[:.]?\s*((?:\d[\s.]?){10,14})",  # amende forfaitaire majorée
]
DATE_AVIS_LABELS = r"(?:date\s+d['’ ]?(?:envoi|[ée]mission|[ée]dition)|envoy[ée]\s+le|[ée]dit[ée]\s+le|" \
                   r"date\s+de\s+l['’ ]?avis|fait\s+le|[ée]mis\s+le)"
INFRACTION_LABELS = r"(?:infraction|commise|constat[ée]e?|relev[ée]e?|date\s+et\s+heure|le\s+v[ée]hicule)"

NATURES = [
    "EXCES DE VITESSE", "FEU ROUGE", "FEU DE SIGNALISATION", "STOP", "SENS INTERDIT",
    "STATIONNEMENT", "ARRET", "TELEPHONE", "CEINTURE", "LIGNE CONTINUE", "VOIE RESERVEE",
    "DISTANCE DE SECURITE", "PEAGE", "ZONE A FAIBLES EMISSIONS", "ZFE", "PASSAGE A NIVEAU",
    "DEFAUT D'ASSURANCE", "CONTROLE TECHNIQUE", "BUS", "BANDE D'ARRET D'URGENCE", "NUISANCE SONORE",
]


def _ascii(s: str) -> str:
    s = s.replace("€", " EUR")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _mkdate(d, m, y) -> date | None:
    try:
        y = int(y)
        if y < 100:
            y += 2000
        dt = date(y, int(m), int(str(d).replace(" ", "")))
        return dt if 2000 <= dt.year <= 2100 else None
    except ValueError:
        return None


def _dates_with_pos(text: str) -> list[tuple[int, date, str | None]]:
    """[(position, date, 'HH:MM' ou None)] pour toutes les dates du texte."""
    out = []
    low = _ascii(text).lower()
    for m in re.finditer(DATE_NUM, low):
        d = _mkdate(*m.groups())
        if d:
            out.append((m.start(), d, _heure_after(low, m.end())))
    for m in re.finditer(DATE_TXT, low):
        d = _mkdate(m.group(1), MOIS[m.group(2)], m.group(3))
        if d:
            out.append((m.start(), d, _heure_after(low, m.end())))
    return sorted(out, key=lambda x: x[0])


def _heure_after(low: str, pos: int) -> str | None:
    m = re.match(r"\s*(?:a|,|-)?\s*" + HEURE, low[pos:pos + 15])
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h < 24 and mi < 60:
            return f"{h:02d}:{mi:02d}"
    return None


def parse(text: str, fleet: list[str] | None = None) -> dict:
    """Renvoie un dict : numero_avis, type, date_infraction, heure_infraction, immat_lue,
    immatriculation (plaque de la flotte si trouvée), lieu, nature, montant, date_avis, anomalies."""
    res: dict = {"anomalies": []}
    flat = re.sub(r"[ \t]+", " ", text)
    low = _ascii(flat).lower()

    # --- Type d'avis
    if re.search(r"forfait\s*post[\s-]*stationnement|\bfps\b", low):
        res["type"] = "FPS"
    elif re.search(r"amende\s+forfaitaire\s+majoree|avis\s+d.amende\s+forfaitaire\s+majoree", low):
        res["type"] = "MAJOREE"
    else:
        res["type"] = "AMENDE"

    # --- Numéro d'avis
    for pat in AVIS_PATTERNS:
        m = re.search(pat, low)
        if m:
            res["numero_avis"] = re.sub(r"\D", "", m.group(1))
            break
    else:
        # repli : nombre isolé de 10 chiffres qui ne ressemble pas à un téléphone
        for m in re.finditer(r"(?<![\d/])(\d[\d ]{8,12}\d)(?![\d/])", low):
            digits = re.sub(r"\D", "", m.group(1))
            if len(digits) == 10 and not re.match(r"0[1-9]", digits):
                res["numero_avis"] = digits
                res["anomalies"].append("numéro d'avis deviné (sans libellé)")
                break
    if not res.get("numero_avis"):
        res["anomalies"].append("numéro d'avis introuvable")

    # --- Dates
    dates = _dates_with_pos(flat)
    m = re.search(DATE_AVIS_LABELS + r"(?:\s+de\s+contravention)?[\s\S]{0,25}?" + DATE_NUM, low)
    if m:
        res["date_avis"] = _mkdate(*m.groups()[-3:])
    infr = None
    for lab in re.finditer(INFRACTION_LABELS, low):
        near = [d for d in dates if lab.start() <= d[0] <= lab.start() + 80 and d[2]]
        if near:
            infr = near[0]
            break
    if not infr:
        with_time = [d for d in dates if d[2] and d[1] != res.get("date_avis")]
        infr = with_time[0] if with_time else None
    if not infr:
        others = [d for d in dates if d[1] != res.get("date_avis")]
        infr = min(others, key=lambda d: d[1]) if others else None
    if infr:
        res["date_infraction"] = infr[1]
        res["heure_infraction"] = infr[2]
        if not infr[2]:
            res["anomalies"].append("heure d'infraction introuvable")
    else:
        res["anomalies"].append("date d'infraction introuvable")

    # --- Titulaire (raison sociale du contrevenant, adressée « M LE REPRESENTANT LEGAL »)
    m = re.search(r"repr[ée]sentant(?:\(e\))?(?:\s+l[ée]gal(?:\(e\))?)?[ \t]*\n\s*([^\n]{3,80})", flat, re.I)
    if m and not re.search(r"\d{5}|vous|infraction", m.group(1), re.I):
        res["titulaire"] = m.group(1).strip()

    # --- Immatriculation
    cands = plates.find_candidates(flat)
    # Les plaques précédées du libellé « Immatriculation : » passent en priorité
    labelled: list[str] = []
    # libellé tolérant à l'OCR : « Immatriculation : », « lmmatriculation 7FL-684-AV », « •4mmatriculation BY-… »
    for lm in re.finditer(r"[il1|4]mmatricul\w*[ \t]*[:.•\-]?[ \t]*([A-Z0-9][A-Z0-9 \-]{5,12})", flat, re.I):
        labelled += [c for c in plates.find_candidates(lm.group(1)) if c not in labelled]
    cands = labelled + [c for c in cands if c not in labelled]
    if cands:
        res["immat_lue"] = cands[0]
    if fleet:
        for c in cands:
            hit, cost = plates.best_match(c, fleet)
            if hit:
                res["immatriculation"] = hit
                res["immat_lue"] = c
                if cost > 0:
                    res["anomalies"].append(f"plaque lue {c} rapprochée de {hit}")
                break
    if not res.get("immatriculation"):
        res["anomalies"].append("immatriculation non reconnue dans la flotte" if cands
                                else "immatriculation introuvable")
        if cands:
            res["immatriculation"] = cands[0]

    # --- Lieu
    m = re.search(r"(?:lieu(?:\s+de\s+l['’ ]?infraction)?|localisation|adresse\s+de\s+l['’ ]?infraction)"
                  r"\s*[:\-]\s*([^\n]{3,120})", flat, re.I)
    if m:
        res["lieu"] = m.group(1).strip(" .;")
    else:
        res["lieu"] = _lieu_apres_date(flat)

    # --- Nature : la ligne la plus détaillée contenant un mot-clé connu
    m = re.search(r"(?:nature\s+de\s+l['’ ]?infraction|infraction\s+constat[ée]e)\s*[:\-]\s*([^\n]{5,160})",
                  flat, re.I)
    if m:
        res["nature"] = m.group(1).strip(" .;")
    else:
        best = ""
        for line in flat.splitlines():
            up = _ascii(line).upper()
            if any(kw in up for kw in NATURES) and len(line) > len(best):
                best = line.strip(" -.;")
        if best:
            res["nature"] = best[:160]

    # --- Montant
    # Sur les avis ANTAI : « 135 € / 90 € / 375 € » (forfaitaire, minorée, majorée) ;
    # les montants en « euros » du texte légal (450 à 3750 euros...) sont ignorés s'il existe des montants en €.
    def amounts(pattern):
        out = []
        for m in re.finditer(pattern, flat, re.I):
            try:
                out.append((m.start(), float(m.group(1).replace(",", "."))))
            except ValueError:
                pass
        return out
    found = amounts(r"(\d{1,4}(?:[.,]\d{2})?)\s*€") or amounts(r"(\d{1,4}(?:[.,]\d{2})?)\s*eur(?:os?)?\b")
    if found:
        lab = re.search(r"montant\s+de\s+l.amende|montant|a\s+payer", low)
        after = [a for a in found if lab and a[0] >= lab.start()]
        res["montant"] = (after or found)[0][1]

    return res


def _lieu_apres_date(text: str) -> str | None:
    """Avis radar : le lieu suit la ligne « Date / heure : le ... » (route, PK, direction, commune - CP)."""
    lines = [l.strip() for l in text.splitlines()]
    for i, line in enumerate(lines):
        if re.search(r"date\s*[/1|lI]?\s*heure(?:\s+de\s+constatation)?\s*:", _ascii(line), re.I):
            parts = []
            for nxt in lines[i + 1:i + 6]:
                if not nxt or len(nxt) > 60 or re.search(r"infraction|constat", nxt, re.I):
                    break
                nxt = re.sub(r"^[•·.\-*]+\s*", "", nxt)  # puces
                nxt = re.sub(r"^(?:\S{1,4}R\s*:|p\s?K\s?/\s?[PF]R\s*:?|[^\s\d]{1,6}\s?:?\s?(?=\d{3}[+.]\d{3}))",
                             "PK/PR : ", nxt, flags=re.I)
                nxt = re.sub(r"\s{2,}", " ", nxt)
                parts.append(nxt)
            if parts:
                # la commune (« CHAMANT - 60300 ») en premier, puis la voie
                commune = [p for p in parts if re.search(r"\b\d{5}\b", p)]
                autres = [p for p in parts if p not in commune]
                return ", ".join(commune + autres)
    # repli : ligne « COMMUNE - 12345 »
    for line in lines:
        if re.fullmatch(r"[A-ZÀ-Ü][A-ZÀ-Ü' \-]{2,40} - \d{5}", line):
            return line
    return None


def is_accuse_designation(text: str) -> bool:
    """Accusé d'enregistrement de désignation / contestation envoyé par l'ANTAI (pas un avis)."""
    return bool(re.search(r"accuse\s+d.enregistrement", _ascii(text).lower()))


def looks_like_new_avis(text: str) -> bool:
    """Une page qui commence un nouvel avis (sert à découper un scan multi-avis).
    Le recto porte le numéro d'avis libellé ; le verso / la notice de paiement non."""
    low = _ascii(text).lower()
    return any(re.search(p, low) for p in AVIS_PATTERNS)


def fmt_date(d) -> str:
    if not d:
        return ""
    if isinstance(d, str):
        d = to_date(d)
        if not d:
            return ""
    return d.strftime("%d/%m/%Y")


def to_date(s) -> date | None:
    """'2026-09-12', '12/09/2026', date ou datetime -> date."""
    if s is None or s == "":
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    s = str(s).strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None
