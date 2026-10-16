"""Tableau de bord, référentiel (clients / véhicules / contrats), lots ANTAI, journal."""
import webbrowser
from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .. import db, parser, plates, referentiel, services
from .common import (RecordDialog, RowsModel, f_bool, f_date, f_dt, f_money, f_plate, f_statut, make_table,
                     open_path, selected_rows, STATUT_COLORS)

ANTAI_PRO_URL = "https://entreprises.antai.gouv.fr/"


def page_header(title: str, *buttons) -> QHBoxLayout:
    lab = QLabel(title)
    lab.setObjectName("pageTitle")
    h = QHBoxLayout()
    h.addWidget(lab)
    h.addStretch()
    for b in buttons:
        h.addWidget(b)
    return h


def button(text, fn, primary=False, accent=False) -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setProperty("primary", True)
    if accent:
        b.setProperty("accent", True)
    b.clicked.connect(fn)
    return b


class Card(QFrame):
    def __init__(self, label, color, on_click):
        super().__init__()
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.on_click = on_click
        self.value = QLabel("0")
        self.value.setObjectName("cardValue")
        self.value.setStyleSheet(f"color:{color}")
        lab = QLabel(label)
        lab.setObjectName("cardLabel")
        lab.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.addWidget(self.value)
        lay.addWidget(lab)

    def mousePressEvent(self, e):
        self.on_click()


class DashboardPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        grid = QGridLayout()
        grid.setSpacing(12)
        defs = [
            ("A_VERIFIER", "À vérifier", "#B7791F", "À traiter (vérifier / non identifiés)"),
            ("NON_IDENTIFIE", "Locataire non trouvé", "#C53030", "À traiter (vérifier / non identifiés)"),
            ("A_DENONCER", "Prêts à dénoncer", "#1E4E8C", "Prêts à dénoncer"),
            ("EXPORTE", "Exportés – à déposer sur l'ANTAI", "#5B3E96", "Exportés, en attente de dépôt"),
            ("urgents", "Échéance proche", "#C53030", "Échéance proche"),
            ("A_PAYER", "À payer (stationnement, FPS…)", "#B45309", "À payer"),
            ("PAYE", "Payés – à refacturer", "#6B4F1F", "Payés – à refacturer"),
            ("REFACTURE", "Refacturés – attente règlement", "#4B5563", "Refacturés – attente de règlement"),
            ("a_notifier", "Clients à notifier", "#2F855A", "Clients à notifier"),
            ("depasses", "Échéance dépassée", "#7B1E1E", "Échéance proche"),
        ]
        self.cards = {}
        for i, (key, label, color, flt) in enumerate(defs):
            c = Card(label, color, lambda f=flt: self.main.show_pv(f))
            self.cards[key] = c
            grid.addWidget(c, i // 5, i % 5)

        self.deadlines = RowsModel([("date_limite", "Échéance", f_date), ("statut", "Statut", f_statut),
                                    ("numero_avis", "N° avis", None), ("immatriculation", "Immat.", f_plate),
                                    ("client", "Locataire", None)])
        self.deadlines.color_fn = lambda r, k: STATUT_COLORS.get(r["statut"]) if k == "statut" else None
        v1, _ = make_table(self.deadlines, self)
        self.clients = RowsModel([("nom", "Client", None), ("n", "Avis (12 mois)", None)])
        v2, _ = make_table(self.clients, self)
        self.vehicles = RowsModel([("immatriculation", "Véhicule", f_plate), ("n", "Avis (12 mois)", None)])
        v3, _ = make_table(self.vehicles, self)
        for v, w in ((v1, 110), (v2, 230), (v3, 110)):
            v.setColumnWidth(0, w)

        def box(title, w):
            g = QGroupBox(title)
            l = QVBoxLayout(g)
            l.addWidget(w)
            return g

        bottom = QHBoxLayout()
        bottom.addWidget(box("Prochaines échéances (désignation ou paiement)", v1), 3)
        bottom.addWidget(box("Clients les plus verbalisés", v2), 2)
        bottom.addWidget(box("Véhicules les plus verbalisés", v3), 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addLayout(page_header("Tableau de bord", button("🚐  Nouvelle location", self.new_location),
                                  button("📥  Importer des scans…", main.pv_page.import_files, primary=True)))
        lay.addWidget(main.pv_page.make_drop_zone())
        lay.addLayout(grid)
        lay.addLayout(bottom, 1)

    def new_location(self):
        from .location_form import LocationDialog
        if LocationDialog(self).exec():
            self.main.refresh_all()

    def refresh(self):
        s = services.stats()
        for k, c in self.cards.items():
            c.value.setText(str(s.get(k, 0)))
        self.deadlines.set_rows(db.q("""SELECT pv.*, COALESCE(c.raison_sociale, c.nom) client FROM pv
                                        LEFT JOIN clients c ON c.id=pv.client_id
                                        WHERE pv.statut IN """ + db.SQL_ECHEANCE + """
                                        AND pv.date_limite IS NOT NULL ORDER BY pv.date_limite LIMIT 30"""))
        self.clients.set_rows(services.top_clients(15))
        self.vehicles.set_rows(services.top_vehicules(15))


REF_COLUMNS = {
    "clients": [("code_client", "Code", None), ("type", "Type", None), ("nom_affiche", "Nom / Raison sociale", None),
                ("siret", "SIRET", None), ("ville", "Ville", None), ("email", "E-mail", None),
                ("telephone", "Téléphone", None), ("nb_pv", "Avis", None), ("complet", "Fiche ANTAI", None)],
    "vehicules": [("immatriculation", "Immatriculation", f_plate), ("marque", "Marque", None), ("modele", "Modèle", None),
                  ("categorie", "Catégorie", None), ("propre", "Société", lambda v, r: "Oui" if v else ""),
                  ("chauffeur", "Chauffeur habituel", None), ("contrat_en_cours", "Loué à (aujourd'hui)", None),
                  ("nb_pv", "Avis", None), ("actif", "Actif", f_bool)],
    "conducteurs": [("matricule", "Matricule", None), ("nom_affiche", "Nom", None), ("date_naissance", "Né(e) le", f_date),
                    ("num_permis", "Permis", None), ("ville", "Ville", None), ("telephone", "Téléphone", None),
                    ("nb_pv", "Avis", None), ("complet", "Fiche ANTAI", None), ("actif", "Actif", f_bool)],
    "contrats": [("numero", "N° contrat", None), ("immatriculation", "Véhicule", f_plate), ("client", "Client", None),
                 ("date_debut", "Début", f_dt), ("date_fin", "Fin", lambda v, r: f_dt(v) if v else "en cours"),
                 ("conducteur", "Conducteur", None), ("designer_conducteur", "Désigner conducteur", f_bool)],
}
REF_SQL = {
    "clients": """SELECT c.*, COALESCE(c.raison_sociale, TRIM(COALESCE(c.nom,'')||' '||COALESCE(c.prenom,''))) nom_affiche,
                         (SELECT COUNT(*) FROM pv WHERE pv.client_id=c.id) nb_pv FROM clients c
                  ORDER BY nom_affiche""",
    "conducteurs": """SELECT d.*, TRIM(COALESCE(d.nom,'')||' '||COALESCE(d.prenom,'')) nom_affiche,
                             (SELECT COUNT(*) FROM pv WHERE pv.conducteur_id=d.id) nb_pv
                      FROM conducteurs d ORDER BY d.nom, d.prenom""",
    "vehicules": """SELECT v.*, (SELECT COUNT(*) FROM pv WHERE pv.vehicule_id=v.id) nb_pv,
                       (SELECT TRIM(COALESCE(d.nom,'')||' '||COALESCE(d.prenom,'')) FROM conducteurs d
                        WHERE d.id=v.conducteur_id) chauffeur,
                       (SELECT COALESCE(c.raison_sociale, c.nom) FROM contrats k JOIN clients c ON c.id=k.client_id
                        WHERE k.vehicule_id=v.id AND k.date_debut<=datetime('now','localtime')
                        AND (k.date_fin IS NULL OR k.date_fin>=datetime('now','localtime')) LIMIT 1) contrat_en_cours
                    FROM vehicules v ORDER BY v.immatriculation""",
    "contrats": """SELECT k.*, v.immatriculation, COALESCE(c.raison_sociale, TRIM(COALESCE(c.nom,'')||' '||COALESCE(c.prenom,''))) client,
                          TRIM(COALESCE(k.cond_nom,'')||' '||COALESCE(k.cond_prenom,'')) conducteur
                   FROM contrats k JOIN vehicules v ON v.id=k.vehicule_id JOIN clients c ON c.id=k.client_id
                   ORDER BY k.date_debut DESC""",
}
TITLES = {"clients": "Clients", "vehicules": "Véhicules", "contrats": "Contrats de location",
          "conducteurs": "Chauffeurs de la société"}


class ReferentielPage(QWidget):
    def __init__(self, main, table: str):
        super().__init__()
        self.main, self.table = main, table
        self.model = RowsModel(REF_COLUMNS[table])
        if table in ("clients", "conducteurs"):
            self.model.color_fn = lambda r, k: (("#9B1C1C", "#FDE2E2") if k == "complet" and r["complet"] != "OK" else None)
        self.view, self.proxy = make_table(self.model, self)
        self.view.doubleClicked.connect(self.edit)
        search = QLineEdit()
        search.setPlaceholderText("Rechercher…")
        search.setClearButtonEnabled(True)
        search.textChanged.connect(self.proxy.setFilterFixedString)
        self.count = QLabel()
        self.count.setObjectName("hint")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        actions = [] if table == "conducteurs" else [button("🚐 Nouvelle location", self.new_location, primary=True)]
        lay.addLayout(page_header(TITLES[table], *actions,
                                  button("＋ Nouveau", self.new, primary=table == "conducteurs"),
                                  button("Modifier", self.edit_selected),
                                  button("Supprimer", self.delete), button("📥 Importer Excel / CSV…", self.import_file),
                                  button("Modèle d'import", self.model_file), button("Exporter…", self.export)))
        bar = QHBoxLayout()
        bar.addWidget(search, 1)
        bar.addWidget(self.count)
        lay.addLayout(bar)
        lay.addWidget(self.view, 1)
        hints = {
            "clients": "Personne morale : raison sociale + adresse suffisent à la désignation. "
                       "Particulier : nom, prénom, date de naissance, adresse (et n° de permis recommandé).",
            "vehicules": "Les immatriculations sont normalisées (AB-123-CD ↔ AB123CD). « Société » : véhicule de votre "
                         "parc conduit par vos salariés — l'avis désigne le chauffeur (le chauffeur habituel est proposé).",
            "conducteurs": "Salariés qui conduisent les véhicules de la société : désignés directement à l'ANTAI "
                           "(civilité, nom, prénom, date de naissance, adresse et n° de permis).",
            "contrats": "Le locataire désigné est celui du contrat en cours à la date et l'heure de l'infraction. "
                        "Une date de fin sans heure couvre toute la journée.",
        }
        h = QLabel(hints[table])
        h.setObjectName("hint")
        lay.addWidget(h)
        self.view.setColumnWidth(0, 120)
        if table in ("clients", "contrats"):
            self.view.setColumnWidth(2, 260)
        if table == "conducteurs":
            self.view.setColumnWidth(1, 220)

    def refresh(self):
        rows = [dict(r) for r in db.q(REF_SQL[self.table])]
        if self.table in ("clients", "conducteurs"):
            from .. import antai_export
            for r in rows:
                d = dict(r, type="PP") if self.table == "conducteurs" else r
                miss = antai_export.missing_fields(d, {"numero_avis": "0000000000", "immatriculation": "X",
                                                       "date_avis": "X", "titulaire": "X"})
                miss += antai_export.warnings(d) and ["n° de permis"]
                r["complet"] = "OK" if not miss else "Manque : " + ", ".join(miss)
        self.model.set_rows(rows)
        self.count.setText(f"{len(rows)} enregistrement(s)")

    def new(self):
        if RecordDialog(self.table, None, self).exec():
            self._after_change()

    def new_location(self):
        """Véhicule + client + contrat en un seul formulaire (pré-rempli avec la ligne sélectionnée)."""
        from .location_form import LocationDialog
        sel = selected_rows(self.view, self.proxy, self.model)
        kw = {}
        if sel and self.table == "vehicules":
            kw["immat"] = sel[0]["immatriculation"]
        elif sel and self.table == "clients":
            kw["client_id"] = sel[0]["id"]
        if LocationDialog(self, **kw).exec():
            self.main.refresh_all()

    def edit(self, index):
        row = self.model.row(self.proxy.mapToSource(index).row())
        rec = db.q1(f"SELECT * FROM {self.table} WHERE id=?", (row["id"],))
        if RecordDialog(self.table, dict(rec), self).exec():
            self._after_change()

    def edit_selected(self):
        idx = self.view.selectionModel().selectedRows()
        if idx:
            self.edit(idx[0])

    def _after_change(self):
        # un nouveau contrat / une fiche complétée peut débloquer des avis en attente
        services.reidentify_open()
        self.main.refresh_all()

    def delete(self):
        rows = selected_rows(self.view, self.proxy, self.model)
        if not rows:
            return
        if QMessageBox.warning(self, "Supprimer", f"Supprimer {len(rows)} enregistrement(s) ?",
                               QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        errors = 0
        for r in rows:
            if self.table == "conducteurs" and db.q1(
                    "SELECT (SELECT COUNT(*) FROM pv WHERE conducteur_id=?) + "
                    "(SELECT COUNT(*) FROM vehicules WHERE conducteur_id=?) n", (r["id"], r["id"]))["n"]:
                errors += 1  # chauffeur désigné sur des avis ou chauffeur habituel : le rendre inactif plutôt
                continue
            try:
                db.execute(f"DELETE FROM {self.table} WHERE id=?", (r["id"],))
            except Exception:
                errors += 1
        if errors:
            QMessageBox.warning(self, "Supprimer", f"{errors} enregistrement(s) utilisé(s) ailleurs (contrats / avis / "
                                                   "véhicules) n'ont pas été supprimés. Décochez « Actif » pour les masquer.")
        self.main.refresh_all()

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, f"Importer – {TITLES[self.table]}", "",
                                              "Excel ou CSV (*.xlsx *.xlsm *.csv *.txt)")
        if not path:
            return
        try:
            res = referentiel.import_file(self.table, path)
        except Exception as e:
            QMessageBox.warning(self, "Import", str(e))
            return
        n = services.reidentify_open()
        self.main.refresh_all()
        msg = (f"{res['created']} créé(s), {res['updated']} mis à jour.\n\nColonnes reconnues :\n  "
               + "\n  ".join(res["colonnes"]))
        if res["errors"]:
            msg += f"\n\n{len(res['errors'])} erreur(s) :\n" + "\n".join(res["errors"][:20])
        msg += f"\n\n{n} avis en cours ré-analysés."
        QMessageBox.information(self, "Import terminé", msg)

    def model_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Modèle d'import", f"modele_{self.table}.xlsx", "Excel (*.xlsx)")
        if path:
            referentiel.write_model(self.table, path)
            open_path(path)

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Exporter", f"{self.table}_{date.today():%Y%m%d}.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        fields = referentiel.FIELDS[self.table]
        ws.append([l for _, l, _ in fields])
        for r in db.q(f"SELECT * FROM {self.table}"):
            vals = []
            for col, _, kind in fields:
                v = r[col]
                if kind == "vehicule":
                    v = (db.q1("SELECT immatriculation FROM vehicules WHERE id=?", (v,)) or {"immatriculation": ""})["immatriculation"]
                elif kind == "client":
                    v = (db.q1("SELECT code_client FROM clients WHERE id=?", (v,)) or {"code_client": ""})["code_client"]
                elif kind == "conducteur":
                    v = (db.q1("SELECT matricule FROM conducteurs WHERE id=?", (v,)) or {"matricule": ""})["matricule"]
                vals.append(v)
            ws.append(vals)
        wb.save(path)
        open_path(path)


class LotsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.model = RowsModel([("created_at", "Créé le", f_dt), ("nom", "Fichier", None), ("nb_pv", "Avis", None),
                                ("depose_le", "Déposé sur l'ANTAI le", f_dt), ("notes", "Notes", None)])
        self.model.color_fn = lambda r, k: (("#5B3E96", "#EDE5FB") if k == "depose_le" and not r["depose_le"] else
                                            ("#1F6B3A", "#DDF3E4") if k == "depose_le" else None)
        self.view, self.proxy = make_table(self.model, self)
        self.view.doubleClicked.connect(lambda _: self.open_file())
        QShortcut(QKeySequence.Delete, self.view, self.delete)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addLayout(page_header("Lots ANTAI",
                                  button("🌐 Ouvrir l'espace entreprises ANTAI", lambda: webbrowser.open(ANTAI_PRO_URL), accent=True),
                                  button("Ouvrir le fichier", self.open_file), button("Ouvrir le dossier", self.open_folder),
                                  button("✔ Marquer comme déposé", self.mark_deposited, primary=True),
                                  button("🗑 Supprimer…", self.delete)))
        steps = QLabel("<b>Procédure :</b> 1. Générez le CSV depuis « Contraventions » → 2. Connectez-vous à l'espace "
                       "entreprises ANTAI, rubrique désignation, et déposez le fichier → 3. Revenez ici et marquez le lot "
                       "comme déposé → 4. Notifiez les clients.")
        steps.setWordWrap(True)
        steps.setObjectName("hint")
        lay.addWidget(steps)
        lay.addWidget(self.view, 1)
        self.detail = RowsModel([("numero_avis", "N° avis", None), ("immatriculation", "Immat.", f_plate),
                                 ("client", "Désigné", None), ("statut", "Statut", f_statut),
                                 ("date_notification", "Notifié", None)])
        dv, _ = make_table(self.detail, self)
        g = QGroupBox("Avis du lot sélectionné")
        QVBoxLayout(g).addWidget(dv)
        lay.addWidget(g, 1)
        self.view.selectionModel().selectionChanged.connect(self._show_detail)
        self.view.setColumnWidth(0, 140)
        self.view.setColumnWidth(1, 330)

    def refresh(self):
        rows = [dict(r) for r in db.q("SELECT * FROM exports ORDER BY id DESC")]
        for r in rows:
            r["nom"] = (r["fichier"] or "").replace("\\", "/").split("/")[-1]
        self.model.set_rows(rows)
        self._show_detail()

    def _current(self):
        rows = selected_rows(self.view, self.proxy, self.model)
        return rows[0] if rows else None

    def _show_detail(self, *_):
        lot = self._current()
        self.detail.set_rows(db.q("""SELECT pv.*, COALESCE(c.raison_sociale, c.nom||' '||COALESCE(c.prenom,'')) client
                                     FROM pv LEFT JOIN clients c ON c.id=pv.client_id WHERE export_id=?""",
                                  (lot["id"],)) if lot else [])

    def open_file(self):
        lot = self._current()
        if lot:
            open_path(lot["fichier"])

    def open_folder(self):
        from .. import config
        open_path(config.sub("exports"))

    def mark_deposited(self):
        lot = self._current()
        if not lot:
            return
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        db.update("exports", lot["id"], {"depose_le": stamp})
        for r in db.q("SELECT id FROM pv WHERE export_id=? AND statut='EXPORTE'", (lot["id"],)):
            db.update("pv", r["id"], {"statut": "DEPOSE", "updated_at": services.now()})
            db.log("Déposé sur l'ANTAI", lot["nom"], r["id"])
        self.main.refresh_all()
        if QMessageBox.question(self, "Lot déposé", "Lot marqué comme déposé.\n\nNotifier maintenant les clients concernés ?") \
                == QMessageBox.Yes:
            self.main.show_pv("Clients à notifier")

    def _context_menu(self, pos):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        if not self.view.selectionModel().isRowSelected(index.row(), index.parent()):
            self.view.selectRow(index.row())
        n = len(selected_rows(self.view, self.proxy, self.model))
        menu = QMenu(self)
        if n == 1:
            menu.addAction("Ouvrir le fichier", self.open_file)
            menu.addAction("✔ Marquer comme déposé", self.mark_deposited)
            menu.addSeparator()
        menu.addAction("🗑  Supprimer le lot…" if n == 1 else f"🗑  Supprimer les {n} lots…", self.delete)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def delete(self):
        lots = selected_rows(self.view, self.proxy, self.model)
        if not lots:
            QMessageBox.information(self, "Supprimer", "Sélectionnez d'abord le ou les lots à supprimer.")
            return
        deposes = [l for l in lots if l["depose_le"]]
        lignes = [f"• {l['nom']} – {l['nb_pv']} avis – "
                  + (f"déposé le {f_dt(l['depose_le'])}" if l["depose_le"] else "non déposé") for l in lots[:12]]
        info = "\n".join(lignes)
        if len(lots) - len(deposes):
            info += ("\n\nLots non déposés : leurs avis repassent « À dénoncer » et pourront être inclus dans un "
                     "nouveau CSV (à faire notamment si l'ANTAI a refusé le fichier).")
        if deposes:
            info += ("\n\n⚠ Lots déjà déposés à l'ANTAI : leurs avis restent « Déposé ANTAI ». La suppression "
                     "n'annule pas les désignations auprès de l'ANTAI.")
        info += "\n\nLa suppression est inscrite au journal."
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Supprimer")
        box.setText(f"<b>Supprimer {'ce lot' if len(lots) == 1 else f'ces {len(lots)} lots'} ANTAI ?</b>")
        box.setInformativeText(info)
        cb = QCheckBox("Supprimer aussi le fichier CSV")
        box.setCheckBox(cb)
        yes = box.addButton("Supprimer", QMessageBox.DestructiveRole)
        no = box.addButton("Annuler", QMessageBox.RejectRole)
        box.setDefaultButton(no)
        box.exec()
        if box.clickedButton() is yes:
            services.delete_lots([l["id"] for l in lots], delete_files=cb.isChecked())
            self.main.refresh_all()


class JournalPage(QWidget):
    """Journal des opérations (affiché dans un onglet des Paramètres)."""

    def __init__(self, main, embedded: bool = False):
        super().__init__()
        self.model = RowsModel([("ts", "Date", f_dt), ("utilisateur", "Utilisateur", None), ("numero_avis", "Avis", None),
                                ("action", "Action", None), ("details", "Détails", None)])
        view, proxy = make_table(self.model, self)
        search = QLineEdit()
        search.setPlaceholderText("Filtrer le journal…")
        search.textChanged.connect(proxy.setFilterFixedString)
        lay = QVBoxLayout(self)
        if embedded:
            lay.setContentsMargins(8, 8, 8, 8)
        else:
            lay.setContentsMargins(20, 16, 20, 16)
            lay.addLayout(page_header("Journal des opérations"))
        lay.addWidget(search)
        lay.addWidget(view, 1)
        for i, w in enumerate([140, 110, 100, 200]):
            view.setColumnWidth(i, w)

    def refresh(self):
        self.model.set_rows(db.q("""SELECT j.*, pv.numero_avis FROM journal j LEFT JOIN pv ON pv.id=j.pv_id
                                    ORDER BY j.id DESC LIMIT 3000"""))
