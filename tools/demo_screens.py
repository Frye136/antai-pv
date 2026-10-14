"""Crée un jeu de démonstration dans un dossier temporaire et capture chaque écran (contrôle visuel).
Usage : python tools/demo_screens.py <dossier_sortie> [avis.pdf ...]"""
import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="antaipv_demo_")
os.environ["APPDATA"] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import config, db, services  # noqa: E402

config.set_data_dir(os.path.join(TMP, "data"))
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
from app.ui.common import STYLE  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.pv_page import PvDialog  # noqa: E402

app.setStyle("Fusion")
app.setStyleSheet(STYLE)
db.set_setting("loueur_raison_sociale", "SARL LOCATION EXEMPLE")

veh = {}
for immat, marque in [("GA123BC", "VOLVO"), ("GL130CD", "RENAULT"), ("GJ906AB", "IVECO"), ("GC382MN", "MERCEDES"),
                      ("GH851YZ", "RENAULT"), ("GM264EF", "PEUGEOT"), ("GF623UV", "CITROEN")]:
    veh[immat] = db.insert("vehicules", {"immatriculation": immat, "marque": marque})
c1 = db.insert("clients", {"code_client": "C001", "type": "PM", "raison_sociale": "TRANSPORTS DUPONT",
                           "adresse": "12 rue de la Gare", "code_postal": "55100", "ville": "VERDUN",
                           "email": "compta@transports-dupont.example.com"})
c2 = db.insert("clients", {"code_client": "C002", "type": "PM", "raison_sociale": "BTP MEUSE",
                           "adresse": "ZA des Près", "code_postal": "55000", "ville": "BAR LE DUC"})
c3 = db.insert("clients", {"code_client": "P001", "type": "PP", "civilite": "M", "nom": "MARTIN", "prenom": "Paul",
                           "adresse": "3 rue Haute", "code_postal": "55110", "ville": "DUN SUR MEUSE"})
db.insert("contrats", {"numero": "LOC-22-014", "vehicule_id": veh["GA123BC"], "client_id": c1,
                       "date_debut": "2022-02-01 08:00", "date_fin": "2022-02-28 18:00"})
db.insert("contrats", {"numero": "LOC-21-310", "vehicule_id": veh["GL130CD"], "client_id": c2,
                       "date_debut": "2021-09-01 08:00", "date_fin": "2021-09-30 18:00"})
db.insert("contrats", {"numero": "LOC-21-288", "vehicule_id": veh["GC382MN"], "client_id": c3,
                       "date_debut": "2021-06-10 08:00", "date_fin": "2021-06-20 18:00"})

for pdf in sys.argv[2:]:
    print(services.import_file(pdf))

win = MainWindow()
win.resize(1480, 900)
win.show()
for i, (label, page) in enumerate(win.pages):
    win.go(i)
    if i == 1:
        win.pv_page.set_filter("Tous")
    app.processEvents()
    win.grab().save(str(OUT / f"{i}_{label.split()[-1]}.png"))
first = db.q1("SELECT id FROM pv ORDER BY id LIMIT 1")
if first:
    dlg = PvDialog(first["id"], win)
    dlg.show()
    app.processEvents()
    dlg.grab().save(str(OUT / "9_fiche.png"))
print("captures :", OUT)
