"""Liste des contraventions + fiche de vérification d'un avis."""
from datetime import date, timedelta
from pathlib import Path

import pymupdf
from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QAction, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from .. import antai_export, db, mailer, parser, plates, referentiel, services
from .common import (STATUT_COLORS, DropZone, RowsModel, Worker, error_box, f_date, f_money, f_plate, f_statut, make_table,
                     open_path, selected_rows)

PV_SQL = """
SELECT pv.*,
       CASE WHEN d.id IS NOT NULL
            THEN '👷 ' || TRIM(COALESCE(d.nom,'')||' '||COALESCE(d.prenom,''))
                 || CASE WHEN pv.conducteur_source='HABITUEL' THEN ' (proposé)' ELSE '' END
            ELSE COALESCE(c.raison_sociale, TRIM(COALESCE(c.nom,'')||' '||COALESCE(c.prenom,''))) END AS client,
       c.email AS client_email, k.numero AS contrat
FROM pv LEFT JOIN clients c ON c.id=pv.client_id LEFT JOIN contrats k ON k.id=pv.contrat_id
        LEFT JOIN conducteurs d ON d.id=pv.conducteur_id
"""

FILTERS = [
    ("Dossiers en cours", "pv.statut IN ('A_VERIFIER','NON_IDENTIFIE','A_DENONCER','EXPORTE','A_PAYER','PAYE')"),
    ("À traiter (vérifier / non identifiés)", "pv.statut IN ('A_VERIFIER','NON_IDENTIFIE')"),
    ("Prêts à dénoncer", "pv.statut='A_DENONCER'"),
    ("Exportés, en attente de dépôt", "pv.statut='EXPORTE'"),
    ("À payer", "pv.statut='A_PAYER'"),
    ("Payés – à refacturer", "pv.statut='PAYE'"),
    ("Refacturés – attente de règlement", "pv.statut='REFACTURE'"),
    ("Clients à notifier", "pv.statut IN ('EXPORTE','DEPOSE','PAYE','REFACTURE') AND pv.client_id IS NOT NULL "
                           "AND pv.date_notification IS NULL"),
    ("Échéance proche", "URGENT"),
    ("Clos", "pv.statut='CLOS'"),
    ("Tous", "1=1"),
]

NOTIFIABLES = ("EXPORTE", "DEPOSE", "PAYE", "REFACTURE", "CLOS")


def _echeance(v, row):
    if not v:
        return ""
    if row.get("statut") not in db.STATUTS_ECHEANCE:
        return parser.fmt_date(v)
    days = (parser.to_date(v) - date.today()).days
    return f"{parser.fmt_date(v)}  ({'dépassée' if days < 0 else 'J-' + str(days)})"


class PvPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.worker = None

        title = QLabel("Contraventions")
        title.setObjectName("pageTitle")

        b_import = QPushButton("📥  Importer des scans…")
        b_import.setProperty("primary", True)
        b_import.clicked.connect(self.import_files)
        b_scan = QPushButton("🖨  Numériser")
        b_scan.clicked.connect(self.scan)
        b_depot = QPushButton("📂  Traiter le dossier de dépôt")
        b_depot.clicked.connect(self.process_depot)
        b_csv = QPushButton("📄  Générer le CSV ANTAI")
        b_csv.setProperty("accent", True)
        b_csv.clicked.connect(self.export_csv)
        b_mail = QPushButton("✉  Notifier les clients")
        b_mail.clicked.connect(self.notify)
        b_pay = QPushButton("💳  Paiement / facturation ▾")
        pay_menu = QMenu(b_pay)
        for text, fn in [("Enregistrer le paiement de la sélection…", self.pay),
                         ("Saisir le n° de facture…", self.invoice),
                         ("Marquer réglé par le client…", self.settle),
                         (None, None),
                         ("Passer en « payer et refacturer »", lambda: self.set_track("PAIEMENT")),
                         ("Passer en « désignation ANTAI »", lambda: self.set_track("DESIGNATION")),
                         ("Revenir à la filière automatique", lambda: self.set_track(None)),
                         (None, None),
                         ("Export « à facturer » (amendes payées + frais)…", self.export_billing)]:
            if text is None:
                pay_menu.addSeparator()
            else:
                a = QAction(text, pay_menu)
                a.triggered.connect(fn)
                pay_menu.addAction(a)
        b_pay.setMenu(pay_menu)
        b_more = QPushButton("Plus ▾")
        menu = QMenu(b_more)
        for text, fn in [("Traiter le dossier de dépôt maintenant", self.process_depot),
                         ("Relancer l'identification des dossiers en cours", self.reidentify),
                         ("Changer le statut de la sélection…", self.change_status),
                         ("Marquer les frais de dossier comme facturés", self.mark_billed),
                         ("Supprimer la sélection…", self.delete),
                         (None, None),
                         ("Exporter la liste vers Excel…", self.export_excel)]:
            if text is None:
                menu.addSeparator()
            else:
                a = QAction(text, menu)
                a.triggered.connect(fn)
                menu.addAction(a)
        b_more.setMenu(menu)

        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch()
        for b in (b_import, b_scan):
            top.addWidget(b)
        top.addSpacing(16)
        for b in (b_csv, b_pay, b_mail, b_more):
            top.addWidget(b)

        self.filter = QComboBox()
        for label, _ in FILTERS:
            self.filter.addItem(label)
        self.filter.currentIndexChanged.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher : n° d'avis, immatriculation, client, lieu…")
        self.search.setClearButtonEnabled(True)
        self.count = QLabel()
        self.count.setObjectName("hint")
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Afficher :"))
        bar.addWidget(self.filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.count)

        self.model = RowsModel([
            ("date_limite", "Échéance", _echeance),
            ("statut", "Statut", f_statut),
            ("traitement", "Filière", lambda v, r: {"PAIEMENT": "Paiement", "DESIGNATION": "Désignation"}.get(v, "")),
            ("numero_avis", "N° avis", None),
            ("type", "Type", None),
            ("date_infraction", "Infraction", f_date),
            ("heure_infraction", "Heure", None),
            ("immatriculation", "Immat.", f_plate),
            ("client", "Locataire", None),
            ("contrat", "Contrat", None),
            ("lieu", "Lieu", None),
            ("montant", "Montant", f_money),
            ("date_notification", "Notifié", lambda v, r: parser.fmt_date(v) if v else ""),
            ("anomalie", "Anomalies", None),
        ])
        self.model.color_fn = self._color
        self.view, self.proxy = make_table(self.model, self)
        self.view.doubleClicked.connect(self.open_detail)
        QShortcut(QKeySequence.Delete, self.view, self.delete)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.search.textChanged.connect(lambda _: self._update_count())

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addLayout(top)
        self.drop_zones: list[DropZone] = []
        lay.addWidget(self.make_drop_zone(compact=True))
        lay.addLayout(bar)
        lay.addWidget(self.view, 1)
        hint = QLabel("Double-cliquez sur un avis pour le vérifier, clic droit pour plus d'actions, Suppr pour supprimer. "
                      "Sélection multiple : Ctrl / Maj + clic.  "
                      "Le CSV et les notifications portent sur la sélection (ou, à défaut, sur tous les avis éligibles affichés).")
        hint.setObjectName("hint")
        lay.addWidget(hint)
        self.refresh()
        for i, w in enumerate([150, 170, 85, 95, 75, 85, 55, 90, 200, 110, 220, 75, 80]):
            self.view.setColumnWidth(i, w)

    def _color(self, row, key):
        if key == "statut":
            return STATUT_COLORS.get(row.get("statut"))
        if key == "date_limite" and row.get("date_limite") and row.get("statut") in db.STATUTS_ECHEANCE:
            days = (parser.to_date(row["date_limite"]) - date.today()).days
            if days < 0:
                return ("#FFFFFF", "#C53030")
            if days <= int(db.setting("alerte_jours") or 10):
                return ("#9B1C1C", "#FDE2E2")
        if key == "anomalie" and row.get("anomalie"):
            return ("#8A5A00", "#FFFFFF")
        return None

    def set_filter(self, label: str):
        idx = self.filter.findText(label)
        if idx >= 0:
            self.filter.setCurrentIndex(idx)
        self.refresh()

    def refresh(self):
        cond = FILTERS[self.filter.currentIndex()][1]
        params = ()
        if cond == "URGENT":
            limit = (date.today() + timedelta(days=int(db.setting("alerte_jours") or 10))).isoformat()
            cond = f"pv.statut IN {db.SQL_ECHEANCE} AND pv.date_limite<=?"
            params = (limit,)
        rows = db.q(PV_SQL + f" WHERE {cond} ORDER BY pv.date_limite IS NULL, pv.date_limite, pv.id DESC", params)
        self.model.set_rows(rows)
        self._update_count()

    def _update_count(self):
        self.count.setText(f"{self.proxy.rowCount()} avis")

    def _visible_rows(self):
        return [self.model.row(self.proxy.mapToSource(self.proxy.index(i, 0)).row()) for i in range(self.proxy.rowCount())]

    def _targets(self, predicate, what: str) -> list[dict]:
        sel = selected_rows(self.view, self.proxy, self.model)
        rows = sel or self._visible_rows()
        ok = [r for r in rows if predicate(r)]
        if sel and len(ok) < len(sel):
            QMessageBox.information(self, "Sélection", f"{len(sel) - len(ok)} avis de la sélection ne sont pas "
                                                       f"éligibles ({what}) et seront ignorés.")
        return ok

    # ------------------------------------------------------------ tâches de fond
    def make_drop_zone(self, compact=False) -> DropZone:
        """Zone de dépôt reliée à l'import (utilisée ici et sur le tableau de bord)."""
        zone = DropZone(self, compact)
        zone.files_dropped.connect(self.import_paths)
        zone.clicked.connect(self.import_files)
        self.drop_zones.append(zone)
        return zone

    def _zones_busy(self, text):
        for z in self.drop_zones:
            z.set_busy(text)

    def run_bg(self, fn, on_done, label="Traitement en cours…"):
        if self.busy():
            QMessageBox.information(self, "Patientez", "Un traitement est déjà en cours.")
            return
        self.main.status(label)
        self._zones_busy(label)
        self.worker = Worker(fn, self)
        self.worker.progress.connect(self.main.status)
        self.worker.progress.connect(self._zones_busy)
        self.worker.done.connect(lambda res: (self._zones_busy(None), self.main.status("Prêt"), on_done(res),
                                              self.main.refresh_all()))
        self.worker.failed.connect(lambda err: (self._zones_busy(None), self.main.status("Erreur"),
                                                error_box(self, "Erreur", err)))
        self.worker.start()

    def busy(self) -> bool:
        watcher = getattr(self.main, "watcher", None)
        return bool(self.worker and self.worker.isRunning()) or bool(watcher and watcher.isRunning())

    def _report_import(self, results):
        if not results:
            self.main.status("Aucun fichier à traiter.")
            return
        counts = {}
        for r in results:
            counts[r["statut"]] = counts.get(r["statut"], 0) + 1
        other = {"DOUBLON": "Doublon ignoré", "ACCUSE": "Accusé d'enregistrement ANTAI", "ERREUR": "Erreur",
                 "IGNORE": "Fichier ignoré"}
        lines = [f"{n} × {db.STATUTS.get(s) or other.get(s, s)}" for s, n in counts.items()]
        msgs = [r["message"] for r in results if r["message"]]
        QMessageBox.information(self, "Import terminé",
                                f"{len([r for r in results if r['pv_id']])} avis importé(s).\n\n" + "\n".join(lines) +
                                ("\n\n" + "\n".join(msgs[:15]) if msgs else ""))
        self.set_filter("Dossiers en cours")

    def import_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choisir les avis scannés", "",
                                                "Scans (*.pdf *.jpg *.jpeg *.png *.tif *.tiff *.bmp)")
        if files:
            self.import_paths(files)

    def import_paths(self, paths: list[str]):
        """Importe des fichiers et/ou des dossiers (parcourus avec leurs sous-dossiers)."""
        files, ignored = [], []
        for p in map(Path, paths):
            candidates = sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else [p]
            for f in candidates:
                (files if f.suffix.lower() in services.SUPPORTED else ignored).append(f)
        if not files:
            QMessageBox.information(self, "Import", "Aucun scan reconnu (PDF, JPG, PNG, TIFF, BMP)."
                                    + (f"\n\nIgnorés : {', '.join(f.name for f in ignored[:10])}" if ignored else ""))
            return

        def job(progress):
            results = []
            for n, f in enumerate(files, 1):
                step = (lambda msg, n=n: progress(f"[{n}/{len(files)}] {msg}")) if len(files) > 1 else progress
                try:
                    results += services.import_file(f, step)
                except Exception as e:  # un fichier illisible n'arrête pas le lot
                    results.append({"pv_id": None, "numero": None, "statut": "ERREUR", "message": f"{f.name} : {e}"})
            results += [{"pv_id": None, "numero": None, "statut": "IGNORE", "message": f"{f.name} : format non pris en charge"}
                        for f in ignored]
            return results

        self.run_bg(job, self._report_import, f"Lecture de {len(files)} fichier(s)…")

    def process_depot(self):
        if not db.setting("dossier_depot"):
            QMessageBox.information(self, "Dossier de dépôt", "Aucun dossier de dépôt configuré (Paramètres > Général).")
            return
        self.run_bg(services.scan_depot, self._report_import, "Traitement du dossier de dépôt…")

    def scan(self):
        try:
            path = services.acquire_from_scanner()
        except Exception as e:
            error_box(self, "Numérisation", f"Scanner indisponible : {e}\n\nAstuce : configurez votre copieur pour "
                                            "numériser vers le dossier de dépôt.")
            return
        if path:
            self.run_bg(lambda progress: services.import_file(path, progress), self._report_import, "Lecture du scan…")

    # ------------------------------------------------------------ actions
    def open_detail(self, index):
        row = self.model.row(self.proxy.mapToSource(index).row())
        dlg = PvDialog(row["id"], self)
        dlg.exec()
        self.main.refresh_all()

    def export_csv(self):
        rows = self._targets(lambda r: r["statut"] == "A_DENONCER", "statut « À dénoncer » requis")
        if not rows:
            QMessageBox.information(self, "CSV ANTAI", "Aucun avis « À dénoncer ».")
            return
        if QMessageBox.question(self, "CSV ANTAI", f"Générer le fichier de désignation pour {len(rows)} avis ?\n\n"
                                "Les avis passeront au statut « Exporté ». Déposez ensuite le fichier sur l'espace "
                                "entreprises ANTAI, puis marquez le lot comme déposé (page Lots ANTAI).") != QMessageBox.Yes:
            return
        try:
            files = antai_export.generate([r["id"] for r in rows])
        except Exception as e:
            error_box(self, "CSV ANTAI", e)
            return
        self.main.refresh_all()
        if QMessageBox.question(self, "CSV ANTAI", "Fichier(s) créé(s) :\n" + "\n".join(str(f) for f in files) +
                                "\n\nOuvrir le dossier ?") == QMessageBox.Yes:
            open_path(files[0].parent)

    def notify(self):
        rows = self._targets(lambda r: r["client_id"] and r["statut"] in NOTIFIABLES,
                             "locataire identifié et avis dénoncé ou payé")
        sel = bool(selected_rows(self.view, self.proxy, self.model))
        if not sel:
            rows = [r for r in rows if not r["date_notification"]]
        if not rows:
            QMessageBox.information(self, "Notification", "Aucun avis à notifier.")
            return
        sans_mail = {r["client"] for r in rows if not r["client_email"]}
        clients = {r["client_id"] for r in rows}
        msg = f"Envoyer {len(clients)} e-mail(s) pour {len(rows)} avis ?"
        if sans_mail:
            msg += "\n\nSans adresse e-mail (ignorés) : " + ", ".join(sorted(sans_mail))
        if QMessageBox.question(self, "Notification des clients", msg) != QMessageBox.Yes:
            return
        ids = [r["id"] for r in rows]
        self.run_bg(lambda progress: mailer.notify(ids, progress),
                    lambda out: QMessageBox.information(self, "Notification", "\n".join(out)), "Envoi des e-mails…")

    def pay(self):
        rows = self._selection_or_warn(lambda r: r["statut"] in ("A_PAYER", "A_VERIFIER", "NON_IDENTIFIE", "PAYE"),
                                       "à payer")
        if not rows:
            return
        dlg = PaymentDialog(rows, self)
        if dlg.exec():
            n = services.record_payment([r["id"] for r in rows], *dlg.values())
            self.main.refresh_all()
            self.main.status(f"{n} paiement(s) enregistré(s) — avis « Payé – à refacturer ».")

    def invoice(self):
        rows = self._selection_or_warn(lambda r: r["client_id"] and r["statut"] in ("PAYE", "EXPORTE", "DEPOSE", "CLOS"),
                                       "payés ou dénoncés, avec un locataire")
        if not rows:
            return
        dlg = InvoiceDialog(len(rows), self)
        if dlg.exec():
            n = services.record_invoice([r["id"] for r in rows], *dlg.values())
            self.main.refresh_all()
            self.main.status(f"{n} avis rattaché(s) à la facture {dlg.values()[0]}.")

    def settle(self):
        rows = self._selection_or_warn(lambda r: r["statut"] in ("REFACTURE", "PAYE", "DEPOSE"), "refacturés")
        if not rows:
            return
        dlg = DateDialog("Réglé par le client", f"Règlement reçu pour {len(rows)} avis, le :", self)
        if dlg.exec():
            services.record_settlement([r["id"] for r in rows], dlg.value())
            self.main.refresh_all()

    def set_track(self, traitement):
        rows = selected_rows(self.view, self.proxy, self.model)
        if not rows:
            QMessageBox.information(self, "Filière", "Sélectionnez d'abord un ou plusieurs avis.")
            return
        bloques = [r for r in rows if r["statut"] not in db.STATUTS_AUTO]
        for r in rows:
            if r not in bloques:
                services.set_traitement(r["id"], traitement)
        self.main.refresh_all()
        if bloques:
            QMessageBox.information(self, "Filière", f"{len(bloques)} avis déjà exportés / payés / clos n'ont pas été "
                                                     "modifiés.")

    def _selection_or_warn(self, predicate, what) -> list[dict]:
        sel = selected_rows(self.view, self.proxy, self.model)
        if not sel:
            QMessageBox.information(self, "Sélection", "Sélectionnez d'abord un ou plusieurs avis (Ctrl / Maj + clic).")
            return []
        ok = [r for r in sel if predicate(r)]
        if len(ok) < len(sel):
            QMessageBox.information(self, "Sélection", f"{len(sel) - len(ok)} avis ignoré(s) : seuls les avis {what} "
                                                       "sont concernés.")
        return ok

    def reidentify(self):
        n = services.reidentify_open()
        self.main.refresh_all()
        self.main.status(f"{n} dossier(s) ré-analysé(s).")

    def change_status(self):
        rows = selected_rows(self.view, self.proxy, self.model)
        if not rows:
            return
        labels = list(db.STATUTS.values())
        lab, ok = QInputDialog.getItem(self, "Changer le statut", f"Nouveau statut pour {len(rows)} avis :", labels, 0, False)
        if ok:
            code = [k for k, v in db.STATUTS.items() if v == lab][0]
            for r in rows:
                db.update("pv", r["id"], {"statut": code, "updated_at": services.now()})
                db.log("Statut modifié", f"{db.STATUTS.get(r['statut'])} → {lab}", r["id"])
            self.main.refresh_all()

    def mark_billed(self):
        rows = selected_rows(self.view, self.proxy, self.model)
        for r in rows:
            db.update("pv", r["id"], {"refacture": 1})
        self.main.status(f"{len(rows)} avis marqué(s) refacturé(s).")

    def _context_menu(self, pos):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        if not self.view.selectionModel().isRowSelected(index.row(), index.parent()):
            self.view.selectRow(index.row())
        n = len(selected_rows(self.view, self.proxy, self.model))
        menu = QMenu(self)
        if n == 1:
            menu.addAction("Ouvrir la fiche", lambda: self.open_detail(index))
            menu.addSeparator()
        menu.addAction("Changer le statut…", self.change_status)
        menu.addAction("🗑  Supprimer…" if n == 1 else f"🗑  Supprimer les {n} avis…", self.delete)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def delete(self):
        rows = selected_rows(self.view, self.proxy, self.model)
        if not rows:
            QMessageBox.information(self, "Supprimer", "Sélectionnez d'abord le ou les avis à supprimer.")
            return
        if delete_with_confirmation(self, rows):
            self.main.refresh_all()

    def export_excel(self):
        path, _ = QFileDialog.getSaveFileName(self, "Exporter", f"contraventions_{date.today():%Y%m%d}.xlsx", "Excel (*.xlsx)")
        if path:
            referentiel.export_pv_excel(self._visible_rows(), path)
            open_path(path)

    def export_billing(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export refacturation", f"refacturation_{date.today():%Y%m}.xlsx",
                                              "Excel (*.xlsx)")
        if not path:
            return
        mark = QMessageBox.question(self, "À facturer", "Après l'export, marquer ces avis comme facturés ?\n"
                                    "(amendes payées -> « Refacturé – attente règlement » ; ils n'apparaîtront plus "
                                    "dans le prochain export)") == QMessageBox.Yes
        n = referentiel.export_refacturation(path, mark)
        self.main.status(f"{n} avis exportés pour refacturation.")
        open_path(path)


class PdfViewer(QWidget):
    def __init__(self, path: str | None):
        super().__init__()
        self.path = path
        # chargé en mémoire : le fichier n'est pas verrouillé (il peut être renommé pendant que la fiche est ouverte)
        self.doc = pymupdf.open(stream=Path(path).read_bytes(), filetype="pdf") if path and Path(path).exists() else None
        self.page, self.zoom = 0, 1.3
        self.label = QLabel("Fichier introuvable" if not self.doc else "")
        self.label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        scroll = QScrollArea()
        scroll.setWidget(self.label)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#5f6b7a;")
        self.info = QLabel()
        bar = QHBoxLayout()
        for text, fn in [("◀", lambda: self.go(-1)), ("▶", lambda: self.go(1)),
                         ("−", lambda: self.set_zoom(-0.2)), ("+", lambda: self.set_zoom(0.2)),
                         ("Ouvrir le PDF", lambda: open_path(self.path))]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addWidget(self.info)
        bar.addStretch()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(bar)
        lay.addWidget(scroll, 1)
        self.render()

    def go(self, d):
        if self.doc:
            self.page = max(0, min(self.doc.page_count - 1, self.page + d))
            self.render()

    def set_zoom(self, d):
        self.zoom = max(0.5, min(4.0, self.zoom + d))
        self.render()

    def render(self):
        if not self.doc:
            return
        pix = self.doc[self.page].get_pixmap(matrix=pymupdf.Matrix(self.zoom, self.zoom))
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        self.label.setPixmap(QPixmap.fromImage(img))
        self.info.setText(f"Page {self.page + 1}/{self.doc.page_count}")


class PvDialog(QDialog):
    def __init__(self, pv_id: int, parent=None):
        super().__init__(parent)
        self.pv_id = pv_id
        self.pv = db.q1("SELECT * FROM pv WHERE id=?", (pv_id,))
        self.setWindowTitle(f"Avis {self.pv['numero_avis'] or '(sans numéro)'}")
        self.resize(1350, 880)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)

        viewer = self.viewer = PdfViewer(self.pv["fichier"])

        p = self.pv
        self.f = {}
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        def line(key, label, value, ph=""):
            w = QLineEdit(value or "")
            w.setCursorPosition(0)
            w.setPlaceholderText(ph)
            self.f[key] = w
            form.addRow(label, w)
            return w

        line("numero_avis", "N° de l'avis", p["numero_avis"], "10 chiffres")
        self.type = QComboBox()
        for code, lab in [("AMENDE", "Avis de contravention"), ("MAJOREE", "Amende forfaitaire majorée"),
                          ("FPS", "Forfait post-stationnement (FPS)"), ("AUTRE", "Autre")]:
            self.type.addItem(lab, code)
        self.type.setCurrentIndex(max(0, self.type.findData(p["type"])))
        form.addRow("Type", self.type)
        self.traitement = QComboBox()
        auto = services.traitement_auto(p, p["client_id"])
        self.traitement.addItem(f"Automatique ({db.TRAITEMENTS[auto].lower()})", None)
        for code, lab in db.TRAITEMENTS.items():
            self.traitement.addItem(lab, code)
        self.traitement.setCurrentIndex(max(0, self.traitement.findData(p["traitement_manuel"])))
        form.addRow("Filière", self.traitement)
        line("date_avis", "Date de l'avis", parser.fmt_date(p["date_avis"]), "jj/mm/aaaa")
        line("date_infraction", "Date infraction", parser.fmt_date(p["date_infraction"]), "jj/mm/aaaa")
        line("heure_infraction", "Heure", p["heure_infraction"], "hh:mm")
        line("immatriculation", "Immatriculation", plates.display(p["immatriculation"]))
        line("titulaire", "Titulaire sur l'avis", p["titulaire"],
             f"vide = {db.setting('loueur_raison_sociale') or 'raison sociale des Paramètres'}")
        if p["immat_lue"] and plates.normalize(p["immat_lue"]) != plates.normalize(p["immatriculation"]):
            form.addRow("", QLabel(f"<i>lue par l'OCR : {plates.display(p['immat_lue'])}</i>"))
        line("lieu", "Lieu", p["lieu"])
        line("nature", "Nature", p["nature"])
        line("montant", "Montant (€)", f"{p['montant']:g}".replace(".", ",") if p["montant"] else "")

        self.contrat = QComboBox()
        form.addRow("Contrat de location", self.contrat)

        # chauffeur salarié : véhicule de la société (ou usage interne d'un véhicule de location)
        self.chauffeur = QComboBox()
        self.chauffeur.addItem("(aucun — locataire du contrat)", None)
        for r in db.q("SELECT * FROM conducteurs WHERE actif=1 OR id=? ORDER BY nom, prenom", (p["conducteur_id"],)):
            self.chauffeur.addItem(f"{r['nom'] or ''} {r['prenom'] or ''}  ({r['matricule'] or '—'})", r["id"])
        self.chauffeur.setCurrentIndex(max(0, self.chauffeur.findData(p["conducteur_id"])))
        self.confirm_chauffeur = QPushButton("✔ Confirmer ce chauffeur")
        self.confirm_chauffeur.setToolTip("Chauffeur habituel du véhicule proposé automatiquement : confirmez qu'il "
                                          "conduisait au moment de l'infraction")
        self.confirm_chauffeur.setVisible(p["conducteur_source"] == "HABITUEL")
        self.confirm_chauffeur.clicked.connect(self._confirm_driver)
        self._driver_confirmed = False
        row_ch = QHBoxLayout()
        row_ch.addWidget(self.chauffeur, 1)
        row_ch.addWidget(self.confirm_chauffeur)
        form.addRow("Chauffeur désigné", row_ch)
        self.chauffeur.currentIndexChanged.connect(self._show_designee)
        self.chauffeur.currentIndexChanged.connect(lambda _: self.confirm_chauffeur.setVisible(False))
        self.designee = QLabel()
        self.designee.setWordWrap(True)
        self.designee.setTextFormat(Qt.RichText)
        self.designee.setStyleSheet("background:#F4F6F9; padding:8px; border-radius:4px;")
        form.addRow("Locataire à refacturer" if p["traitement"] == "PAIEMENT" else "Personne désignée", self.designee)
        self.contrat.currentIndexChanged.connect(self._show_designee)

        self.statut = QComboBox()
        for code, lab in db.STATUTS.items():
            self.statut.addItem(lab, code)
        self.statut.setCurrentIndex(self.statut.findData(p["statut"]))
        form.addRow("Statut", self.statut)
        line("frais_dossier", "Frais de dossier (€ HT)", f"{p['frais_dossier']:g}".replace(".", ",") if p["frais_dossier"] is not None else "")
        self.refacture = QCheckBox("Frais de dossier facturés au client")
        self.refacture.setChecked(bool(p["refacture"]))
        form.addRow("", self.refacture)

        titre = QLabel("<b>Paiement et facturation</b> (filière « payer et refacturer »)")
        titre.setStyleSheet("color:#1F3A5F; padding-top:8px;")
        form.addRow(titre)
        line("date_paiement", "Payé le", parser.fmt_date(p["date_paiement"]), "jj/mm/aaaa")
        line("montant_paye", "Montant payé (€)", f"{p['montant_paye']:g}".replace(".", ",") if p["montant_paye"] else "")
        self.mode = QComboBox()
        self.mode.setEditable(True)
        self.mode.addItem("")
        self.mode.addItems(db.MODES_PAIEMENT)
        self.mode.setCurrentText(p["mode_paiement"] or "")
        form.addRow("Mode de paiement", self.mode)
        line("ref_paiement", "Réf. du paiement", p["ref_paiement"], "n° de transaction, de chèque…")
        line("facture_numero", "N° de facture", p["facture_numero"], "facture émise dans votre logiciel")
        line("date_facture", "Facturé le", parser.fmt_date(p["date_facture"]), "jj/mm/aaaa")
        line("date_reglement", "Réglé par le client le", parser.fmt_date(p["date_reglement"]), "jj/mm/aaaa")
        self.notes = QPlainTextEdit(p["notes"] or "")
        self.notes.setMaximumHeight(70)
        form.addRow("Notes", self.notes)

        info = QLabel(
            f"<b>Échéance {'de paiement (avant majoration)' if p['traitement'] == 'PAIEMENT' else 'de désignation'} :</b> "
            f"{parser.fmt_date(p['date_limite']) or '—'}<br>"
            f"<b>Dénoncé le :</b> {parser.fmt_date(p['date_designation']) or '—'} &nbsp; "
            f"<b>Client notifié le :</b> {p['date_notification'] or '—'}<br>"
            + (f"<span style='color:#9B1C1C'><b>Anomalies :</b> {p['anomalie']}</span>" if p["anomalie"] else ""))
        info.setWordWrap(True)

        fiche = QWidget()
        fl = QVBoxLayout(fiche)
        fl.addLayout(form)
        fl.addWidget(info)
        fl.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(fiche)
        scroll.setWidgetResizable(True)

        ocr = QPlainTextEdit(p["ocr_texte"] or "")
        ocr.setReadOnly(True)
        hist = QPlainTextEdit("\n".join(f"{r['ts']}  {r['utilisateur']}  {r['action']}  {r['details'] or ''}"
                                        for r in db.q("SELECT * FROM journal WHERE pv_id=? ORDER BY id", (pv_id,))))
        hist.setReadOnly(True)
        tabs = QTabWidget()
        tabs.addTab(scroll, "Fiche")
        tabs.addTab(ocr, "Texte lu (OCR)")
        tabs.addTab(hist, "Historique")

        b_reread = QPushButton("📷  Relire le scan")
        b_reread.setToolTip("Relance l'OCR (redressement, amélioration d'image) et remplace les champs extraits")
        b_reread.clicked.connect(self.reread)
        b_loc = QPushButton("🚐  Créer la location")
        b_loc.setToolTip("Locataire introuvable ? Saisissez la location (véhicule + client + contrat) en un formulaire")
        b_loc.clicked.connect(self.create_location)
        b_loc.setVisible(not self.pv["contrat_id"])
        b_reid = QPushButton("🔎  Ré-identifier")
        b_reid.clicked.connect(self.reidentify)
        b_mail = QPushButton("✉  Envoyer au client")
        b_mail.clicked.connect(self.send_mail)
        b_save = QPushButton("Enregistrer")
        b_save.setProperty("primary", True)
        b_save.clicked.connect(self.save_and_close)
        b_close = QPushButton("Fermer")
        b_close.clicked.connect(self.reject)
        b_del = QPushButton("🗑  Supprimer")
        b_del.setToolTip("Supprimer cet avis de la base (confirmation demandée)")
        b_del.clicked.connect(self.delete)
        btns = QHBoxLayout()
        btns.addWidget(b_loc)
        btns.addWidget(b_reread)
        btns.addWidget(b_reid)
        btns.addWidget(b_mail)
        btns.addStretch()
        btns.addWidget(b_del)
        btns.addWidget(b_close)
        btns.addWidget(b_save)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(tabs, 1)
        rl.addLayout(btns)
        split = QSplitter()
        split.addWidget(viewer)
        split.addWidget(right)
        split.setSizes([720, 600])
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        self._load_contracts()

    def _load_contracts(self):
        self.contrat.blockSignals(True)
        self.contrat.clear()
        self.contrat.addItem("(aucun)", None)
        immat = plates.normalize(self.f["immatriculation"].text())
        d = parser.to_date(self.f["date_infraction"].text())
        rows = []
        if immat:
            # contrats du véhicule autour de la date (± 60 jours) — le contrat en cours apparaît en premier
            lo = (d - timedelta(days=60)).isoformat() if d else "0000"
            hi = (d + timedelta(days=60)).isoformat() + " 23:59" if d else "9999"
            rows = db.q("""SELECT k.*, COALESCE(c.raison_sociale, c.nom||' '||COALESCE(c.prenom,'')) client
                           FROM contrats k JOIN vehicules v ON v.id=k.vehicule_id JOIN clients c ON c.id=k.client_id
                           WHERE v.immatriculation=? AND k.date_debut<=? AND (k.date_fin IS NULL OR k.date_fin>=?)
                           ORDER BY k.date_debut DESC""", (immat, hi, lo))
        for r in rows:
            fin = parser.fmt_date(r["date_fin"]) + " " + (r["date_fin"] or "")[11:16] if r["date_fin"] else "en cours"
            self.contrat.addItem(f"{r['numero']} – {r['client']}  ({parser.fmt_date(r['date_debut'])} "
                                 f"{r['date_debut'][11:16]} → {fin})", r["id"])
        if self.pv["contrat_id"] and self.contrat.findData(self.pv["contrat_id"]) < 0:
            k = db.q1("SELECT numero FROM contrats WHERE id=?", (self.pv["contrat_id"],))
            self.contrat.addItem(f"{k['numero'] if k else '?'}", self.pv["contrat_id"])
        self.contrat.setCurrentIndex(max(0, self.contrat.findData(self.pv["contrat_id"])))
        self.contrat.blockSignals(False)
        self._show_designee()

    def _show_designee(self):
        k = db.q1("SELECT * FROM contrats WHERE id=?", (self.contrat.currentData(),)) if self.contrat.currentData() else None
        fake = dict(self.pv)
        fake.update(contrat_id=k["id"] if k else None, client_id=k["client_id"] if k else None,
                    conducteur_id=self.chauffeur.currentData(),
                    numero_avis=self.f["numero_avis"].text() or None,
                    immatriculation=self.f["immatriculation"].text() or None,
                    date_avis=self.f["date_avis"].text() or None)
        d = antai_export.designee(fake)
        if not d:
            self.designee.setText("<i>Aucun locataire – choisissez un contrat.</i>")
            return
        if d.get("type") == "PM":
            who = f"<b>{d.get('raison_sociale') or ''}</b> (personne morale)"
        else:
            who = f"<b>{d.get('civilite') or ''} {d.get('nom') or ''} {d.get('prenom') or ''}</b>, né(e) le " \
                  f"{parser.fmt_date(d.get('date_naissance')) or '?'} – permis {d.get('num_permis') or '?'}"
        addr = f"{d.get('adresse') or ''} {d.get('complement') or ''}, {d.get('code_postal') or ''} {d.get('ville') or ''}"
        missing = antai_export.missing_fields(d, fake)
        txt = f"{who}<br>{addr}<br>✉ {d.get('email') or '<i>pas d’e-mail</i>'}"
        if missing:
            txt += f"<br><span style='color:#C53030'>Manquant pour la désignation : {', '.join(missing)}</span>"
        if fake.get("conducteur_id"):
            txt = "👷 <i>Chauffeur de la société</i><br>" + txt
            if self.pv["conducteur_source"] == "HABITUEL" and fake["conducteur_id"] == self.pv["conducteur_id"] \
                    and not self._driver_confirmed:
                txt += "<br><span style='color:#8A5A00'>Chauffeur habituel proposé : confirmez-le s'il conduisait.</span>"
        self.designee.setText(txt)

    def _confirm_driver(self):
        self._driver_confirmed = True
        self.confirm_chauffeur.setVisible(False)
        self._show_designee()

    def _values(self) -> dict:
        def num(s):
            s = s.strip().replace(",", ".").replace("€", "")
            return float(s) if s else None

        def d(key):
            txt = self.f[key].text().strip()
            v = parser.to_date(txt)
            if txt and not v:
                raise ValueError(f"Date invalide : {txt}")
            return v.isoformat() if v else None

        heure = self.f["heure_infraction"].text().strip().replace("h", ":").replace("H", ":")
        if heure and len(heure.split(":")) == 2:
            h, m = heure.split(":")
            heure = f"{int(h):02d}:{int(m or 0):02d}"
        return {
            "numero_avis": services.clean_numero(self.f["numero_avis"].text()) or None,
            "type": self.type.currentData(),
            "date_avis": d("date_avis"), "date_infraction": d("date_infraction"),
            "heure_infraction": heure or None,
            "immatriculation": plates.normalize(self.f["immatriculation"].text()) or None,
            "titulaire": self.f["titulaire"].text().strip() or None,
            "lieu": self.f["lieu"].text().strip() or None, "nature": self.f["nature"].text().strip() or None,
            "montant": num(self.f["montant"].text()), "frais_dossier": num(self.f["frais_dossier"].text()),
            "refacture": 1 if self.refacture.isChecked() else 0,
            "date_paiement": d("date_paiement"), "montant_paye": num(self.f["montant_paye"].text()),
            "mode_paiement": self.mode.currentText().strip() or None,
            "ref_paiement": self.f["ref_paiement"].text().strip() or None,
            "facture_numero": self.f["facture_numero"].text().strip() or None,
            "date_facture": d("date_facture"), "date_reglement": d("date_reglement"),
            "notes": self.notes.toPlainText().strip() or None,
            "updated_at": services.now(),
        }

    def save(self) -> bool:
        try:
            vals = self._values()
        except ValueError as e:
            QMessageBox.warning(self, "Saisie", str(e))
            return False
        old = self.pv
        changed = [k for k in ("numero_avis", "type", "date_avis", "date_infraction", "heure_infraction", "immatriculation")
                   if vals[k] != old[k]]
        try:
            db.update("pv", self.pv_id, vals)
        except Exception as e:
            QMessageBox.warning(self, "Enregistrement", "Ce numéro d'avis existe déjà." if "UNIQUE" in str(e) else str(e))
            return False
        statut = self.statut.currentData()
        ch = self.chauffeur.currentData()
        driver_changed = ch != old["conducteur_id"] or (ch and old["conducteur_source"] == "HABITUEL"
                                                        and self._driver_confirmed)
        if self.contrat.currentData() != old["contrat_id"] and not ch:
            services.set_contract(self.pv_id, self.contrat.currentData())
            db.log("Modification", "contrat choisi manuellement", self.pv_id)
        elif driver_changed:
            services.set_conducteur(self.pv_id, ch)
        elif changed and statut in db.STATUTS_AUTO:
            db.update("pv", self.pv_id, {"statut": "A_VERIFIER"})
            services.identify(self.pv_id)
        elif statut != old["statut"]:
            db.update("pv", self.pv_id, {"statut": statut})
            db.log("Statut modifié", f"{db.STATUTS.get(old['statut'])} → {db.STATUTS.get(statut)}", self.pv_id)
        if self.traitement.currentData() != old["traitement_manuel"]:
            services.set_traitement(self.pv_id, self.traitement.currentData())
        # avancement automatique de la filière paiement selon les dates saisies
        cur = db.q1("SELECT statut FROM pv WHERE id=?", (self.pv_id,))["statut"]
        if statut == old["statut"]:
            nxt = None
            if vals["date_reglement"] and not old["date_reglement"]:
                nxt = "CLOS"
            elif vals["facture_numero"] and not old["facture_numero"] and cur == "PAYE":
                nxt = "REFACTURE"
            elif vals["date_paiement"] and not old["date_paiement"] and cur in ("A_PAYER", "A_VERIFIER", "NON_IDENTIFIE"):
                nxt = "PAYE"
            if nxt:
                db.update("pv", self.pv_id, {"statut": nxt, "traitement": "PAIEMENT" if nxt != "CLOS" else
                                             (self.pv["traitement"] or "PAIEMENT")})
                db.log("Statut", f"{db.STATUTS.get(cur)} → {db.STATUTS.get(nxt)}", self.pv_id)
        if changed:
            db.log("Correction", ", ".join(changed), self.pv_id)
        if {"numero_avis", "immatriculation"} & set(changed):
            services.rename_archive(self.pv_id)
        self.pv = db.q1("SELECT * FROM pv WHERE id=?", (self.pv_id,))
        self.viewer.path = self.pv["fichier"]
        return True

    def delete(self):
        row = dict(db.q1(PV_SQL + " WHERE pv.id=?", (self.pv_id,)))
        if delete_with_confirmation(self, [row]):
            self.accept()

    def save_and_close(self):
        if self.save():
            self.accept()

    def create_location(self):
        from datetime import datetime
        from .location_form import LocationDialog
        if not self.save():
            return
        d = parser.to_date(self.pv["date_infraction"])
        kw = {"immat": self.pv["immatriculation"]}
        if d:  # période pré-remplie autour de l'infraction, à ajuster
            kw["debut"] = datetime(d.year, d.month, d.day, 0, 0)
            kw["fin"] = datetime(d.year, d.month, d.day, 23, 59)
        dlg = LocationDialog(self, **kw)
        if dlg.exec():
            statut = services.set_contract(self.pv_id, dlg.created_contract_id)
            self.pv = db.q1("SELECT * FROM pv WHERE id=?", (self.pv_id,))
            self.statut.setCurrentIndex(self.statut.findData(statut))
            self._load_contracts()

    def reread(self):
        if QMessageBox.question(self, "Relire le scan", "Relire le PDF avec l'OCR et remplacer les champs extraits "
                                "(n°, dates, plaque, titulaire, lieu, nature, montant) ?") != QMessageBox.Yes:
            return
        self.setCursor(Qt.WaitCursor)
        try:
            statut = services.reread(self.pv_id)
        except Exception as e:
            error_box(self, "Relire le scan", e)
            return
        finally:
            self.unsetCursor()
        QMessageBox.information(self, "Relire le scan", f"Lecture terminée. Résultat : {db.STATUTS.get(statut, statut)}")
        self.accept()
        dlg = PvDialog(self.pv_id, self.parent())  # réouverture avec les nouvelles valeurs
        dlg.exec()

    def reidentify(self):
        if not self.save():
            return
        db.update("pv", self.pv_id, {"contrat_id": None})
        statut = services.identify(self.pv_id, force=self.pv["statut"] in db.STATUTS_AUTO)
        self.pv = db.q1("SELECT * FROM pv WHERE id=?", (self.pv_id,))
        self.statut.setCurrentIndex(self.statut.findData(statut))
        self._load_contracts()
        QMessageBox.information(self, "Identification", f"Résultat : {db.STATUTS[statut]}"
                                + (f"\n\n{self.pv['anomalie']}" if self.pv["anomalie"] else ""))

    def send_mail(self):
        if not self.save():
            return
        if not self.pv["client_id"]:
            QMessageBox.information(self, "E-mail", "Aucun locataire identifié.")
            return
        mail = mailer.build(self.pv["client_id"], [self.pv_id], self.pv["traitement"] or "DESIGNATION")
        dlg = MailPreview(mail, self)
        if dlg.exec() == QDialog.Accepted:
            try:
                mailer.send(dlg.mail())
                db.update("pv", self.pv_id, {"date_notification": services.now()[:16]})
                db.log("Client notifié", mail["to"], self.pv_id)
                QMessageBox.information(self, "E-mail", "Message envoyé.")
            except Exception as e:
                error_box(self, "E-mail", e)


class MailPreview(QDialog):
    def __init__(self, mail: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Aperçu de l'e-mail")
        self.resize(700, 600)
        self._mail = dict(mail)
        form = QFormLayout()
        self.to = QLineEdit(mail["to"])
        self.cc = QLineEdit(mail["cc"])
        self.subject = QLineEdit(mail["subject"])
        self.body = QPlainTextEdit(mail["body"])
        form.addRow("À", self.to)
        form.addRow("Cc", self.cc)
        form.addRow("Objet", self.subject)
        form.addRow("Pièces jointes", QLabel(", ".join(Path(a).name for a in mail["attachments"]) or "—"))
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.body, 1)
        b = QHBoxLayout()
        b.addStretch()
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        send = QPushButton("Envoyer")
        send.setProperty("primary", True)
        send.clicked.connect(self.accept)
        b.addWidget(cancel)
        b.addWidget(send)
        lay.addLayout(b)

    def mail(self) -> dict:
        m = dict(self._mail)
        m.update(to=self.to.text(), cc=self.cc.text(), subject=self.subject.text(), body=self.body.toPlainText())
        return m


def _date_edit(value=None) -> QDateEdit:
    w = QDateEdit(value or QDate.currentDate())
    w.setCalendarPopup(True)
    w.setDisplayFormat("dd/MM/yyyy")
    return w


class _SmallDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.form = QFormLayout()
        ok = QPushButton("Valider")
        ok.setProperty("primary", True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay = QVBoxLayout(self)
        lay.addLayout(self.form)
        lay.addLayout(btns)


class PaymentDialog(_SmallDialog):
    """Paiement d'un ou plusieurs avis (chaque avis est payé à son montant, sauf montant saisi pour un seul)."""

    def __init__(self, rows, parent=None):
        super().__init__("Enregistrer le paiement", parent)
        total = sum(r["montant"] or 0 for r in rows)
        self.form.addRow(QLabel(f"{len(rows)} avis — total des montants lus : {total:.2f} €".replace(".", ",")))
        self.date = _date_edit()
        self.mode = QComboBox()
        self.mode.setEditable(True)
        self.mode.addItems(db.MODES_PAIEMENT)
        self.ref = QLineEdit()
        self.ref.setPlaceholderText("n° de transaction, de chèque…")
        self.form.addRow("Payé le", self.date)
        self.form.addRow("Mode", self.mode)
        self.form.addRow("Référence", self.ref)
        self.montant = None
        if len(rows) == 1:
            self.montant = QLineEdit(f"{rows[0]['montant']:g}".replace(".", ",") if rows[0]["montant"] else "")
            self.montant.setPlaceholderText("montant réellement payé (minoré, majoré…)")
            self.form.addRow("Montant payé (€)", self.montant)

    def values(self):
        montant = None
        if self.montant is not None and self.montant.text().strip():
            montant = float(self.montant.text().replace(",", ".").replace("€", "").strip())
        return (self.date.date().toPython().isoformat(), self.mode.currentText().strip(), self.ref.text().strip(),
                montant)


class InvoiceDialog(_SmallDialog):
    def __init__(self, n, parent=None):
        super().__init__("Facture client", parent)
        self.form.addRow(QLabel(f"{n} avis refacturé(s) sur la facture :"))
        self.numero = QLineEdit()
        self.numero.setPlaceholderText("n° de la facture dans votre logiciel")
        self.date = _date_edit()
        self.form.addRow("N° de facture", self.numero)
        self.form.addRow("Date", self.date)

    def accept(self):
        if not self.numero.text().strip():
            QMessageBox.warning(self, "Facture", "Indiquez le n° de facture.")
            return
        super().accept()

    def values(self):
        return self.numero.text().strip(), self.date.date().toPython().isoformat()


class DateDialog(_SmallDialog):
    def __init__(self, title, label, parent=None):
        super().__init__(title, parent)
        self.date = _date_edit()
        self.form.addRow(label, self.date)

    def value(self):
        return self.date.date().toPython().isoformat()


ENGAGES = {"EXPORTE": "exporté dans un CSV", "DEPOSE": "déposé à l'ANTAI", "PAYE": "payé",
           "REFACTURE": "refacturé", "CLOS": "clos"}


def delete_with_confirmation(parent, rows: list[dict]) -> bool:
    """Demande confirmation (avec avertissement si des avis sont déjà engagés) puis supprime. Renvoie True si supprimé."""
    lignes = [f"• {r['numero_avis'] or '(sans n°)'} – {plates.display(r['immatriculation'])} – "
              f"{parser.fmt_date(r['date_infraction'])} – {db.STATUTS.get(r['statut'], r['statut'])}" for r in rows[:12]]
    if len(rows) > 12:
        lignes.append(f"… et {len(rows) - 12} autre(s)")
    engages = [r for r in rows if r["statut"] in ENGAGES]
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Supprimer")
    box.setText(f"<b>Supprimer définitivement {'cet avis' if len(rows) == 1 else f'ces {len(rows)} avis'} ?</b>")
    info = "\n".join(lignes)
    if engages:
        etats = ", ".join(sorted({ENGAGES[r["statut"]] for r in engages}))
        info += (f"\n\n⚠ {len(engages)} avis sont déjà engagés ({etats}) : la suppression ne les annule pas"
                 if len(engages) > 1 else
                 f"\n\n⚠ Cet avis est déjà engagé ({etats}) : la suppression ne l'annule pas")
        info += " auprès de l'ANTAI ni dans votre facturation."
    info += "\n\nLa suppression est inscrite au journal. Un avis supprimé peut être réimporté depuis son scan."
    box.setInformativeText(info)
    cb = QCheckBox("Supprimer aussi le PDF archivé")
    box.setCheckBox(cb)
    yes = box.addButton("Supprimer", QMessageBox.DestructiveRole)
    no = box.addButton("Annuler", QMessageBox.RejectRole)
    box.setDefaultButton(no)
    box.exec()
    if box.clickedButton() is not yes:
        return False
    services.delete_pv([r["id"] for r in rows], delete_files=cb.isChecked())
    return True
