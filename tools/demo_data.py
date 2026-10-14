"""Jeu de données de démonstration : 4 clients, 20 véhicules, contrats couvrant les avis réels des archives.

    python tools/demo_data.py               -> crée demo/clients.xlsx, demo/vehicules.xlsx, demo/contrats.xlsx
    python tools/demo_data.py --importer    -> crée les fichiers et les importe dans le dossier de données configuré

Toutes les données sont fictives. Les contrats couvrent des périodes passées et en cours, dont un véhicule loué à
deux clients le même jour (départagés par l'heure) et un contrat qui désigne le conducteur nommé.
Les fiches portent la note « DÉMO » pour pouvoir les retrouver / supprimer.
"""
import sys
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import referentiel  # noqa: E402

DEMO = "DÉMO"

CLIENTS = [
    # code, type, raison sociale, siret, civ, nom, prénom, naissance, lieu, permis, délivré, adresse, cpl, cp, ville, pays, email
    ("C001", "PM", "TRANSPORTS DUPONT", "41234567800012", "", "", "", "", "", "", "",
     "12 rue de la Gare", "", "55100", "VERDUN", "FRANCE", "compta@transports-dupont.example.com"),
    ("C002", "PM", "BTP MEUSE", "52345678900027", "", "", "", "", "", "", "",
     "ZA des Prés", "Bâtiment B", "55000", "BAR-LE-DUC", "FRANCE", "flotte@btp-meuse.example.com"),
    ("C003", "PM", "AMBULANCES DES ARDENNES", "63456789000034", "", "", "", "", "", "", "",
     "4 bis avenue Jean Jaurès", "", "08200", "SEDAN", "FRANCE", "direction@ambulances-ardennes.example.com"),
    ("P001", "PP", "", "", "M", "MARTIN", "Paul", "01/05/1980", "VERDUN", "800555100123", "15/06/1999",
     "3 rue Haute", "", "55110", "DUN-SUR-MEUSE", "FRANCE", "paul.martin@example.com"),
]

VEHICULES = [
    ("GA-123-BC", "VOLVO", "FH 500", "Tracteur"), ("GB-214-KL", "LECITRAILER", "Semi-remorque", "Remorque"),
    ("GC-382-MN", "MERCEDES", "Actros", "Tracteur"), ("GD-457-PR", "RENAULT", "Master", "Utilitaire"),
    ("GE-519-ST", "IVECO", "Daily", "Utilitaire"), ("GF-623-UV", "CITROËN", "Jumper", "Utilitaire"),
    ("GG-748-WX", "PEUGEOT", "Boxer", "Utilitaire"), ("GH-851-YZ", "RENAULT", "Trafic", "Utilitaire"),
    ("GJ-906-AB", "IVECO", "Stralis", "Porteur"), ("GL-130-CD", "RENAULT", "Kangoo", "Utilitaire"),
    ("GM-264-EF", "PEUGEOT", "Partner", "Utilitaire"), ("GN-371-GH", "FORD", "Transit", "Utilitaire"),
    ("GP-482-JK", "VOLVO", "FL", "Porteur"), ("GQ-593-LM", "SCANIA", "R450", "Tracteur"),
    ("GR-604-NP", "IVECO", "Stralis", "Porteur"),
    ("GK-112-AB", "RENAULT", "Master", "Utilitaire"), ("GM-245-CD", "MERCEDES", "Sprinter", "Utilitaire"),
    ("GN-378-EF", "VOLKSWAGEN", "Crafter", "Utilitaire"), ("GP-401-GH", "TOYOTA", "Proace", "Utilitaire"),
    ("GQ-534-JK", "DACIA", "Duster", "VL"),
]

# n°, plaque, client, début, fin, conducteur (nom, prénom, naissance, lieu, permis, adresse, cp, ville), désigner cond.
NO_DRIVER = ("",) * 8
CONTRATS = [
    ("LOC-21-001", "GD-457-PR", "C001", "04/01/2021 08:00", "31/03/2021 18:00", NO_DRIVER, 0),
    ("LOC-21-014", "GE-519-ST", "C002", "15/02/2021 08:00", "30/04/2021 18:00", NO_DRIVER, 0),
    ("LOC-21-022", "GF-623-UV", "C003", "01/04/2021 08:00", "30/06/2021 18:00", NO_DRIVER, 0),
    ("LOC-21-031", "GC-382-MN", "P001", "10/06/2021 09:00", "20/06/2021 18:00", NO_DRIVER, 0),
    ("LOC-21-035", "GG-748-WX", "P001", "01/07/2021 09:00", "15/07/2021 18:00", NO_DRIVER, 0),
    ("LOC-21-040", "GH-851-YZ", "C001", "01/07/2021 08:00", "31/12/2021 18:00", NO_DRIVER, 0),
    ("LOC-21-052", "GL-130-CD", "C003", "15/08/2021 08:00", "30/09/2021 18:00", NO_DRIVER, 0),
    ("LOC-21-058", "GJ-906-AB", "C002", "01/09/2021 08:00", "31/10/2021 18:00", NO_DRIVER, 0),
    ("LOC-21-061", "GN-371-GH", "C003", "15/09/2021 08:00", "15/11/2021 18:00",
     ("LEROY", "Julie", "12/03/1990", "SEDAN", "900808100456", "7 rue du Moulin", "08200", "SEDAN"), 1),
    ("LOC-21-063", "GA-123-BC", "C002", "01/10/2021 08:00", "10/10/2021 18:00", NO_DRIVER, 0),
    ("LOC-21-066", "GM-264-EF", "C001", "01/10/2021 08:00", "31/10/2021 18:00", NO_DRIVER, 0),
    ("LOC-21-077", "GP-482-JK", "C001", "15/11/2021 08:00", "15/01/2022 18:00", NO_DRIVER, 0),
    ("LOC-21-080", "GQ-593-LM", "C002", "01/12/2021 08:00", "31/01/2022 18:00", NO_DRIVER, 0),
    # même véhicule, deux locataires le même jour : l'heure de l'infraction (10h31) départage
    ("LOC-22-005", "GA-123-BC", "C001", "01/02/2022 08:00", "15/02/2022 12:00", NO_DRIVER, 0),
    ("LOC-22-006", "GA-123-BC", "P001", "15/02/2022 14:00", "28/02/2022 18:00", NO_DRIVER, 0),
    ("LOC-22-009", "GC-382-MN", "C003", "01/02/2022 08:00", "31/03/2022 18:00", NO_DRIVER, 0),
    ("LOC-26-018", "GB-214-KL", "C002", "01/05/2026 07:00", "31/05/2026 19:00", NO_DRIVER, 0),
    # locations en cours
    ("LOC-26-101", "GK-112-AB", "C001", "01/09/2026 08:00", "", NO_DRIVER, 0),
    ("LOC-26-102", "GM-245-CD", "C001", "01/09/2026 08:00", "", NO_DRIVER, 0),
    ("LOC-26-103", "GN-378-EF", "C002", "15/09/2026 08:00", "", NO_DRIVER, 0),
    ("LOC-26-104", "GP-401-GH", "C003", "01/10/2026 08:00", "31/12/2026 18:00", NO_DRIVER, 0),
    ("LOC-26-105", "GQ-534-JK", "P001", "10/10/2026 10:00", "20/10/2026 10:00", NO_DRIVER, 0),
    ("LOC-26-106", "GA-123-BC", "C003", "01/10/2026 08:00", "", NO_DRIVER, 0),
    ("LOC-26-107", "GB-214-KL", "C002", "01/06/2026 07:00", "", NO_DRIVER, 0),
]


def _sheet(path: Path, table: str, rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = table
    ws.append([label for _, label, _ in referentiel.FIELDS[table]])
    for r in rows:
        ws.append(r)
    referentiel._style_header(ws, len(referentiel.FIELDS[table]))
    for col in ws.iter_cols(min_row=2):  # tout en texte : codes postaux, n° de permis, SIRET…
        for c in col:
            c.number_format = "@"
    wb.save(path)


def build(out: Path) -> dict[str, Path]:
    out.mkdir(exist_ok=True)
    files = {t: out / f"{t}.xlsx" for t in ("clients", "vehicules", "contrats")}
    _sheet(files["clients"], "clients",
           [[*c[:2], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9], c[10], c[11], c[12], c[13], c[14], c[15],
             c[16], "", "", "", "", DEMO, "1"] for c in CLIENTS])
    _sheet(files["vehicules"], "vehicules", [[p, m, mo, cat, "", DEMO, "1"] for p, m, mo, cat in VEHICULES])
    _sheet(files["contrats"], "contrats",
           [[n, p, c, d, f, *drv, str(des), DEMO] for n, p, c, d, f, drv, des in CONTRATS])
    return files


if __name__ == "__main__":
    files = build(ROOT / "demo")
    print("Fichiers :", *files.values(), sep="\n  ")
    if "--importer" in sys.argv:
        from app import config, db, services
        print("Base :", config.db_path())
        for table in ("clients", "vehicules", "contrats"):
            res = referentiel.import_file(table, str(files[table]))
            print(f"  {table:10} {res['created']} créés, {res['updated']} mis à jour, erreurs : {res['errors'] or 'aucune'}")
        n = services.reidentify_open()
        print(f"  {n} avis en cours ré-analysés")
        for r in db.q("SELECT numero_avis, immatriculation, statut, anomalie FROM pv"):
            print("   ", dict(r))
