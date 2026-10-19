"""Traitements métier : import des scans, archivage, identification du locataire, échéances."""
import hashlib
import os
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import pymupdf

from . import antai_export, config, db, ocr, parser, plates

SUPPORTED = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}


def now() -> str:
    return datetime.now().isoformat(" ", "seconds")


def fleet() -> list[str]:
    return [r["immatriculation"] for r in db.q("SELECT immatriculation FROM vehicules")]


# ---------------------------------------------------------------- import / archivage

def _archive_path(numero: str | None, immat: str | None, d_avis) -> Path:
    d = parser.to_date(d_avis) or date.today()
    folder = config.sub("archive") / f"{d:%Y}" / f"{d:%m}"
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{numero or 'SANS-NUMERO'}_{plates.normalize(immat) or 'XX'}"
    path = folder / f"{base}.pdf"
    i = 2
    while path.exists():
        path = folder / f"{base}_{i}.pdf"
        i += 1
    return path


def import_file(path: str | Path, progress=None, move_to: Path | None = None) -> list[dict]:
    """Importe un fichier scanné (1 à n avis). Renvoie [{'pv_id', 'numero', 'statut', 'message'}]."""
    path = Path(path)
    results = []
    doc = ocr.open_as_pdf(str(path))
    texts = []
    for i, page in enumerate(doc):
        if progress:
            progress(f"{path.name} : lecture page {i + 1}/{doc.page_count}")
        res = ocr.read_page(page)
        texts.append(res.text)
        if res.rotation:  # page scannée tournée / à l'envers : archivée à l'endroit
            page.set_rotation((page.rotation + res.rotation) % 360)

    # Découpage : chaque recto portant un n° d'avis commence un nouvel avis, les pages suivantes y sont rattachées.
    # Un accusé d'enregistrement ANTAI forme un seul document (ses pages annexes ne sont pas des avis).
    groups: list[list[int]] = []
    numeros: list[str | None] = []  # n° d'avis de chaque groupe
    for i, t in enumerate(texts):
        accuse_en_cours = groups and parser.is_accuse_designation(texts[groups[-1][0]])
        nouveau = parser.looks_like_new_avis(t) and not accuse_en_cours
        num = parser.parse(t).get("numero_avis") if nouveau else None
        if nouveau and groups and num and num == numeros[-1]:
            nouveau = False  # verso / formulaire de requête portant le même n° : même avis
        if not groups or nouveau or parser.is_accuse_designation(t):
            groups.append([i])
            numeros.append(num)
        else:
            groups[-1].append(i)

    flt = fleet()
    for pages in groups:
        text = "\n".join(texts[p] for p in pages)
        data = parser.parse(texts[pages[0]], flt)
        numero = data.get("numero_avis")
        if parser.is_accuse_designation(texts[pages[0]]):
            results.append(_import_accuse(numero, _sub_pdf(doc, pages), path.name))
            continue
        if numero and db.q1("SELECT id FROM pv WHERE numero_avis=?", (numero,)):
            db.log("Doublon ignoré", f"{numero} ({path.name})")
            results.append({"pv_id": None, "numero": numero, "statut": "DOUBLON",
                            "message": f"Avis {numero} déjà enregistré — ignoré"})
            continue
        pdf_bytes = _sub_pdf(doc, pages)
        digest = hashlib.sha256(pdf_bytes).hexdigest()
        if db.q1("SELECT id FROM pv WHERE fichier_hash=?", (digest,)):
            results.append({"pv_id": None, "numero": numero, "statut": "DOUBLON",
                            "message": "Document identique déjà importé — ignoré"})
            continue
        dest = _archive_path(numero, data.get("immatriculation"), data.get("date_avis"))
        dest.write_bytes(pdf_bytes)
        pv_id = db.insert("pv", {
            "numero_avis": numero,
            "type": data.get("type", "AMENDE"),
            "date_infraction": _iso(data.get("date_infraction")),
            "heure_infraction": data.get("heure_infraction"),
            "immatriculation": data.get("immatriculation"),
            "immat_lue": data.get("immat_lue"),
            "titulaire": data.get("titulaire"),
            "lieu": data.get("lieu"), "nature": data.get("nature"), "montant": data.get("montant"),
            "date_avis": _iso(data.get("date_avis")),
            "fichier": str(dest), "fichier_hash": digest, "ocr_texte": text,
            "anomalie": "; ".join(data.get("anomalies", [])),
            "notes": "\n".join([f"Source : {path.name}"]
                                + ([f"Conducteur interpellé : {data['conducteur_interpelle']}"]
                                   if data.get("conducteur_interpelle") else [])
                                + ([f"Tranche {data['tranche']} (un avis par tranche de surcharge)"]
                                   if data.get("tranche") else [])
                                + ([f"Montant minoré : {data['montant_minore']:g} € si payé sous 15 jours (30 jours "
                                    f"en ligne) à compter du {parser.fmt_date(data.get('date_avis')) or 'jour de l’avis'}"
                                    .replace(".", ",")]
                                   if data.get("montant_minore") else [])),
        })
        db.log("Import", f"{path.name} p.{pages[0] + 1}-{pages[-1] + 1}", pv_id)
        statut = identify(pv_id)
        results.append({"pv_id": pv_id, "numero": numero, "statut": statut, "message": ""})
    doc.close()

    if move_to is not None:
        move_to.mkdir(parents=True, exist_ok=True)
        target = move_to / f"{datetime.now():%Y%m%d_%H%M%S}_{path.name}"
        shutil.move(str(path), target)
    return results


def _sub_pdf(doc, pages: list[int]) -> bytes:
    sub = pymupdf.open()
    sub.insert_pdf(doc, from_page=pages[0], to_page=pages[-1])
    data = sub.tobytes(garbage=3, deflate=True)
    sub.close()
    return data


def _import_accuse(numero: str | None, pdf_bytes: bytes, source: str) -> dict:
    """Accusé d'enregistrement ANTAI : archivé à côté de l'avis, qui passe « Déposé ANTAI »."""
    pv = db.q1("SELECT * FROM pv WHERE numero_avis=?", (numero,)) if numero else None
    folder = Path(pv["fichier"]).parent if pv and pv["fichier"] else _archive_path(numero, None, None).parent
    dest = folder / f"{numero or 'SANS-NUMERO'}_ACCUSE-ANTAI.pdf"
    i = 2
    while dest.exists():
        dest = folder / f"{numero or 'SANS-NUMERO'}_ACCUSE-ANTAI_{i}.pdf"
        i += 1
    dest.write_bytes(pdf_bytes)
    if not pv:
        db.log("Accusé ANTAI sans avis", f"{numero} ({source}) -> {dest.name}")
        return {"pv_id": None, "numero": numero, "statut": "ACCUSE",
                "message": f"Accusé ANTAI {numero or '?'} archivé, mais l'avis correspondant n'est pas dans la base"}
    upd = {"notes": ((pv["notes"] or "") + f"\nAccusé ANTAI : {dest}").strip(), "updated_at": now()}
    if pv["statut"] in ("A_VERIFIER", "NON_IDENTIFIE", "A_DENONCER", "EXPORTE"):
        upd["statut"] = "DEPOSE"
        upd["traitement"] = "DESIGNATION"
        upd["date_designation"] = pv["date_designation"] or date.today().isoformat()
    db.update("pv", pv["id"], upd)
    db.log("Accusé d'enregistrement ANTAI reçu", dest.name, pv["id"])
    return {"pv_id": None, "numero": numero, "statut": "ACCUSE",
            "message": f"Accusé ANTAI {numero} rattaché à l'avis — statut : {db.STATUTS[upd.get('statut', pv['statut'])]}"}


def _iso(d) -> str | None:
    d = parser.to_date(d)
    return d.isoformat() if d else None


def reread(pv_id: int) -> str:
    """Relit le PDF archivé avec l'OCR actuel et remplace les champs extraits, puis ré-identifie le locataire.
    Utile pour un avis importé avant une amélioration de la lecture, ou mal lu."""
    pv = db.q1("SELECT * FROM pv WHERE id=?", (pv_id,))
    if not pv["fichier"] or not Path(pv["fichier"]).exists():
        raise FileNotFoundError("PDF archivé introuvable.")
    doc = ocr.open_as_pdf(pv["fichier"])
    texts = [ocr.read_page(p).text for p in doc]
    doc.close()
    data = parser.parse(texts[0], fleet())
    upd = {k: v for k, v in {
        "numero_avis": data.get("numero_avis"), "type": data.get("type"),
        "date_infraction": _iso(data.get("date_infraction")), "heure_infraction": data.get("heure_infraction"),
        "immatriculation": data.get("immatriculation"), "immat_lue": data.get("immat_lue"),
        "titulaire": data.get("titulaire"), "lieu": data.get("lieu"), "nature": data.get("nature"),
        "montant": data.get("montant"), "date_avis": _iso(data.get("date_avis")),
    }.items() if v}  # un champ non relu garde sa valeur actuelle
    if upd.get("numero_avis") and db.q1("SELECT id FROM pv WHERE numero_avis=? AND id<>?", (upd["numero_avis"], pv_id)):
        upd.pop("numero_avis")
    upd.update(ocr_texte="\n".join(texts), anomalie="; ".join(data.get("anomalies", [])), updated_at=now())
    db.update("pv", pv_id, upd)
    db.log("Relecture du scan", ", ".join(k for k in upd if k not in ("ocr_texte", "anomalie", "updated_at")), pv_id)
    return identify(pv_id)


def delete_pv(pv_ids: list[int], delete_files: bool = False) -> int:
    """Supprime des avis de la base (trace conservée dans le journal). `delete_files` : supprime aussi le PDF archivé.
    Un avis supprimé peut être réimporté depuis son scan."""
    n = 0
    for i in pv_ids:
        pv = db.q1("SELECT * FROM pv WHERE id=?", (i,))
        if not pv:
            continue
        detail = (f"avis {pv['numero_avis'] or '?'} – {plates.display(pv['immatriculation'])} – "
                  f"{db.STATUTS.get(pv['statut'], pv['statut'])}")
        if delete_files and pv["fichier"]:
            try:
                Path(pv["fichier"]).unlink(missing_ok=True)
                detail += " – PDF supprimé"
            except OSError as e:
                detail += f" – PDF non supprimé ({e})"
        elif pv["fichier"]:
            detail += f" – PDF conservé : {pv['fichier']}"
        db.execute("DELETE FROM pv WHERE id=?", (i,))
        db.execute("UPDATE journal SET pv_id=NULL WHERE pv_id=?", (i,))  # l'historique reste lisible
        db.log("Suppression", detail)
        n += 1
    return n


def delete_lots(export_ids: list[int], delete_files: bool = False) -> int:
    """Supprime des lots ANTAI. Lot non déposé : ses avis repassent « À dénoncer » (à régénérer).
    Lot déjà déposé : ses avis restent « Déposé ANTAI » (la désignation a eu lieu), seul le lien au lot disparaît.
    `delete_files` : supprime aussi le fichier CSV."""
    n = 0
    for i in export_ids:
        lot = db.q1("SELECT * FROM exports WHERE id=?", (i,))
        if not lot:
            continue
        nom = Path(lot["fichier"] or "").name
        for r in db.q("SELECT id, statut FROM pv WHERE export_id=?", (i,)):
            upd = {"export_id": None, "updated_at": now()}
            if not lot["depose_le"] and r["statut"] == "EXPORTE":
                upd.update(statut="A_DENONCER", date_designation=None)
            db.update("pv", r["id"], upd)
            db.log("Lot supprimé", f"{nom} – avis " + ("à redénoncer" if "statut" in upd else "inchangé"), r["id"])
        detail = f"{nom} ({lot['nb_pv']} avis, {'déposé le ' + lot['depose_le'] if lot['depose_le'] else 'non déposé'})"
        if delete_files and lot["fichier"]:
            try:
                Path(lot["fichier"]).unlink(missing_ok=True)
                detail += " – CSV supprimé"
            except OSError as e:
                detail += f" – CSV non supprimé ({e})"
        db.execute("DELETE FROM exports WHERE id=?", (i,))
        db.log("Suppression de lot", detail)
        n += 1
    return n


def rename_archive(pv_id: int) -> None:
    """Renomme le PDF archivé après correction du n° / de la plaque."""
    pv = db.q1("SELECT * FROM pv WHERE id=?", (pv_id,))
    if not pv or not pv["fichier"]:
        return
    cur = Path(pv["fichier"])
    wanted = f"{pv['numero_avis'] or 'SANS-NUMERO'}_{plates.normalize(pv['immatriculation']) or 'XX'}"
    if not cur.exists() or cur.stem.startswith(wanted):
        return
    dest = _archive_path(pv["numero_avis"], pv["immatriculation"], pv["date_avis"])
    if dest.drive.lower() != cur.drive.lower():
        dest = cur.with_name(dest.name)  # renommage sur place : jamais de copie (pas de doublon si le fichier est ouvert)
    try:
        os.replace(cur, dest)
    except OSError as e:  # fichier ouvert dans un autre logiciel : on garde l'ancien nom
        db.log("Renommage du PDF impossible", f"{cur.name} -> {dest.name} : {e}", pv_id)
        return
    db.update("pv", pv_id, {"fichier": str(dest)})


# ---------------------------------------------------------------- identification

def find_contracts(vehicule_id: int, d_infr, heure: str | None) -> list:
    d = parser.to_date(d_infr)
    if not d:
        return []
    if heure:
        start = end = f"{d.isoformat()} {heure}"
    else:
        start, end = f"{d.isoformat()} 23:59", f"{d.isoformat()} 00:00"
    return db.q("""SELECT * FROM contrats WHERE vehicule_id=? AND date_debut<=?
                   AND (date_fin IS NULL OR date_fin='' OR date_fin>=?) ORDER BY date_debut""",
                (vehicule_id, start, end))


def deadline(pv) -> str | None:
    """Échéance : désignation (45 j après l'avis) ou paiement avant majoration (FPS : 3 mois)."""
    fps = pv["type"] == "FPS"
    delai = int(db.setting("delai_fps_jours" if fps else "delai_jours") or (90 if fps else 45))
    base = parser.to_date(pv["date_avis"]) or parser.to_date(pv["date_infraction"])
    return (base + timedelta(days=delai)).isoformat() if base else None


def traitement_auto(pv, client_id: int | None) -> str:
    """Filière par défaut : payer et refacturer pour FPS / majorées / autres / stationnement / clients qui le
    préfèrent ; désignation ANTAI sinon."""
    if pv["type"] in ("FPS", "MAJOREE", "AUTRE", "INTERPELLATION"):
        return "PAIEMENT"
    if db.setting("stationnement_payer") == "1" and "STATIONNEMENT" in parser._ascii(pv["nature"] or "").upper():
        return "PAIEMENT"
    if client_id:
        c = db.q1("SELECT traitement_pv FROM clients WHERE id=?", (client_id,))
        if c and c["traitement_pv"] == "PAIEMENT":
            return "PAIEMENT"
    return "DESIGNATION"


def identify(pv_id: int, force: bool = False) -> str:
    """Rapproche le PV du véhicule et du contrat en cours à la date/heure de l'infraction, choisit la filière
    (désignation ou paiement) et met à jour statut, anomalies et échéance.
    Ne modifie pas un PV déjà exporté / payé / clos, sauf `force`."""
    pv = db.q1("SELECT * FROM pv WHERE id=?", (pv_id,))
    if pv["statut"] not in db.STATUTS_AUTO and not force:
        return pv["statut"]
    upd: dict = {"date_limite": deadline(pv), "updated_at": now()}
    anomalies = [a for a in (pv["anomalie"] or "").split("; ")
                 if a and not a.startswith(("locataire", "véhicule", "plusieurs contrats", "plaque lue", "fiche",
                                            "avis", "FPS", "données", "n° de permis", "immatriculation",
                                            "chauffeur", "SIRET"))]

    immat = plates.normalize(pv["immatriculation"])
    veh = db.q1("SELECT * FROM vehicules WHERE immatriculation=?", (immat,)) if immat else None
    if not veh and immat:
        hit, _ = plates.best_match(immat, fleet())
        if hit:
            veh = db.q1("SELECT * FROM vehicules WHERE immatriculation=?", (hit,))
            upd["immatriculation"] = hit
            anomalies.append(f"plaque lue {immat} rapprochée de {hit}")
    upd["vehicule_id"] = veh["id"] if veh else None
    upd["contrat_id"] = None
    upd["client_id"] = None

    # --- locataire au moment de l'infraction
    probleme = None  # statut d'attente si le locataire n'est pas déterminé
    if not veh:
        probleme = "NON_IDENTIFIE"
        anomalies.append("véhicule absent de la flotte")
    else:
        contrats = find_contracts(veh["id"], pv["date_infraction"], pv["heure_infraction"])
        if not contrats:
            probleme = "NON_IDENTIFIE"
            anomalies.append("véhicule non loué à cette date (usage interne ?)")
        elif len(contrats) > 1 and pv["contrat_id"] in [c["id"] for c in contrats]:
            upd["contrat_id"] = pv["contrat_id"]  # choix manuel déjà fait
        elif len(contrats) > 1:
            probleme = "A_VERIFIER"
            anomalies.append(f"plusieurs contrats possibles ({', '.join(c['numero'] or str(c['id']) for c in contrats)})"
                             " — choisissez le bon")
        else:
            upd["contrat_id"] = contrats[0]["id"]
    if upd["contrat_id"]:
        k = db.q1("SELECT client_id FROM contrats WHERE id=?", (upd["contrat_id"],))
        upd["client_id"] = k["client_id"] if k else None

    # --- chauffeur salarié (véhicule de la société ou usage interne) : désigné à la place du locataire
    societe = bool(veh and veh["propre"] and not upd["contrat_id"])
    if pv["conducteur_source"] == "MANUEL" and pv["conducteur_id"]:
        probleme = None  # chauffeur choisi et confirmé dans la fiche
        anomalies = [a for a in anomalies if not a.startswith("véhicule non loué")]
    elif societe:
        upd["contrat_id"] = upd["client_id"] = None
        probleme = "A_VERIFIER"
        if veh["conducteur_id"]:
            upd["conducteur_id"], upd["conducteur_source"] = veh["conducteur_id"], "HABITUEL"
            anomalies.append("véhicule de la société : chauffeur habituel proposé — confirmez-le dans la fiche")
        else:
            upd["conducteur_id"] = upd["conducteur_source"] = None
            anomalies.append("véhicule de la société : choisissez le chauffeur dans la fiche")
    elif pv["conducteur_source"] == "HABITUEL":  # proposition devenue caduque (véhicule loué, plus « société »)
        upd["conducteur_id"] = upd["conducteur_source"] = None
    if probleme == "NON_IDENTIFIE" and veh and not societe:
        anomalies = [a if not a.startswith("véhicule non loué") else
                     "véhicule non loué à cette date (usage interne ?) — un chauffeur peut être désigné dans la fiche"
                     for a in anomalies]

    # --- filière
    traitement = pv["traitement_manuel"] or traitement_auto(pv, upd["client_id"])
    upd["traitement"] = traitement
    if traitement == "PAIEMENT":
        # le paiement n'attend pas l'identification : le locataire ne sert qu'à refacturer
        statut = "A_PAYER"
        if probleme and not societe and pv["conducteur_source"] != "MANUEL":
            anomalies.append("locataire à identifier pour la refacturation")
    else:
        statut = probleme or "A_DENONCER"
        if pv["type"] == "MAJOREE":
            anomalies.append("avis majoré : la désignation n'est plus possible, passez en « payer et refacturer »")
            statut = "A_VERIFIER"
        if pv["type"] == "INTERPELLATION":
            anomalies.append("avis à conducteur interpellé : il n'y a normalement rien à désigner, "
                             "passez en « payer et refacturer »")
            statut = "A_VERIFIER"
        if statut == "A_DENONCER":
            merged = dict(pv)
            merged.update(upd)
            d = antai_export.designee(merged)
            missing = antai_export.missing_fields(d, merged)
            if missing:
                statut = "A_VERIFIER"
                anomalies.append("données manquantes : " + ", ".join(missing))
            anomalies += antai_export.warnings(d)

    if pv["client_id"] != upd["client_id"] or pv["frais_dossier"] is None:
        upd["frais_dossier"] = frais_dossier(upd["client_id"])
    upd["statut"] = statut
    upd["anomalie"] = "; ".join(dict.fromkeys(anomalies))
    db.update("pv", pv_id, upd)
    return statut


def set_contract(pv_id: int, contrat_id: int | None) -> str:
    """Choix manuel du contrat (cas ambigu)."""
    k = db.q1("SELECT * FROM contrats WHERE id=?", (contrat_id,)) if contrat_id else None
    db.update("pv", pv_id, {"contrat_id": contrat_id, "client_id": k["client_id"] if k else None})
    db.log("Contrat choisi manuellement", f"contrat {k['numero'] if k else '-'}", pv_id)
    pv = db.q1("SELECT * FROM pv WHERE id=?", (pv_id,))
    if pv["statut"] in db.STATUTS_AUTO:
        return identify(pv_id)  # garde le contrat choisi (cas ambigu) et recalcule statut / filière
    db.update("pv", pv_id, {"frais_dossier": frais_dossier(pv["client_id"]), "updated_at": now()})
    return pv["statut"]


def set_conducteur(pv_id: int, conducteur_id: int | None) -> str:
    """Choix (confirmé) du chauffeur salarié à désigner ; None : revenir au locataire du contrat."""
    db.update("pv", pv_id, {"conducteur_id": conducteur_id, "conducteur_source": "MANUEL" if conducteur_id else None})
    d = db.q1("SELECT nom, prenom, matricule FROM conducteurs WHERE id=?", (conducteur_id,)) if conducteur_id else None
    db.log("Chauffeur désigné", f"{d['nom']} {d['prenom'] or ''} ({d['matricule'] or '-'})" if d else "aucun", pv_id)
    pv = db.q1("SELECT statut FROM pv WHERE id=?", (pv_id,))
    return identify(pv_id) if pv["statut"] in db.STATUTS_AUTO else pv["statut"]


def set_traitement(pv_id: int, traitement: str | None) -> str:
    """Impose la filière (DESIGNATION / PAIEMENT) ou revient à l'automatique (None)."""
    db.update("pv", pv_id, {"traitement_manuel": traitement})
    db.log("Filière modifiée", db.TRAITEMENTS.get(traitement, "automatique"), pv_id)
    return identify(pv_id)


# ---------------------------------------------------------------- filière payer et refacturer

def record_payment(pv_ids: list[int], date_paiement: str, mode: str, ref: str, montant: float | None = None) -> int:
    """Enregistre le paiement des avis (montant = montant de l'avis si non précisé) -> « Payé – à refacturer »."""
    n = 0
    for i in pv_ids:
        pv = db.q1("SELECT * FROM pv WHERE id=?", (i,))
        if not pv or pv["statut"] in ("CLOS", "ANNULE", "REFACTURE"):
            continue
        paye = montant if montant is not None else pv["montant"]
        db.update("pv", i, {"statut": "PAYE", "traitement": "PAIEMENT", "date_paiement": date_paiement,
                            "montant_paye": paye, "mode_paiement": mode, "ref_paiement": ref or None,
                            "updated_at": now()})
        db.log("Paiement enregistré", f"{paye} € – {mode} {ref or ''}".strip(), i)
        n += 1
    return n


def record_invoice(pv_ids: list[int], numero: str, date_facture: str) -> int:
    """N° de facture émise dans le logiciel de facturation -> « Refacturé – attente règlement ».
    Pour un avis dénoncé, marque seulement les frais de dossier comme facturés."""
    n = 0
    for i in pv_ids:
        pv = db.q1("SELECT * FROM pv WHERE id=?", (i,))
        if not pv:
            continue
        upd = {"facture_numero": numero, "date_facture": date_facture, "refacture": 1, "updated_at": now()}
        if pv["statut"] == "PAYE":
            upd["statut"] = "REFACTURE"
        db.update("pv", i, upd)
        db.log("Refacturé", f"facture {numero} du {parser.fmt_date(date_facture)}", i)
        n += 1
    return n


def record_settlement(pv_ids: list[int], date_reglement: str) -> int:
    """Règlement reçu du client -> « Clos »."""
    for i in pv_ids:
        db.update("pv", i, {"statut": "CLOS", "date_reglement": date_reglement, "updated_at": now()})
        db.log("Réglé par le client", parser.fmt_date(date_reglement), i)
    return len(pv_ids)


def frais_dossier(client_id: int | None) -> float | None:
    if not client_id:
        return None
    c = db.q1("SELECT frais_dossier FROM clients WHERE id=?", (client_id,))
    if c and c["frais_dossier"] is not None:
        return c["frais_dossier"]
    try:
        return float(db.setting("frais_dossier").replace(",", "."))
    except ValueError:
        return None


def reidentify_open() -> int:
    """Relance l'identification de tous les PV en attente (après un import de contrats p.ex.)."""
    rows = db.q("SELECT id FROM pv WHERE statut IN " + db.SQL_ECHEANCE)
    for r in rows:
        identify(r["id"])
    return len(rows)


# ---------------------------------------------------------------- dossier de dépôt

def scan_depot(progress=None) -> list[dict]:
    """Traite tous les fichiers présents dans le dossier de dépôt (scanner / copieur)."""
    folder = db.setting("dossier_depot")
    if not folder or not Path(folder).is_dir():
        return []
    done = config.sub("depot_traites")
    results = []
    for f in sorted(Path(folder).iterdir()):
        if f.is_file() and f.suffix.lower() in SUPPORTED:
            try:
                results += import_file(f, progress, move_to=done)
            except Exception as e:  # fichier en cours d'écriture, PDF corrompu...
                results.append({"pv_id": None, "numero": None, "statut": "ERREUR", "message": f"{f.name} : {e}"})
    return results


def acquire_from_scanner() -> Path | None:
    """Numérisation via WIA (boîte de dialogue Windows du scanner). Renvoie le fichier image créé."""
    import win32com.client
    dlg = win32com.client.Dispatch("WIA.CommonDialog")
    img = dlg.ShowAcquireImage(1, 0, 0, "{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}", False, True, False)
    if img is None:
        return None
    dest = config.sub("numerisations") / f"scan_{datetime.now():%Y%m%d_%H%M%S}.png"
    img.SaveFile(str(dest))
    return dest


# ---------------------------------------------------------------- tableau de bord

def stats() -> dict:
    today = date.today().isoformat()
    alerte = (date.today() + timedelta(days=int(db.setting("alerte_jours") or 10))).isoformat()
    s = {r["statut"]: r["n"] for r in db.q("SELECT statut, COUNT(*) n FROM pv GROUP BY statut")}
    s["urgents"] = db.q1(f"""SELECT COUNT(*) n FROM pv WHERE statut IN {db.SQL_ECHEANCE}
                            AND date_limite IS NOT NULL AND date_limite<=?""", (alerte,))["n"]
    s["depasses"] = db.q1(f"""SELECT COUNT(*) n FROM pv WHERE statut IN {db.SQL_ECHEANCE}
                             AND date_limite IS NOT NULL AND date_limite<?""", (today,))["n"]
    s["a_notifier"] = db.q1("""SELECT COUNT(*) n FROM pv WHERE statut IN ('EXPORTE','DEPOSE','PAYE','REFACTURE')
                               AND client_id IS NOT NULL AND date_notification IS NULL""")["n"]
    s["a_refacturer"] = db.q1("""SELECT COUNT(*) n FROM pv WHERE client_id IS NOT NULL AND refacture=0
                                 AND statut IN ('EXPORTE','DEPOSE','CLOS','PAYE')""")["n"]
    s["mois"] = db.q1("SELECT COUNT(*) n FROM pv WHERE created_at>=?", (date.today().replace(day=1).isoformat(),))["n"]
    s["total"] = db.q1("SELECT COUNT(*) n FROM pv")["n"]
    return s


def top_clients(limit=8):
    return db.q("""SELECT COALESCE(c.raison_sociale, c.nom || ' ' || COALESCE(c.prenom,'')) nom, COUNT(*) n
                   FROM pv JOIN clients c ON c.id=pv.client_id
                   WHERE pv.date_infraction >= date('now','-12 months')
                   GROUP BY c.id ORDER BY n DESC LIMIT ?""", (limit,))


def top_vehicules(limit=8):
    return db.q("""SELECT immatriculation, COUNT(*) n FROM pv
                   WHERE date_infraction >= date('now','-12 months') AND immatriculation IS NOT NULL
                   GROUP BY immatriculation ORDER BY n DESC LIMIT ?""", (limit,))


def client_label(c) -> str:
    if not c:
        return ""
    if c["type"] == "PM":
        return c["raison_sociale"] or ""
    return " ".join(x for x in (c["nom"], c["prenom"]) if x)


def clean_numero(s: str) -> str:
    return re.sub(r"\D", "", s or "")
