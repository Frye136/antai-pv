"""Paramètres : général, e-mail, format d'export ANTAI, sauvegarde."""
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .. import antai_export, config, db, mailer
from .common import open_path
from .pages import JournalPage, button, page_header


def _browse_dir(edit: QLineEdit, parent):
    d = QFileDialog.getExistingDirectory(parent, "Choisir un dossier", edit.text())
    if d:
        edit.setText(d)


class SettingsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        tabs = QTabWidget()
        tabs.addTab(self._general(), "Général")
        tabs.addTab(self._mail(), "E-mail")
        tabs.addTab(self._export(), "Format export ANTAI")
        tabs.addTab(self._backup(), "Données && sauvegarde")
        self.journal = JournalPage(main, embedded=True)
        self.tabs = tabs
        tabs.addTab(self.journal, "Journal")
        tabs.insertTab(tabs.indexOf(self.journal), self._updates(), "Mises à jour")
        tabs.currentChanged.connect(lambda i: self.journal.refresh() if tabs.widget(i) is self.journal else None)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addLayout(page_header("Paramètres", button("Enregistrer", self.save, primary=True)))
        lay.addWidget(tabs, 1)
        self.load()

    # ------------------------------------------------------------------ onglets
    def _general(self):
        w = QWidget()
        f = QFormLayout(w)
        self.loueur = QLineEdit()
        self.siret = QLineEdit()
        self.delai = QSpinBox()
        self.delai.setRange(1, 365)
        self.alerte = QSpinBox()
        self.alerte.setRange(1, 60)
        self.frais = QLineEdit()
        self.depot = QLineEdit()
        self.watch = QCheckBox("Surveiller ce dossier et importer automatiquement les nouveaux scans (toutes les minutes)")
        dep = QHBoxLayout()
        dep.addWidget(self.depot)
        dep.addWidget(button("Parcourir…", lambda: _browse_dir(self.depot, self)))
        f.addRow("Votre raison sociale, telle que sur les avis", self.loueur)
        f.addRow("Votre SIRET", self.siret)
        f.addRow("Délai de désignation (jours)", self.delai)
        f.addRow("Alerter quand l'échéance est à moins de (jours)", self.alerte)
        self.delai_fps = QSpinBox()
        self.delai_fps.setRange(1, 365)
        f.addRow("FPS : délai de paiement avant majoration (jours)", self.delai_fps)
        self.stationnement = QCheckBox("Contraventions de stationnement : payer et refacturer (au lieu de désigner)")
        f.addRow("", self.stationnement)
        f.addRow("Frais de dossier par défaut (€ HT)", self.frais)
        f.addRow("Dossier de dépôt des scans", dep)
        f.addRow("", self.watch)
        hint = QLabel("Astuce : configurez le copieur pour « numériser vers dossier » dans le dossier de dépôt. "
                      "Un PDF peut contenir plusieurs avis (recto/verso) : ils sont découpés automatiquement.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        f.addRow("", hint)
        return w

    def _mail(self):
        w = QWidget()
        f = QFormLayout(w)
        self.mode = QComboBox()
        self.mode.addItem("Serveur SMTP", "smtp")
        self.mode.addItem("Outlook installé sur ce poste", "outlook")
        self.host = QLineEdit()
        self.host.setPlaceholderText("ex. smtp.office365.com / ssl0.ovh.net")
        self.port = QLineEdit()
        self.sec = QComboBox()
        for lab, code in [("STARTTLS (587)", "starttls"), ("SSL/TLS (465)", "ssl"), ("Aucune", "none")]:
            self.sec.addItem(lab, code)
        self.user = QLineEdit()
        self.pwd = QLineEdit()
        self.pwd.setEchoMode(QLineEdit.Password)
        self.pwd.setPlaceholderText("inchangé")
        self.sender = QLineEdit()
        self.bcc = QLineEdit()
        self.bcc.setPlaceholderText("copie cachée systématique (archivage), facultatif")
        self.subject = QLineEdit()
        self.body = QPlainTextEdit()
        self.body.setMinimumHeight(200)
        self.ligne = QLineEdit()
        self.body_pay = QPlainTextEdit()
        self.body_pay.setMinimumHeight(200)
        f.addRow("Mode d'envoi", self.mode)
        f.addRow("Serveur SMTP", self.host)
        f.addRow("Port", self.port)
        f.addRow("Sécurité", self.sec)
        f.addRow("Identifiant", self.user)
        f.addRow("Mot de passe", self.pwd)
        f.addRow("Expéditeur", self.sender)
        f.addRow("Cci", self.bcc)
        f.addRow("", button("Tester la connexion", self.test_mail))
        f.addRow("Objet", self.subject)
        f.addRow("Message (avis dénoncés)", self.body)
        f.addRow("Message (avis payés et refacturés)", self.body_pay)
        f.addRow("Ligne par avis ({liste_pv})", self.ligne)
        hint = QLabel("Variables : {client} {raison_sociale} {nom} {prenom} {nb_pv} {liste_pv} {immatriculations} "
                      "{frais_total} {montant_total} (montant payé) {loueur} — et, par avis : {numero_avis} {immatriculation} {date_infraction} "
                      "{heure_infraction} {lieu} {nature} {montant} {date_avis} {frais_dossier}")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        f.addRow("", hint)
        return w

    def _export(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()
        self.sep = QComboBox()
        for lab, v in [("Point-virgule ;", ";"), ("Virgule ,", ","), ("Tabulation", "\t"), ("Barre |", "|")]:
            self.sep.addItem(lab, v)
        self.enc = QComboBox()
        for lab, v in [("Windows-1252 (ANSI, modèle ANTAI)", "cp1252"), ("UTF-8 avec BOM", "utf-8-sig"), ("UTF-8", "utf-8")]:
            self.enc.addItem(lab, v)
        self.datefmt = QComboBox()
        for lab, v in [("jj/mm/aaaa", "%d/%m/%Y"), ("aaaa-mm-jj", "%Y-%m-%d"), ("jjmmaaaa", "%d%m%Y")]:
            self.datefmt.addItem(lab, v)
        self.header = QCheckBox("Ligne d'en-têtes")
        self.tirets = QCheckBox("Immatriculation avec tirets (AB-123-CD)")
        self.civ_m = QLineEdit()
        self.civ_f = QLineEdit()
        self.civ_pm = QLineEdit()
        self.maxl = QSpinBox()
        self.maxl.setRange(0, 100)
        self.maxl.setSpecialValueText("illimité")
        f.addRow("Séparateur", self.sep)
        f.addRow("Encodage", self.enc)
        f.addRow("Format des dates", self.datefmt)
        f.addRow("", self.header)
        f.addRow("", self.tirets)
        civ = QHBoxLayout()
        civ.addWidget(QLabel("Homme :"))
        civ.addWidget(self.civ_m)
        civ.addWidget(QLabel("Femme :"))
        civ.addWidget(self.civ_f)
        civ.addWidget(QLabel("Société :"))
        civ.addWidget(self.civ_pm)
        f.addRow("Civilités", civ)
        f.addRow("Lignes max. par fichier", self.maxl)
        lay.addLayout(f)
        self.cols = QTableWidget(0, 2)
        self.cols.setHorizontalHeaderLabels(["Titre de la colonne (en-tête)", "Donnée"])
        self.cols.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cols.verticalHeader().setDefaultSectionSize(28)
        lay.addWidget(self.cols, 1)
        b = QHBoxLayout()
        for text, fn in [("＋ Colonne", self.add_col), ("− Supprimer", self.del_col), ("▲", lambda: self.move_col(-1)),
                         ("▼", lambda: self.move_col(1)), ("Importer un modèle CSV ANTAI…", self.import_model),
                         ("Réinitialiser (modèle ANTAI)", self.reset_template)]:
            b.addWidget(button(text, fn))
        b.addStretch()
        lay.addLayout(b)
        hint = QLabel("Par défaut : modèle CSV officiel ANTAI (18 colonnes, 100 désignations max par fichier). "
                      "« Raison sociale désignant » = le titulaire inscrit sur l'avis (vous), « SIRET » = celui de la société désignée (vide pour une personne) ; "
                      "une entreprise désignée a la civilité SOCIETE et sa raison sociale dans « Nom ou Raison sociale ». "
                      "Si l'ANTAI change son modèle, importez simplement le nouveau fichier : les colonnes sont "
                      "associées automatiquement.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

    def _updates(self):
        w = QWidget()
        f = QFormLayout(w)
        url = f"https://github.com/{config.GITHUB_REPO}"
        f.addRow("Version installée", QLabel(f"<b>{config.VERSION}</b>"))
        link = QLabel(f'<a href="{url}">{url}</a> — logiciel libre (licence MIT)')
        link.setOpenExternalLinks(True)
        f.addRow("Projet", link)
        self.maj_auto = QCheckBox("Rechercher une nouvelle version à chaque démarrage")
        f.addRow("", self.maj_auto)
        f.addRow("", button("Rechercher une mise à jour maintenant", lambda: self.main.check_updates(manual=True)))
        hint = QLabel("La recherche interroge uniquement l'API publique de GitHub (aucune donnée transmise). "
                      "La nouvelle version est téléchargée, son empreinte SHA-256 vérifiée, puis elle remplace "
                      "AntaiPV.exe au redémarrage. Vos données (base, archives) ne sont pas modifiées.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        f.addRow("", hint)
        return w

    def _backup(self):
        w = QWidget()
        f = QFormLayout(w)
        self.datadir = QLineEdit(str(config.data_dir()))
        row = QHBoxLayout()
        row.addWidget(self.datadir)
        row.addWidget(button("Parcourir…", lambda: _browse_dir(self.datadir, self)))
        f.addRow("Dossier des données", row)
        hint = QLabel("Contient la base (antai_pv.db), l'archive des PDF, les lots CSV et les sauvegardes. "
                      "Changer de dossier nécessite un redémarrage (les fichiers ne sont pas déplacés automatiquement). "
                      "Une sauvegarde de la base est faite chaque jour à l'ouverture (30 conservées).")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        f.addRow("", hint)
        b = QHBoxLayout()
        b.addWidget(button("Ouvrir le dossier des données", lambda: open_path(config.data_dir())))
        b.addWidget(button("Ouvrir l'archive des avis", lambda: open_path(config.sub("archive"))))
        b.addWidget(button("Sauvegarder maintenant", self.backup_now))
        b.addStretch()
        f.addRow("", b)
        return w

    # ------------------------------------------------------------------ chargement / enregistrement
    def load(self):
        s = db.setting
        self.loueur.setText(s("loueur_raison_sociale"))
        self.siret.setText(s("loueur_siret"))
        self.delai.setValue(int(s("delai_jours") or 45))
        self.alerte.setValue(int(s("alerte_jours") or 10))
        self.delai_fps.setValue(int(s("delai_fps_jours") or 90))
        self.stationnement.setChecked(s("stationnement_payer") == "1")
        self.maj_auto.setChecked(s("maj_auto") == "1")
        self.frais.setText(s("frais_dossier"))
        self.depot.setText(s("dossier_depot"))
        self.watch.setChecked(s("surveiller_depot") == "1")
        self.mode.setCurrentIndex(max(0, self.mode.findData(s("mail_mode"))))
        self.host.setText(s("smtp_host"))
        self.port.setText(s("smtp_port"))
        self.sec.setCurrentIndex(max(0, self.sec.findData(s("smtp_security"))))
        self.user.setText(s("smtp_user"))
        self.sender.setText(s("smtp_from"))
        self.bcc.setText(s("smtp_bcc"))
        self.subject.setText(s("mail_sujet"))
        self.body.setPlainText(s("mail_corps"))
        self.body_pay.setPlainText(s("mail_corps_paiement"))
        self.ligne.setText(s("mail_ligne_pv"))
        self._load_template(antai_export.template())

    def _load_template(self, t: dict):
        self.sep.setCurrentIndex(max(0, self.sep.findData(t.get("separator", ";"))))
        self.enc.setCurrentIndex(max(0, self.enc.findData(t.get("encoding", "cp1252"))))
        self.datefmt.setCurrentIndex(max(0, self.datefmt.findData(t.get("date_format", "%d/%m/%Y"))))
        self.header.setChecked(t.get("header", True))
        self.tirets.setChecked(t.get("plaque_tirets", False))
        civ = t.get("civilites", {})
        self.civ_m.setText(civ.get("M", "M."))
        self.civ_f.setText(civ.get("MME", "MME"))
        self.civ_pm.setText(civ.get("PM", "SOCIETE"))
        self.maxl.setValue(int(t.get("max_lignes") or 0))
        self.cols.setRowCount(0)
        for c in t["columns"]:
            self._append_col(c["titre"], c["champ"])

    def _append_col(self, titre="", champ=""):
        r = self.cols.rowCount()
        self.cols.insertRow(r)
        self.cols.setItem(r, 0, QTableWidgetItem(titre))
        combo = QComboBox()
        for key, lab in antai_export.FIELDS.items():
            combo.addItem(lab, key)
        if champ.startswith("="):
            combo.addItem(f"Valeur fixe : {champ[1:]}", champ)
        combo.setCurrentIndex(max(0, combo.findData(champ)))
        self.cols.setCellWidget(r, 1, combo)

    def _template_from_ui(self) -> dict:
        cols = []
        for r in range(self.cols.rowCount()):
            titre = self.cols.item(r, 0).text() if self.cols.item(r, 0) else ""
            cols.append({"titre": titre, "champ": self.cols.cellWidget(r, 1).currentData()})
        return {"separator": self.sep.currentData(), "encoding": self.enc.currentData(),
                "date_format": self.datefmt.currentData(), "header": self.header.isChecked(),
                "plaque_tirets": self.tirets.isChecked(),
                "civilites": {"M": self.civ_m.text().strip(), "MME": self.civ_f.text().strip(),
                              "PM": self.civ_pm.text().strip()},
                "version": 2,
                "max_lignes": self.maxl.value(), "columns": cols}

    def add_col(self):
        self._append_col()

    def del_col(self):
        r = self.cols.currentRow()
        if r >= 0:
            self.cols.removeRow(r)

    def move_col(self, d):
        r = self.cols.currentRow()
        t = r + d
        if r < 0 or not 0 <= t < self.cols.rowCount():
            return
        items = [(self.cols.item(i, 0).text() if self.cols.item(i, 0) else "", self.cols.cellWidget(i, 1).currentData())
                 for i in range(self.cols.rowCount())]
        items[r], items[t] = items[t], items[r]
        self.cols.setRowCount(0)
        for titre, champ in items:
            self._append_col(titre, champ)
        self.cols.setCurrentCell(t, 0)

    def import_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Modèle CSV fourni par l'ANTAI", "", "CSV (*.csv *.txt)")
        if path:
            try:
                self._load_template(antai_export.template_from_model(path))
                QMessageBox.information(self, "Modèle importé", "Colonnes chargées et associées automatiquement. "
                                        "Vérifiez la colonne « Donnée » puis enregistrez.")
            except Exception as e:
                QMessageBox.warning(self, "Modèle", str(e))

    def reset_template(self):
        self._load_template(json.loads(json.dumps(antai_export.DEFAULT_TEMPLATE)))

    def save(self):
        try:
            float(self.frais.text().replace(",", ".") or 0)
        except ValueError:
            QMessageBox.warning(self, "Paramètres", "Frais de dossier invalides.")
            return
        vals = {
            "loueur_raison_sociale": self.loueur.text().strip(), "loueur_siret": self.siret.text().strip(),
            "delai_jours": self.delai.value(), "alerte_jours": self.alerte.value(),
            "frais_dossier": self.frais.text().strip().replace(",", "."),
            "dossier_depot": self.depot.text().strip(), "surveiller_depot": "1" if self.watch.isChecked() else "0",
            "delai_fps_jours": self.delai_fps.value(),
            "stationnement_payer": "1" if self.stationnement.isChecked() else "0",
            "maj_auto": "1" if self.maj_auto.isChecked() else "0",
            "mail_mode": self.mode.currentData(), "smtp_host": self.host.text().strip(),
            "smtp_port": self.port.text().strip(), "smtp_security": self.sec.currentData(),
            "smtp_user": self.user.text().strip(), "smtp_from": self.sender.text().strip(),
            "smtp_bcc": self.bcc.text().strip(), "mail_sujet": self.subject.text(),
            "mail_corps": self.body.toPlainText(), "mail_corps_paiement": self.body_pay.toPlainText(),
            "mail_ligne_pv": self.ligne.text(),
            "export_template": json.dumps(self._template_from_ui(), ensure_ascii=False),
        }
        if self.pwd.text():
            vals["smtp_password"] = mailer.protect(self.pwd.text())
            self.pwd.clear()
        for k, v in vals.items():
            db.set_setting(k, v)
        db.log("Paramètres modifiés")
        if self.datadir.text().strip() != str(config.data_dir()):
            config.set_data_dir(self.datadir.text().strip())
            QMessageBox.information(self, "Dossier des données", "Le nouveau dossier sera utilisé au prochain démarrage.")
        self.main.status("Paramètres enregistrés.")
        self.main.refresh_all()

    def test_mail(self):
        self.save()
        try:
            QMessageBox.information(self, "E-mail", mailer.test_connection())
        except Exception as e:
            QMessageBox.warning(self, "E-mail", f"Échec : {e}")

    def backup_now(self):
        path = db.backup(force=True)
        QMessageBox.information(self, "Sauvegarde", f"Base sauvegardée :\n{path}")

    def refresh(self):
        if self.tabs.currentWidget() is self.journal:
            self.journal.refresh()
