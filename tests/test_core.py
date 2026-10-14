"""Tests de bout en bout du moteur (sans interface).  Lancer :  python tests/test_core.py [chemin_avis.pdf]"""
import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="antaipv_test_")
os.environ["APPDATA"] = TMP  # configuration isolée
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import antai_export, config, db, parser, plates, services  # noqa: E402

config.set_data_dir(os.path.join(TMP, "data"))


def test_plates():
    assert plates.normalize("ab-123 cd") == "AB123CD"
    assert plates.display("AB123CD") == "AB-123-CD"
    assert "GA123BC" in plates.find_candidates("Immatriculation : GA-123-BC")
    assert plates.best_match("GA1Z3BC", ["GA123BC", "AB123CD"])[0] == "GA123BC"
    assert plates.best_match("ZZ999ZZ", ["GA123BC", "AB123CD"])[0] is None


SAMPLE = """Numéro de l'avis
de contravention
3999000017
M LE REPRESENTANT LEGAL
SARL LOCATION EXEMPLE
1 RUE DE LA PAIX
AVIS DE CONTRAVENTION
Date de l'avis de
contravention
18/02/2022
EXCES DE VITESSE INFERIEUR A 20 KM/H PAR CONDUCTEUR DE VEHICULE A MOTEUR -
Date / heure : le 15/02/2022 à 10h31
RD932A
pK/PR : 001.500
Direction : SENLIS vers COMPIEGNE
CHAMANT - 60300
Cette infraction a été constatée
Montant de l'amende
vous étes redevable de t'amende (art. L1210 du code
135 €
90 €
375 €
Immatriculation : GA-123-BC
d'une amende de 3750 euros (amende forfaitaire de 450
"""


def test_parser():
    r = parser.parse(SAMPLE, ["GA123BC"])
    assert r["numero_avis"] == "3999000017", r
    assert str(r["date_avis"]) == "2022-02-18", r
    assert str(r["date_infraction"]) == "2022-02-15" and r["heure_infraction"] == "10:31", r
    assert r["immatriculation"] == "GA123BC", r
    assert r["montant"] == 135.0, r
    assert r["lieu"].startswith("CHAMANT - 60300"), r
    assert r["nature"].startswith("EXCES DE VITESSE INFERIEUR"), r
    assert r["titulaire"] == "SARL LOCATION EXEMPLE", r
    assert parser.looks_like_new_avis(SAMPLE)
    assert not parser.looks_like_new_avis("Notice de paiement - avis de contravention - verso")


def test_regles_antai():
    assert antai_export.clean_text("Dupont & Fils + Co #2") == "Dupont ET Fils Co 2"
    assert antai_export.clean_pays("Belgique") == "BELGIQUE" and antai_export.clean_pays("fr") == "FRANCE"
    assert antai_export.clean_pays("Côte d’Ivoire") in antai_export.PAYS
    assert antai_export._civilite_code("Monsieur") == "M" and antai_export._civilite_code("Mme") == "MME"
    assert len(antai_export.DEFAULT_TEMPLATE["columns"]) == 18


def seed():
    db.set_setting("loueur_raison_sociale", "SARL LOCATION EXEMPLE")
    db.set_setting("loueur_siret", "123 456 789 00012")
    v = db.insert("vehicules", {"immatriculation": "GA123BC", "marque": "VOLVO"})
    pm = db.insert("clients", {"code_client": "C1", "type": "PM", "raison_sociale": "Transports Dupont",
                               "adresse": "4 bis avenue Jules Ferry", "code_postal": "8390", "ville": "Le Chesne",
                               "email": "x@example.com"})
    pp = db.insert("clients", {"code_client": "C2", "type": "PP", "civilite": "M", "nom": "Martin",
                               "prenom": "Paul", "date_naissance": "1980-05-01", "adresse": "1 rue Haute",
                               "code_postal": "55100", "ville": "Verdun"})
    db.insert("contrats", {"numero": "K1", "vehicule_id": v, "client_id": pm,
                           "date_debut": "2022-02-10 08:00", "date_fin": "2022-02-15 12:00"})
    db.insert("contrats", {"numero": "K2", "vehicule_id": v, "client_id": pp,
                           "date_debut": "2022-02-15 14:00", "date_fin": None})
    return pm, pp


def test_pipeline(pdf: str | None):
    pm, pp = seed()
    if pdf:
        res = services.import_file(pdf)
        assert res and res[0]["pv_id"], res
        pv_id = res[0]["pv_id"]
        print("  import réel :", res, dict(db.q1("SELECT numero_avis, immatriculation, date_avis, date_infraction,"
                                                 " heure_infraction, montant, lieu, statut, anomalie FROM pv WHERE id=?",
                                                 (pv_id,))))
        assert services.import_file(pdf)[0]["statut"] == "DOUBLON"
    else:
        pv_id = db.insert("pv", {"numero_avis": "3999000017", "immatriculation": "GA123BC",
                                 "date_avis": "2022-02-18", "date_infraction": "2022-02-15",
                                 "heure_infraction": "10:31"})
        services.identify(pv_id)
    pv = db.q1("SELECT * FROM pv WHERE id=?", (pv_id,))
    assert pv["client_id"] == pm and pv["statut"] == "A_DENONCER", dict(pv)
    assert pv["date_limite"] == "2022-04-04"

    # PV de l'après-midi -> particulier (2e contrat)
    pv2 = db.insert("pv", {"numero_avis": "1111111111", "immatriculation": "GA-1Z3-BC", "date_avis": "2022-02-20",
                           "date_infraction": "2022-02-15", "heure_infraction": "16:00"})
    assert services.identify(pv2) == "A_DENONCER"
    assert db.q1("SELECT client_id FROM pv WHERE id=?", (pv2,))["client_id"] == pp
    # Sans heure, ce jour-là deux contrats -> à vérifier
    pv3 = db.insert("pv", {"numero_avis": "2222222222", "immatriculation": "GA123BC", "date_avis": "2022-02-20",
                           "date_infraction": "2022-02-15"})
    assert services.identify(pv3) == "A_VERIFIER"
    assert services.set_contract(pv3, db.q1("SELECT id FROM contrats WHERE numero='K1'")["id"]) == "A_DENONCER"

    files = antai_export.generate([pv_id, pv2])
    text = files[0].read_bytes().decode("cp1252").splitlines()
    print("  CSV :", *text, sep="\n    ")
    official = ("Réf. Avis;Immatriculation;Date avis;Raison sociale désignant;SIRET;Civilité;Nom ou Raison sociale;"
                "Prénom;Date de naissance;Email;N° Permis de conduire;Permis délivré le;N° Voie;Nom Voie;"
                "Complément adresse;Code postal;Ville;Pays")
    assert text[0] == official, text[0]
    assert text[1] == ("3999000017;GA123BC;18/02/2022;SARL LOCATION EXEMPLE;12345678900012;SOCIETE;TRANSPORTS DUPONT;"
                       ";;x@example.com;;;4 bis;AVENUE JULES FERRY;;08390;LE CHESNE;FRANCE"), text[1]
    assert text[2] == ("1111111111;GA123BC;20/02/2022;SARL LOCATION EXEMPLE;12345678900012;M.;MARTIN;Paul;"
                       "01/05/1980;;;;1;RUE HAUTE;;55100;VERDUN;FRANCE"), text[2]
    assert db.q1("SELECT statut FROM pv WHERE id=?", (pv_id,))["statut"] == "EXPORTE"


def test_paiement():
    """Filière « payer et refacturer » : stationnement / FPS, paiement, facture, règlement."""
    from app import mailer, referentiel
    veh = db.q1("SELECT id FROM vehicules WHERE immatriculation='GA123BC'")["id"]
    pm = db.q1("SELECT id FROM clients WHERE code_client='C1'")["id"]
    db.execute("UPDATE contrats SET date_fin='2022-02-28 18:00' WHERE numero='K2'")  # location terminée
    db.insert("contrats", {"numero": "K9", "vehicule_id": veh, "client_id": pm,
                           "date_debut": "2026-03-01 08:00", "date_fin": "2026-03-31 18:00"})

    fps = db.insert("pv", {"numero_avis": "4000000001", "type": "FPS", "immatriculation": "GA123BC",
                           "date_avis": "2026-03-20", "date_infraction": "2026-03-10", "heure_infraction": "09:00",
                           "montant": 35.0})
    assert services.identify(fps) == "A_PAYER"
    r = db.q1("SELECT * FROM pv WHERE id=?", (fps,))
    assert r["traitement"] == "PAIEMENT" and r["client_id"] == pm and r["date_limite"] == "2026-06-18", dict(r)

    stat = db.insert("pv", {"numero_avis": "4000000002", "type": "AMENDE", "immatriculation": "GA123BC",
                            "date_avis": "2026-03-20", "date_infraction": "2026-03-12", "heure_infraction": "10:00",
                            "nature": "STATIONNEMENT GENANT D'UN VEHICULE SUR UN TROTTOIR", "montant": 135.0})
    assert services.identify(stat) == "A_PAYER"
    assert services.set_traitement(stat, "DESIGNATION") == "A_DENONCER"  # choix manuel
    assert services.set_traitement(stat, None) == "A_PAYER"              # retour à l'automatique

    vit = db.insert("pv", {"numero_avis": "4000000003", "type": "AMENDE", "immatriculation": "GA123BC",
                           "date_avis": "2026-03-20", "date_infraction": "2026-03-14", "heure_infraction": "11:00",
                           "nature": "EXCES DE VITESSE", "montant": 68.0})
    assert services.identify(vit) == "A_DENONCER"
    db.update("clients", pm, {"traitement_pv": "PAIEMENT"})  # ce client préfère qu'on paie
    assert services.identify(vit) == "A_PAYER"
    db.update("clients", pm, {"traitement_pv": None})

    assert services.record_payment([fps, stat], "2026-03-25", "Carte bancaire (en ligne)", "TX-1") == 2
    assert db.q1("SELECT statut, montant_paye FROM pv WHERE id=?", (stat,))["montant_paye"] == 135.0
    mail = mailer.build(pm, [fps, stat], "PAIEMENT")
    assert "170,00 €" in mail["body"] and "réglées par nos soins" in mail["body"], mail["body"]

    out = os.path.join(TMP, "a_facturer.xlsx")
    n = referentiel.export_refacturation(out, mark=True)
    assert n >= 2 and db.q1("SELECT statut FROM pv WHERE id=?", (fps,))["statut"] == "REFACTURE"
    services.record_invoice([fps, stat], "FA-2026-0042", "2026-03-31")
    assert db.q1("SELECT facture_numero FROM pv WHERE id=?", (stat,))["facture_numero"] == "FA-2026-0042"
    services.record_settlement([fps, stat], "2026-04-15")
    assert db.q1("SELECT statut FROM pv WHERE id=?", (fps,))["statut"] == "CLOS"

    # base d'une version précédente : « Non désignable » -> « À payer »
    old = db.insert("pv", {"numero_avis": "4000000009", "statut": "NON_DESIGNABLE"})
    db._migrate(db.get())
    assert db.q1("SELECT statut, traitement FROM pv WHERE id=?", (old,))["statut"] == "A_PAYER"


def test_updater():
    """Comparaison de versions et lecture d'une release GitHub (réseau simulé)."""
    import hashlib
    import json
    from app import updater
    assert updater.parse_version("v1.10.0") > updater.parse_version("1.9.3")
    assert updater.parse_version("v" + config.VERSION) == updater.parse_version(config.VERSION)

    exe = b"MZ fake exe"
    release = {"tag_name": "v99.0.0", "body": "Nouveautés", "html_url": "https://github.com/x/y/releases/v99.0.0",
               "assets": [{"name": "AntaiPV.exe", "browser_download_url": "https://x/AntaiPV.exe"},
                          {"name": "AntaiPV.exe.sha256", "browser_download_url": "https://x/AntaiPV.exe.sha256"}]}
    original = updater._get
    try:
        updater._get = lambda url, accept=None: json.dumps(release).encode()
        info = updater.check()
        assert info and info["version"] == "99.0.0" and info["sha_url"].endswith(".sha256"), info
        release["tag_name"] = "v" + config.VERSION
        assert updater.check() is None  # déjà à jour
    finally:
        updater._get = original
    assert hashlib.sha256(exe).hexdigest()  # l'empreinte publiée par la CI est un sha256 hexadécimal


if __name__ == "__main__":
    test_plates()
    test_parser()
    test_regles_antai()
    test_pipeline(sys.argv[1] if len(sys.argv) > 1 else None)
    test_paiement()
    test_updater()
    print("OK — tous les tests passent")
