"""Notification des clients par e-mail : un mail par client regroupant ses avis (copies PDF jointes).
Envoi via SMTP ou via Outlook installé sur le poste."""
import base64
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from . import db, parser, plates, services


# --- mot de passe SMTP chiffré avec DPAPI (lié à la session Windows)
def protect(secret: str) -> str:
    if not secret:
        return ""
    import win32crypt
    blob = win32crypt.CryptProtectData(secret.encode("utf-8"), "AntaiPV", None, None, None, 0)
    return "dpapi:" + base64.b64encode(blob).decode()


def unprotect(value: str) -> str:
    if not value:
        return ""
    if not value.startswith("dpapi:"):
        return value
    import win32crypt
    return win32crypt.CryptUnprotectData(base64.b64decode(value[6:]), None, None, None, 0)[1].decode("utf-8")


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def build(client_id: int, pv_ids: list[int], traitement: str = "DESIGNATION") -> dict:
    """Prépare le mail (destinataires, sujet, corps, pièces jointes) pour un client et ses PV.
    Le corps dépend de la filière : désignation ANTAI ou avis payés et refacturés."""
    c = db.q1("SELECT * FROM clients WHERE id=?", (client_id,))
    pvs = [db.q1("SELECT * FROM pv WHERE id=?", (i,)) for i in pv_ids]
    ligne = db.setting("mail_ligne_pv")
    lignes = []
    frais = paye = 0.0
    for p in pvs:
        frais += p["frais_dossier"] or 0
        paye += (p["montant_paye"] if p["montant_paye"] is not None else p["montant"]) or 0
        lignes.append(ligne.format_map(_SafeDict(_pv_vars(p))))
    ctx = _SafeDict({
        "client": services.client_label(c), "raison_sociale": c["raison_sociale"] or "",
        "nom": c["nom"] or "", "prenom": c["prenom"] or "",
        "nb_pv": len(pvs), "liste_pv": "\n".join(lignes),
        "immatriculations": ", ".join(dict.fromkeys(plates.display(p["immatriculation"]) for p in pvs)),
        "frais_total": f"{frais:.2f}".replace(".", ","),
        "montant_total": f"{paye:.2f}".replace(".", ","),
        "loueur": db.setting("loueur_raison_sociale"),
        **(_pv_vars(pvs[0]) if len(pvs) == 1 else {}),
    })
    return {
        "to": c["email"] or "", "cc": c["email_cc"] or "", "bcc": db.setting("smtp_bcc"),
        "subject": db.setting("mail_sujet").format_map(ctx),
        "body": db.setting("mail_corps_paiement" if traitement == "PAIEMENT" else "mail_corps").format_map(ctx),
        "attachments": [p["fichier"] for p in pvs if p["fichier"] and Path(p["fichier"]).exists()],
    }


def _pv_vars(p) -> dict:
    return {
        "numero_avis": p["numero_avis"] or "", "immatriculation": plates.display(p["immatriculation"]),
        "date_infraction": parser.fmt_date(p["date_infraction"]), "heure_infraction": p["heure_infraction"] or "",
        "lieu": p["lieu"] or "", "nature": (p["nature"] or "").capitalize(),
        "montant": f"{p['montant']:.2f}".replace(".", ",") if p["montant"] else "",
        "date_avis": parser.fmt_date(p["date_avis"]),
        "frais_dossier": f"{p['frais_dossier']:.2f}".replace(".", ",") if p["frais_dossier"] else "",
    }


def _split(addrs: str) -> list[str]:
    return [a.strip() for a in (addrs or "").replace(",", ";").split(";") if a.strip()]


def send(mail: dict) -> None:
    if not _split(mail["to"]):
        raise ValueError("Le client n'a pas d'adresse e-mail.")
    if db.setting("mail_mode") == "outlook":
        _send_outlook(mail)
    else:
        _send_smtp(mail)


def _send_smtp(mail: dict) -> None:
    host = db.setting("smtp_host")
    if not host:
        raise ValueError("Serveur SMTP non configuré (Paramètres > E-mail).")
    port = int(db.setting("smtp_port") or 587)
    sec = db.setting("smtp_security")
    user = db.setting("smtp_user")
    pwd = unprotect(db.setting("smtp_password"))
    sender = db.setting("smtp_from") or user

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(_split(mail["to"]))
    if _split(mail["cc"]):
        msg["Cc"] = ", ".join(_split(mail["cc"]))
    msg["Subject"] = mail["subject"]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(mail["body"])
    for a in mail["attachments"]:
        msg.add_attachment(Path(a).read_bytes(), maintype="application", subtype="pdf", filename=Path(a).name)
    rcpt = _split(mail["to"]) + _split(mail["cc"]) + _split(mail["bcc"])

    ctx = ssl.create_default_context()
    if sec == "ssl":
        server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        if sec == "starttls":
            server.starttls(context=ctx)
    with server:
        if user:
            server.login(user, pwd)
        server.send_message(msg, from_addr=sender, to_addrs=rcpt)


def _send_outlook(mail: dict) -> None:
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        ol = win32com.client.Dispatch("Outlook.Application")
        m = ol.CreateItem(0)
        m.To = "; ".join(_split(mail["to"]))
        m.CC = "; ".join(_split(mail["cc"]))
        m.BCC = "; ".join(_split(mail["bcc"]))
        m.Subject = mail["subject"]
        m.Body = mail["body"]
        for a in mail["attachments"]:
            m.Attachments.Add(str(Path(a).resolve()))
        m.Send()
    finally:
        pythoncom.CoUninitialize()


def notify(pv_ids: list[int], progress=None) -> list[str]:
    """Envoie un mail par client. Renvoie la liste des messages (succès / erreurs)."""
    by_client: dict[tuple, list[int]] = {}
    for i in pv_ids:
        p = db.q1("SELECT id, client_id, traitement FROM pv WHERE id=?", (i,))
        if p and p["client_id"]:
            key = (p["client_id"], "PAIEMENT" if p["traitement"] == "PAIEMENT" else "DESIGNATION")
            by_client.setdefault(key, []).append(p["id"])
    out = []
    for n, ((cid, traitement), ids) in enumerate(by_client.items(), 1):
        c = db.q1("SELECT * FROM clients WHERE id=?", (cid,))
        label = services.client_label(c)
        if progress:
            progress(f"Envoi {n}/{len(by_client)} : {label}")
        try:
            mail = build(cid, ids, traitement)
            send(mail)
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            for i in ids:
                db.update("pv", i, {"date_notification": stamp})
                db.log("Client notifié", f"{label} <{mail['to']}>", i)
            out.append(f"✔ {label} : {len(ids)} avis envoyé(s) à {mail['to']}")
        except Exception as e:
            for i in ids:
                db.log("Échec notification", str(e), i)
            out.append(f"✘ {label} : {e}")
    skipped = len(pv_ids) - sum(len(v) for v in by_client.values())
    if skipped:
        out.append(f"— {skipped} avis sans client identifié ignoré(s)")
    return out


def test_connection() -> str:
    if db.setting("mail_mode") == "outlook":
        import win32com.client
        win32com.client.Dispatch("Outlook.Application")
        return "Outlook est accessible."
    host = db.setting("smtp_host")
    port = int(db.setting("smtp_port") or 587)
    sec = db.setting("smtp_security")
    ctx = ssl.create_default_context()
    server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) if sec == "ssl" else smtplib.SMTP(host, port, timeout=15)
    with server:
        if sec == "starttls":
            server.starttls(context=ctx)
        if db.setting("smtp_user"):
            server.login(db.setting("smtp_user"), unprotect(db.setting("smtp_password")))
    return "Connexion SMTP réussie."
