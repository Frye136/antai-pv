"""Génération du fichier CSV de désignation à déposer sur l'espace gestionnaire de flotte ANTAI.

Règles du « Guide utilisateur – Gestionnaires de parc non conventionnés » (ANTAI) et du modèle CSV officiel :
- 18 colonnes, séparateur « ; », ANSI ou UTF-8, ligne d'en-tête obligatoire, 100 désignations max par fichier ;
- « Raison sociale désignant » = raison sociale du contrevenant inscrite sur l'avis (le loueur), contrôlée par l'ANTAI ;
- Civilité : « M. », « MME » ou « SOCIETE » (personne morale désignée : raison sociale dans « Nom ou Raison sociale ») ;
- dates JJ/MM/AAAA ; code postal sur 5 chiffres pour la France ; pays selon la liste de l'annexe 3 ;
- caractères autorisés limités (lettres, accents usuels, chiffres, ()-/.,%«»:_[]?!' et espace).
Tout reste modifiable dans Paramètres > Format export ANTAI.
"""
import csv
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from . import config, db, parser, plates

FIELDS = {
    "": "(vide)",
    "numero_avis": "N° de l'avis",
    "immatriculation": "Immatriculation",
    "date_avis": "Date de l'avis",
    "date_infraction": "Date de l'infraction",
    "heure_infraction": "Heure de l'infraction",
    "designant_raison_sociale": "Raison sociale désignant (titulaire sur l'avis = vous)",
    "designant_siret": "SIRET du désignant (vous)",
    "civilite": "Civilité (M. / MME / SOCIETE)",
    "nom": "Nom ou raison sociale du désigné",
    "prenom": "Prénom",
    "date_naissance": "Date de naissance",
    "lieu_naissance": "Lieu de naissance",
    "email": "Email du désigné",
    "num_permis": "N° permis de conduire",
    "date_permis": "Permis délivré le",
    "num_voie": "N° de voie",
    "nom_voie": "Nom de voie",
    "adresse": "Adresse complète",
    "complement": "Complément d'adresse",
    "code_postal": "Code postal",
    "ville": "Ville",
    "pays": "Pays",
    "siret": "SIRET du désigné (si société)",
}

DEFAULT_TEMPLATE = {
    "version": 2,
    "separator": ";",
    "encoding": "cp1252",
    "date_format": "%d/%m/%Y",
    "header": True,
    "plaque_tirets": False,
    "civilites": {"M": "M.", "MME": "MME", "PM": "SOCIETE"},
    "max_lignes": 100,
    "columns": [
        {"titre": "Réf. Avis", "champ": "numero_avis"},
        {"titre": "Immatriculation", "champ": "immatriculation"},
        {"titre": "Date avis", "champ": "date_avis"},
        {"titre": "Raison sociale désignant", "champ": "designant_raison_sociale"},
        {"titre": "SIRET", "champ": "designant_siret"},
        {"titre": "Civilité", "champ": "civilite"},
        {"titre": "Nom ou Raison sociale", "champ": "nom"},
        {"titre": "Prénom", "champ": "prenom"},
        {"titre": "Date de naissance", "champ": "date_naissance"},
        {"titre": "Email", "champ": "email"},
        {"titre": "N° Permis de conduire", "champ": "num_permis"},
        {"titre": "Permis délivré le", "champ": "date_permis"},
        {"titre": "N° Voie", "champ": "num_voie"},
        {"titre": "Nom Voie", "champ": "nom_voie"},
        {"titre": "Complément adresse", "champ": "complement"},
        {"titre": "Code postal", "champ": "code_postal"},
        {"titre": "Ville", "champ": "ville"},
        {"titre": "Pays", "champ": "pays"},
    ],
}

# Annexe 3 du guide ANTAI : libellés de pays autorisés
PAYS = set("""AFGHANISTAN|AFRIQUE DU SUD|ALBANIE|ALGERIE|ALLEMAGNE|ANDORRE|ANGLETERRE|ANGOLA|ANTIGUA-ET-BARBUDA|
ARABIE SAOUDITE|ARGENTINE|ARMENIE|AUSTRALIE|AUTRICHE|AZERBAIDJAN|BAHAMAS|BAHREIN|BANGLADESH|BARBADE|BELGIQUE|
BELIZE|BENIN|BHOUTAN|BIELORUSSIE|BIRMANIE|BOLIVIE|BOSNIE-HERZEGOVINE|BOTSWANA|BRESIL|BRUNEI|BULGARIE|BURKINA FASO|
BURUNDI|CAMBODGE|CAMEROUN|CANADA|CAP-VERT|CHILI|CHINE|CHYPRE|COLOMBIE|COMORES|CONGO|COREE DU NORD|COREE DU SUD|
COSTA RICA|COTE D'IVOIRE|CROATIE|CUBA|DANEMARK|DJIBOUTI|DOMINIQUE|EGYPTE|EMIRATS ARABES UNIS|EQUATEUR|ERYTHREE|
ESPAGNE|ESTONIE|ETATS UNIS|ETHIOPIE|FIDJI|FINLANDE|FRANCE|GABON|GAMBIE|GEORGIE|GHANA|GRECE|GRENADE|GUATEMALA|
GUINEE|GUINEE EQUATORIALE|GUINEE-BISSAU|GUYANE|HAITI|HONDURAS|HONGRIE|ILE MAURICE|INDE|INDONESIE|IRAK|IRAN|
IRLANDE|ISLANDE|ISRAEL|ITALIE|JAMAIQUE|JAPON|JORDANIE|KAZAKHSTAN|KENYA|KIRGHIZISTAN|KIRIBATI|KOSOVO|KOWEIT|LAOS|
LESOTHO|LETTONIE|LIBAN|LIBERIA|LIBYE|LIECHTENSTEIN|LITUANIE|LUXEMBOURG|MACEDOINE|MADAGASCAR|MALAISIE|MALAWI|
MALDIVES|MALI|MALTE|MAROC|MARSHALL|MAURICE|MAURITANIE|MEXIQUE|MICRONESIE|MOLDAVIE|MONACO|MONGOLIE|MONTENEGRO|
MOZAMBIQUE|NAMIBIE|NAURU|NEPAL|NICARAGUA|NIGER|NIGERIA|NORVEGE|NOUVELLE ZELANDE|OMAN|OUGANDA|OUZBEKISTAN|PAKISTAN|
PALAOS|PANAMA|PAPOUASIE-NOUVELLE-GUINEE|PARAGUAY|PAYS-BAS|PEROU|PHILIPPINES|POLOGNE|PORTUGAL|QATAR|
REPUBLIQUE CENTRAFRICAINE|REPUBLIQUE DEMOCRATIQUE DU CONGO|REPUBLIQUE DOMINICAINE|REPUBLIQUE TCHEQUE|ROUMANIE|
ROYAUME UNI|RUSSIE|RWANDA|SAINT MARIN|SAINTE LUCIE|SAINT-KITTS-ET-NEVIS|SAINT-VINCENT-ET-LES-GRENADINES|SALOMON|
SALVADOR|SAMOA|SAO TOME ET PRINCIPE|SENEGAL|SERBIE|SEYCHELLES|SIERRA LEONE|SINGAPOUR|SLOVAQUIE|SLOVENIE|SOMALIE|
SOUDAN|SRI LANKA|SUEDE|SUISSE|SURINAME|SWAZILAND|SYRIE|TADJIKISTAN|TAIWAN|TANZANIE|TCHAD|THAILANDE|TIMOR-ORIENTAL|
TOGO|TONGA|TRINITE-ET-TOBAGO|TUNISIE|TURKMENISTAN|TURQUIE|TUVALU|UKRAINE|URUGUAY|USA|VANUATU|VATICAN|VENEZUELA|
VIETNAM|YEMEN|ZAMBIE|ZIMBABWE""".replace("\n", "").split("|"))
PAYS_ALIAS = {"FR": "FRANCE", "BE": "BELGIQUE", "LU": "LUXEMBOURG", "DE": "ALLEMAGNE", "CH": "SUISSE",
              "ES": "ESPAGNE", "IT": "ITALIE", "NL": "PAYS-BAS", "PT": "PORTUGAL", "GB": "ROYAUME UNI",
              "UK": "ROYAUME UNI", "ROYAUME-UNI": "ROYAUME UNI", "ETATS-UNIS": "ETATS UNIS", "PAYS BAS": "PAYS-BAS",
              "REPUBLIQUE TCHEQUE": "REPUBLIQUE TCHEQUE", "TCHEQUIE": "REPUBLIQUE TCHEQUE"}

# caractères autorisés par l'ANTAI dans les zones de saisie
_ALLOWED = re.compile(r"[^A-Za-z0-9()\-/.,%«»:_\[\]?!' ÀÁÂÃÄÅàáâãäåÈÉÊËèéêëÌÍÎÏìíîïÒÓÔÕÖòóôõöÙÚÛÜùúûüÝŸýÿÇçÑñ]")

# Associations automatiques titre de colonne -> champ (import d'un nouveau modèle officiel)
_ALIASES = [
    (r"r[ée]f.*avis|n.*avis|num.*avis", "numero_avis"),
    (r"immat", "immatriculation"),
    (r"date.*avis", "date_avis"),
    (r"date.*infraction", "date_infraction"),
    (r"heure", "heure_infraction"),
    (r"raison sociale d[ée]sign", "designant_raison_sociale"),
    (r"siret|siren", "designant_siret"),
    (r"civilit", "civilite"),
    (r"^nom(?! voie)|nom ou raison", "nom"),
    (r"pr[ée]nom", "prenom"),
    (r"date.*naissance", "date_naissance"),
    (r"lieu.*naissance", "lieu_naissance"),
    (r"mail", "email"),
    (r"n.*permis", "num_permis"),
    (r"permis.*d[ée]livr|date.*permis", "date_permis"),
    (r"n.*voie", "num_voie"),
    (r"nom.*voie|libell.*voie|rue", "nom_voie"),
    (r"compl", "complement"),
    (r"code.*postal|^cp$", "code_postal"),
    (r"ville|commune|localit", "ville"),
    (r"pays", "pays"),
]


def template() -> dict:
    t = db.setting_json("export_template", None)
    # un format enregistré avant le modèle officiel à 18 colonnes est ignoré
    if t and t.get("columns") and t.get("version", 1) >= 2:
        return t
    return json.loads(json.dumps(DEFAULT_TEMPLATE))


def guess_field(title: str) -> str:
    low = title.strip().lower()
    for pat, field in _ALIASES:
        if re.search(pat, low):
            return field
    return ""


def template_from_model(path: str) -> dict:
    """Construit un format à partir d'un fichier modèle CSV (1re ligne = en-têtes)."""
    raw = Path(path).read_bytes()
    enc = "cp1252"
    try:
        text = raw.decode("utf-8-sig")
        enc = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    first = text.splitlines()[0]
    sep = max([";", ",", "\t", "|"], key=first.count)
    t = template()
    t.update(separator=sep, encoding="cp1252" if enc == "cp1252" else "utf-8-sig",
             columns=[{"titre": h.strip(), "champ": guess_field(h)} for h in first.split(sep)])
    return t


def split_adresse(adresse: str) -> tuple[str, str]:
    """'4 bis avenue Jules Ferry' -> ('4 bis', 'avenue Jules Ferry')."""
    a = (adresse or "").strip()
    m = re.match(r"^(\d+\s*(?:bis|ter|quater|[a-d])?)\b[\s,]*(.+)$", a, re.I)
    return (m.group(1).strip(), m.group(2).strip()) if m else ("", a)


def _ascii_upper(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper().strip()


def clean_text(s) -> str:
    """Remplace les caractères refusés par l'ANTAI (&, +, #, ’, retours ligne…)."""
    s = str(s or "").replace("&", " ET ").replace("’", "'").replace("°", " ")
    s = _ALLOWED.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_pays(p) -> str:
    v = _ascii_upper((p or "FRANCE").replace("’", "'"))
    v = PAYS_ALIAS.get(v, v)
    return v


def designant_raison_sociale(pv) -> str:
    """Raison sociale du contrevenant telle qu'inscrite sur l'avis (sinon : celle du loueur dans les paramètres)."""
    keys = pv.keys() if hasattr(pv, "keys") else []
    return (pv["titulaire"] if "titulaire" in keys and pv["titulaire"] else "") or db.setting("loueur_raison_sociale")


def designee(pv) -> dict:
    """Personne (morale ou physique) à désigner pour ce PV : le chauffeur salarié s'il est renseigné (véhicule de la
    société), sinon le conducteur nommé du contrat ou le client locataire."""
    cid = pv["conducteur_id"] if "conducteur_id" in pv.keys() else None
    if cid:
        d = db.q1("SELECT * FROM conducteurs WHERE id=?", (cid,))
        if d:
            out = {key: d[key] for key in d.keys()}
            out.update(type="PP", raison_sociale="", siret="")
            return out
    c = db.q1("SELECT * FROM clients WHERE id=?", (pv["client_id"],)) if pv["client_id"] else None
    k = db.q1("SELECT * FROM contrats WHERE id=?", (pv["contrat_id"],)) if pv["contrat_id"] else None
    if k and k["designer_conducteur"] and k["cond_nom"]:
        return {
            "type": "PP", "civilite": "", "nom": k["cond_nom"], "prenom": k["cond_prenom"],
            "date_naissance": k["cond_date_naissance"], "lieu_naissance": k["cond_lieu_naissance"],
            "num_permis": k["cond_num_permis"], "date_permis": "",
            "adresse": k["cond_adresse"], "complement": "", "code_postal": k["cond_code_postal"],
            "ville": k["cond_ville"], "pays": "FRANCE", "email": c["email"] if c else "",
            "raison_sociale": "", "siret": "",
        }
    if not c:
        return {}
    return {key: c[key] for key in c.keys()}


def missing_fields(d: dict, pv) -> list[str]:
    """Champs obligatoires manquants ou refusés par l'ANTAI (bloquent la génération du CSV)."""
    miss = []
    if not re.fullmatch(r"\d{10}", str(pv["numero_avis"] or "")):
        miss.append("n° d'avis (10 chiffres)")
    if not pv["immatriculation"]:
        miss.append("immatriculation")
    if not pv["date_avis"]:
        miss.append("date de l'avis")
    if not designant_raison_sociale(pv):
        miss.append("votre raison sociale (Paramètres)")
    if not d:
        return miss + ["locataire"]
    if d.get("type") == "PM":
        if not d.get("raison_sociale"):
            miss.append("raison sociale")
    else:
        for f, lib in (("nom", "nom"), ("prenom", "prénom"), ("date_naissance", "date de naissance")):
            if not d.get(f):
                miss.append(lib)
        if not _civilite_code(d.get("civilite")):
            miss.append("civilité (M. / Mme)")
        dn, dp = parser.to_date(d.get("date_naissance")), parser.to_date(d.get("date_permis"))
        if dn and dp and dp <= dn:
            miss.append("date du permis antérieure à la naissance")
    for f, lib in (("adresse", "adresse"), ("ville", "ville")):
        if not d.get(f):
            miss.append(lib)
    pays = clean_pays(d.get("pays"))
    if pays not in PAYS:
        miss.append(f"pays « {d.get('pays')} » hors liste ANTAI")
    if pays == "FRANCE" and not re.fullmatch(r"\d{4,5}", re.sub(r"\s", "", d.get("code_postal") or "")):
        miss.append("code postal (5 chiffres)")
    return miss


def warnings(d: dict) -> list[str]:
    """Points signalés en avertissement par l'ANTAI (n'empêchent pas le dépôt)."""
    if d and d.get("type") != "PM" and not d.get("num_permis"):
        return ["n° de permis du conducteur non renseigné (avertissement ANTAI)"]
    return []


def _civilite_code(civ) -> str:
    c = _ascii_upper(civ).replace(".", "")
    return {"M": "M", "MR": "M", "MONSIEUR": "M", "H": "M", "HOMME": "M",
            "MME": "MME", "MADAME": "MME", "MLLE": "MME", "MADEMOISELLE": "MME", "F": "MME", "FEMME": "MME"}.get(c, "")


def row_values(pv, t: dict) -> dict:
    d = designee(pv)
    fmt = t.get("date_format", "%d/%m/%Y")

    def dt(v):
        x = parser.to_date(v)
        return x.strftime(fmt) if x else ""

    pm = d.get("type") == "PM"
    num, voie = split_adresse(d.get("adresse") or "")
    pays = clean_pays(d.get("pays"))
    cp = re.sub(r"\s", "", d.get("code_postal") or "")
    if pays == "FRANCE" and cp.isdigit() and len(cp) == 4:
        cp = cp.zfill(5)
    immat = pv["immatriculation"] or ""
    civ_map = t.get("civilites", {})
    civ = civ_map.get("PM", "SOCIETE") if pm else civ_map.get(_civilite_code(d.get("civilite")), "")
    email = (d.get("email") or "").split(";")[0].split(",")[0].strip()
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+@[A-Za-z0-9_.\-]+\.[A-Za-z]{2,}", email):
        email = ""  # l'ANTAI n'accepte que les caractères non accentués _ . - @
    return {
        "": "",
        "numero_avis": pv["numero_avis"] or "",
        "immatriculation": plates.display(immat) if t.get("plaque_tirets") else plates.normalize(immat),
        "date_avis": dt(pv["date_avis"]),
        "date_infraction": dt(pv["date_infraction"]),
        "heure_infraction": pv["heure_infraction"] or "",
        "designant_raison_sociale": designant_raison_sociale(pv).strip(),  # non contrôlé : laissé tel quel
        "designant_siret": re.sub(r"\D", "", db.setting("loueur_siret")),
        "civilite": civ,
        "nom": clean_text(d.get("raison_sociale") if pm else d.get("nom")).upper(),
        "prenom": "" if pm else clean_text(d.get("prenom")),
        "date_naissance": "" if pm else dt(d.get("date_naissance")),
        "lieu_naissance": "" if pm else clean_text(d.get("lieu_naissance")),
        "email": email,
        "num_permis": "" if pm else re.sub(r"[^A-Za-z0-9]", "", _ascii_upper(d.get("num_permis"))),
        "date_permis": "" if pm else dt(d.get("date_permis")),
        "num_voie": clean_text(num),
        "nom_voie": clean_text(voie).upper(),
        "adresse": clean_text(d.get("adresse")).upper(),
        "complement": clean_text(d.get("complement")).upper(),
        "code_postal": cp,
        "ville": clean_text(d.get("ville")).upper(),
        "pays": pays,
        "siret": re.sub(r"\D", "", d.get("siret") or "") if pm else "",
    }


def _cell(value: str, t: dict) -> str:
    v = str(value or "").replace(t.get("separator", ";"), " ").replace("\n", " ").strip()
    # caractères non représentables dans l'encodage cible (ex. cp1252) -> remplacés
    return v.encode(t.get("encoding", "cp1252"), "replace").decode(t.get("encoding", "cp1252"))


def generate(pv_ids: list[int]) -> list[Path]:
    """Crée le(s) fichier(s) CSV (100 lignes max chacun), enregistre les lots et passe les PV au statut EXPORTE."""
    t = template()
    pvs = [db.q1("SELECT * FROM pv WHERE id=?", (i,)) for i in pv_ids]
    pvs = [p for p in pvs if p]
    if not pvs:
        return []
    size = int(t.get("max_lignes") or 0) or len(pvs)
    out_dir = config.sub("exports")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    files = []
    for n, start in enumerate(range(0, len(pvs), size), 1):
        chunk = pvs[start:start + size]
        suffix = f"_{n}" if len(pvs) > size else ""
        path = out_dir / f"LOT-ANTAI_{stamp}{suffix}.csv"
        with open(path, "w", newline="", encoding=t.get("encoding", "cp1252"), errors="replace") as f:
            w = csv.writer(f, delimiter=t.get("separator", ";"), quoting=csv.QUOTE_MINIMAL)
            if t.get("header", True):
                w.writerow([_cell(c["titre"], t) for c in t["columns"]])
            for pv in chunk:
                vals = row_values(pv, t)
                w.writerow([_cell(vals.get(c["champ"], ""), t) for c in t["columns"]])
        export_id = db.insert("exports", {"fichier": str(path), "nb_pv": len(chunk)})
        for pv in chunk:
            db.update("pv", pv["id"], {"statut": "EXPORTE", "export_id": export_id,
                                       "date_designation": datetime.now().strftime("%Y-%m-%d"),
                                       "updated_at": datetime.now().isoformat(" ", "seconds")})
            db.log("Export ANTAI", path.name, pv["id"])
        files.append(path)
    return files
