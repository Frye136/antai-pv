"""Formulaire unique « Nouvelle location » : véhicule + client + contrat en un seul écran.

Le véhicule et le client peuvent être existants ou créés à la volée ; tout est enregistré en une transaction.
"""
from datetime import date, datetime, timedelta

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QCompleter, QDateTimeEdit, QDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import antai_export, db, parser, plates, referentiel, services


def _searchable(combo: QComboBox):
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.completer().setFilterMode(Qt.MatchContains)
    combo.completer().setCompletionMode(QCompleter.PopupCompletion)


def _dt_edit(value: datetime) -> QDateTimeEdit:
    w = QDateTimeEdit(QDateTime(value))
    w.setCalendarPopup(True)
    w.setDisplayFormat("dd/MM/yyyy HH:mm")
    return w


def next_code(prefix: str, table: str, col: str, width: int = 3) -> str:
    """Prochain code libre : C004, P002, LOC-26-012…"""
    n = 0
    for r in db.q(f"SELECT {col} v FROM {table} WHERE {col} LIKE ?", (prefix + "%",)):
        tail = (r["v"] or "")[len(prefix):]
        if tail.isdigit():
            n = max(n, int(tail))
    return f"{prefix}{n + 1:0{width}d}"


class LocationDialog(QDialog):
    def __init__(self, parent=None, immat: str | None = None, debut: datetime | None = None,
                 fin: datetime | None = None, client_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("Nouvelle location")
        self.resize(760, 860)
        self.created_contract_id = None

        # ------------------------------------------------ véhicule
        self.immat = QComboBox()
        _searchable(self.immat)
        self.immat.addItem("")
        for r in db.q("SELECT * FROM vehicules ORDER BY immatriculation"):
            self.immat.addItem(plates.display(r["immatriculation"]))
        self.immat.lineEdit().setPlaceholderText("AB-123-CD — plaque existante ou nouvelle")
        self.veh_info = QLabel()
        self.veh_info.setObjectName("hint")
        self.marque, self.modele, self.categorie = QLineEdit(), QLineEdit(), QLineEdit()
        self.categorie.setPlaceholderText("Utilitaire, VL, Porteur…")
        g_veh = QGroupBox("1. Véhicule")
        fv = QFormLayout(g_veh)
        fv.addRow("Immatriculation *", self.immat)
        fv.addRow("", self.veh_info)
        self.new_veh_rows = []
        for label, w in (("Marque", self.marque), ("Modèle", self.modele), ("Catégorie", self.categorie)):
            fv.addRow(label, w)
            self.new_veh_rows.append(w)
        self.fv = fv

        # ------------------------------------------------ client
        self.rb_existing = QRadioButton("Client existant")
        self.rb_new = QRadioButton("Nouveau client")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_existing)
        grp.addButton(self.rb_new)
        self.client = QComboBox()
        _searchable(self.client)
        self.client.addItem("", None)
        for r in db.q("SELECT * FROM clients ORDER BY COALESCE(raison_sociale, nom)"):
            name = r["raison_sociale"] or f"{r['nom'] or ''} {r['prenom'] or ''}".strip()
            self.client.addItem(f"{name}  ({r['code_client'] or '—'} · {r['ville'] or ''})", r["id"])
        self.client.lineEdit().setPlaceholderText("Rechercher un client…")

        self.rb_pm = QRadioButton("Entreprise")
        self.rb_pp = QRadioButton("Particulier")
        grp2 = QButtonGroup(self)
        grp2.addButton(self.rb_pm)
        grp2.addButton(self.rb_pp)
        self.rb_pm.setChecked(True)
        self.raison, self.siret = QLineEdit(), QLineEdit()
        self.civ = QComboBox()
        self.civ.addItem("—", None)  # choix obligatoire : une civilité erronée serait transmise à l'ANTAI
        self.civ.addItem("M.", "M")
        self.civ.addItem("Mme", "MME")
        self.nom, self.prenom = QLineEdit(), QLineEdit()
        self.naissance, self.lieu_naissance = QLineEdit(), QLineEdit()
        self.permis, self.date_permis = QLineEdit(), QLineEdit()
        for w in (self.naissance, self.date_permis):
            w.setPlaceholderText("jj/mm/aaaa")
        self.adresse, self.complement = QLineEdit(), QLineEdit()
        self.adresse.setPlaceholderText("n° et voie")
        self.cp, self.ville, self.pays = QLineEdit(), QLineEdit(), QLineEdit("FRANCE")
        self.email, self.tel = QLineEdit(), QLineEdit()

        g_cli = QGroupBox("2. Client (locataire)")
        cl = QVBoxLayout(g_cli)
        row = QHBoxLayout()
        row.addWidget(self.rb_existing)
        row.addWidget(self.rb_new)
        row.addStretch()
        cl.addLayout(row)
        cl.addWidget(self.client)
        self.new_cli = QWidget()
        fc = QFormLayout(self.new_cli)
        fc.setContentsMargins(0, 4, 0, 0)
        trow = QHBoxLayout()
        trow.addWidget(self.rb_pm)
        trow.addWidget(self.rb_pp)
        trow.addStretch()
        fc.addRow("Type", trow)
        self.pm_rows = [("Raison sociale *", self.raison), ("SIRET", self.siret)]
        civ_nom = QHBoxLayout()
        civ_nom.addWidget(self.civ)
        civ_nom.addWidget(self.nom, 1)
        self.pp_rows = [("Civilité / Nom *", civ_nom), ("Prénom *", self.prenom),
                        ("Date de naissance *", self.naissance), ("Lieu de naissance", self.lieu_naissance),
                        ("N° de permis", self.permis), ("Permis délivré le", self.date_permis)]
        for label, w in self.pm_rows + self.pp_rows:
            fc.addRow(label, w)
        cpv = QHBoxLayout()
        cpv.addWidget(self.cp)
        cpv.addWidget(self.ville, 3)
        self.cp.setPlaceholderText("Code postal")
        self.ville.setPlaceholderText("Ville")
        fc.addRow("Adresse *", self.adresse)
        fc.addRow("Complément", self.complement)
        fc.addRow("CP / Ville *", cpv)
        fc.addRow("Pays", self.pays)
        fc.addRow("E-mail", self.email)
        fc.addRow("Téléphone", self.tel)
        self.fc = fc
        cl.addWidget(self.new_cli)

        # ------------------------------------------------ contrat
        now = datetime.now().replace(second=0, microsecond=0)
        self.numero = QLineEdit(next_code(f"LOC-{date.today():%y}-", "contrats", "numero"))
        self.debut = _dt_edit(debut or now)
        self.fin = _dt_edit(fin or (debut or now) + timedelta(days=7))
        self.en_cours = QCheckBox("Location en cours (pas encore de date de retour)")
        self.en_cours.toggled.connect(lambda on: self.fin.setEnabled(not on))
        self.g_drv = QGroupBox("Conducteur nommé (facultatif) — à désigner à la place du client")
        self.g_drv.setCheckable(True)
        self.g_drv.setChecked(False)
        self.d_nom, self.d_prenom, self.d_naiss, self.d_lieu = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.d_permis, self.d_adresse, self.d_cp, self.d_ville = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.d_naiss.setPlaceholderText("jj/mm/aaaa")
        fd = QFormLayout(self.g_drv)
        for label, w in (("Nom", self.d_nom), ("Prénom", self.d_prenom), ("Date de naissance", self.d_naiss),
                         ("Lieu de naissance", self.d_lieu), ("N° de permis", self.d_permis),
                         ("Adresse", self.d_adresse), ("Code postal", self.d_cp), ("Ville", self.d_ville)):
            fd.addRow(label, w)
        g_con = QGroupBox("3. Contrat")
        fk = QFormLayout(g_con)
        fk.addRow("N° de contrat", self.numero)
        fk.addRow("Départ *", self.debut)
        fk.addRow("Retour", self.fin)
        fk.addRow("", self.en_cours)
        fk.addRow(self.g_drv)

        # ------------------------------------------------ bilan + boutons
        self.check = QLabel()
        self.check.setWordWrap(True)
        self.check.setTextFormat(Qt.RichText)
        self.check.setStyleSheet("padding:8px; border-radius:4px;")
        save = QPushButton("Enregistrer la location")
        save.setProperty("primary", True)
        save.clicked.connect(self.save)
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(save)

        inner = QWidget()
        il = QVBoxLayout(inner)
        for g in (g_veh, g_cli, g_con):
            il.addWidget(g)
        il.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        lay = QVBoxLayout(self)
        lay.addWidget(scroll, 1)
        lay.addWidget(self.check)
        lay.addLayout(btns)

        # ------------------------------------------------ comportements
        self.immat.editTextChanged.connect(self._vehicle_changed)
        for rb in (self.rb_existing, self.rb_new, self.rb_pm, self.rb_pp):
            rb.toggled.connect(self._client_mode)
        self.client.currentIndexChanged.connect(self._update_check)
        self.civ.currentIndexChanged.connect(self._update_check)
        for w in (self.raison, self.nom, self.prenom, self.naissance, self.adresse, self.cp, self.ville, self.pays,
                  self.permis, self.date_permis, self.email, self.d_nom, self.d_prenom, self.d_naiss):
            w.textChanged.connect(self._update_check)
        for w in (self.debut, self.fin):
            w.dateTimeChanged.connect(self._update_check)
        self.en_cours.toggled.connect(self._update_check)
        self.g_drv.toggled.connect(self._update_check)

        if client_id:
            self.client.setCurrentIndex(max(0, self.client.findData(client_id)))
        (self.rb_existing if client_id or self.client.count() > 1 else self.rb_new).setChecked(True)
        if immat:
            self.immat.setEditText(plates.display(immat))
        self._vehicle_changed(self.immat.currentText())
        self._client_mode()

    # ------------------------------------------------------------------ état du formulaire
    def _vehicle_changed(self, text):
        p = plates.normalize(text)
        v = db.q1("SELECT * FROM vehicules WHERE immatriculation=?", (p,)) if p else None
        for w in self.new_veh_rows:
            self.fv.setRowVisible(w, bool(p) and not v)
        if not p:
            self.veh_info.setText("")
        elif v:
            last = db.q1("""SELECT k.numero, k.date_fin, COALESCE(c.raison_sociale, c.nom) client FROM contrats k
                            JOIN clients c ON c.id=k.client_id WHERE k.vehicule_id=? ORDER BY k.date_debut DESC LIMIT 1""",
                         (v["id"],))
            txt = f"Véhicule existant : {v['marque'] or ''} {v['modele'] or ''}".strip()
            if last:
                txt += f" — dernier contrat {last['numero']} ({last['client']}, " \
                       f"{'en cours' if not last['date_fin'] else 'retour ' + parser.fmt_date(last['date_fin'])})"
            self.veh_info.setText(txt)
        else:
            valid = len(p) >= 5
            self.veh_info.setText("➕ Nouveau véhicule : il sera créé à l'enregistrement" if valid
                                  else "Immatriculation incomplète")
        self._update_check()

    def _client_mode(self, *_):
        new = self.rb_new.isChecked()
        self.client.setVisible(not new)
        self.new_cli.setVisible(new)
        pm = self.rb_pm.isChecked()
        for _, w in self.pm_rows:
            self.fc.setRowVisible(w, pm)
        for _, w in self.pp_rows:
            self.fc.setRowVisible(w, not pm)
        self._update_check()

    def _new_client_values(self) -> dict:
        pm = self.rb_pm.isChecked()
        v = {
            "type": "PM" if pm else "PP",
            "raison_sociale": self.raison.text().strip() if pm else None,
            "siret": self.siret.text().strip() if pm else None,
            "civilite": None if pm else self.civ.currentData(),
            "nom": None if pm else self.nom.text().strip().upper(),
            "prenom": None if pm else self.prenom.text().strip(),
            "date_naissance": None if pm else referentiel.norm_date(self.naissance.text().strip()),
            "lieu_naissance": None if pm else self.lieu_naissance.text().strip(),
            "num_permis": None if pm else self.permis.text().strip(),
            "date_permis": None if pm else referentiel.norm_date(self.date_permis.text().strip()),
            "adresse": self.adresse.text().strip(), "complement": self.complement.text().strip(),
            "code_postal": referentiel.coerce("clients", "code_postal", "text", self.cp.text()),
            "ville": self.ville.text().strip().upper(), "pays": self.pays.text().strip().upper() or "FRANCE",
            "email": self.email.text().strip(), "telephone": self.tel.text().strip(),
        }
        return {k: (val or None) for k, val in v.items()}

    def _period(self) -> tuple[str, str | None]:
        d = self.debut.dateTime().toPython().strftime("%Y-%m-%d %H:%M")
        f = None if self.en_cours.isChecked() else self.fin.dateTime().toPython().strftime("%Y-%m-%d %H:%M")
        return d, f

    def _designee(self) -> dict:
        if self.g_drv.isChecked() and self.d_nom.text().strip():
            return {"type": "PP", "civilite": "M", "nom": self.d_nom.text(), "prenom": self.d_prenom.text(),
                    "date_naissance": referentiel.norm_date(self.d_naiss.text().strip()),
                    "adresse": self.d_adresse.text(), "code_postal": self.d_cp.text(), "ville": self.d_ville.text(),
                    "pays": "FRANCE", "num_permis": self.d_permis.text()}
        if self.rb_new.isChecked():
            return self._new_client_values()
        cid = self.client.currentData()
        c = db.q1("SELECT * FROM clients WHERE id=?", (cid,)) if cid else None
        return {k: c[k] for k in c.keys()} if c else {}

    def _problems(self) -> tuple[list[str], list[str]]:
        """(erreurs bloquantes, points manquants pour la désignation ANTAI)."""
        errors = []
        if len(plates.normalize(self.immat.currentText())) < 5:
            errors.append("immatriculation")
        if self.rb_existing.isChecked() and not self.client.currentData():
            errors.append("client à choisir")
        if self.rb_new.isChecked():
            v = self._new_client_values()
            if v["type"] == "PM" and not v["raison_sociale"]:
                errors.append("raison sociale")
            if v["type"] == "PP" and not v["nom"]:
                errors.append("nom du client")
            if v["type"] == "PP" and not v["civilite"]:
                errors.append("civilité")
            if self.naissance.text().strip() and not v["date_naissance"] and v["type"] == "PP":
                errors.append("date de naissance invalide")
        d, f = self._period()
        if f and f < d:
            errors.append("retour avant le départ")
        fake_pv = {"numero_avis": "0000000000", "immatriculation": "X", "date_avis": "X", "titulaire": "X"}
        missing = antai_export.missing_fields(self._designee(), fake_pv) if not errors else []
        return errors, missing

    def _update_check(self, *_):
        errors, missing = self._problems()
        if errors:
            self.check.setText("<b>À compléter :</b> " + ", ".join(errors))
            self.check.setStyleSheet("padding:8px; border-radius:4px; background:#FFF4D6; color:#8A5A00;")
        elif missing:
            self.check.setText("Enregistrable, mais la <b>désignation ANTAI sera bloquée</b> tant que manquent : "
                               + ", ".join(missing))
            self.check.setStyleSheet("padding:8px; border-radius:4px; background:#FDE2E2; color:#9B1C1C;")
        else:
            self.check.setText("✔ Tout est prêt : un avis sur ce véhicule pendant la location pourra être dénoncé "
                               "automatiquement.")
            self.check.setStyleSheet("padding:8px; border-radius:4px; background:#DDF3E4; color:#1F6B3A;")

    # ------------------------------------------------------------------ enregistrement
    def save(self):
        errors, missing = self._problems()
        if errors:
            QMessageBox.warning(self, "Nouvelle location", "À compléter : " + ", ".join(errors))
            return
        immat = plates.normalize(self.immat.currentText())
        d, f = self._period()
        veh = db.q1("SELECT id FROM vehicules WHERE immatriculation=?", (immat,))
        if veh:
            overlap = db.q("""SELECT k.numero, COALESCE(c.raison_sociale, c.nom) client FROM contrats k
                              JOIN clients c ON c.id=k.client_id WHERE k.vehicule_id=? AND k.date_debut<=?
                              AND (k.date_fin IS NULL OR k.date_fin>=?)""", (veh["id"], f or "9999", d))
            if overlap and QMessageBox.question(
                    self, "Chevauchement", "Ce véhicule est déjà loué sur cette période :\n"
                    + "\n".join(f"• {o['numero']} – {o['client']}" for o in overlap)
                    + "\n\nEnregistrer quand même ?") != QMessageBox.Yes:
                return
        if missing and QMessageBox.question(self, "Désignation incomplète",
                                            "Il manque pour la désignation ANTAI : " + ", ".join(missing)
                                            + "\n\nEnregistrer quand même ?") != QMessageBox.Yes:
            return

        conn = db.get()
        try:
            with db.lock:
                if not veh:
                    cur = conn.execute("INSERT INTO vehicules(immatriculation, marque, modele, categorie) VALUES(?,?,?,?)",
                                       (immat, self.marque.text().strip().upper() or None,
                                        self.modele.text().strip() or None, self.categorie.text().strip() or None))
                    veh_id = cur.lastrowid
                else:
                    veh_id = veh["id"]
                if self.rb_new.isChecked():
                    v = self._new_client_values()
                    v["code_client"] = next_code("C" if v["type"] == "PM" else "P", "clients", "code_client")
                    cols = ", ".join(v)
                    client_id = conn.execute(f"INSERT INTO clients({cols}) VALUES({', '.join('?' * len(v))})",
                                             tuple(v.values())).lastrowid
                else:
                    client_id = self.client.currentData()
                k = {"numero": self.numero.text().strip() or next_code(f"LOC-{date.today():%y}-", "contrats", "numero"),
                     "vehicule_id": veh_id, "client_id": client_id, "date_debut": d, "date_fin": f}
                if self.g_drv.isChecked() and self.d_nom.text().strip():
                    k.update(cond_nom=self.d_nom.text().strip().upper(), cond_prenom=self.d_prenom.text().strip(),
                             cond_date_naissance=referentiel.norm_date(self.d_naiss.text().strip()),
                             cond_lieu_naissance=self.d_lieu.text().strip(), cond_num_permis=self.d_permis.text().strip(),
                             cond_adresse=self.d_adresse.text().strip(), cond_code_postal=self.d_cp.text().strip(),
                             cond_ville=self.d_ville.text().strip().upper(), designer_conducteur=1)
                cols = ", ".join(k)
                self.created_contract_id = conn.execute(
                    f"INSERT INTO contrats({cols}) VALUES({', '.join('?' * len(k))})", tuple(k.values())).lastrowid
                conn.commit()
        except Exception as e:
            conn.rollback()
            msg = "Ce n° de contrat existe déjà." if "UNIQUE" in str(e) and "numero" in str(e) else str(e)
            QMessageBox.warning(self, "Nouvelle location", f"Enregistrement impossible : {msg}")
            return
        db.log("Nouvelle location", f"{k['numero']} – {plates.display(immat)}")
        # un avis en attente sur ce véhicule / cette période peut maintenant être identifié
        services.reidentify_open()
        newly = db.q("SELECT numero_avis FROM pv WHERE statut IN ('A_DENONCER','A_PAYER') AND contrat_id=?",
                     (self.created_contract_id,))
        newly = [r["numero_avis"] for r in newly if r["numero_avis"]]
        if newly:
            QMessageBox.information(self, "Nouvelle location",
                                    f"Location enregistrée.\n\n{len(newly)} avis en attente rattaché(s) à ce contrat "
                                    f"(à dénoncer ou à payer) : {', '.join(newly)}")
        self.accept()
