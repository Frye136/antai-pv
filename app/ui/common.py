"""Éléments d'interface partagés : style, tâches de fond, modèle de table, formulaire générique."""
import os
import traceback

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QScrollArea, QTableView, QVBoxLayout, QWidget)

from .. import db, parser, plates, referentiel

NAVY = "#1F3A5F"
ACCENT = "#E8772E"

STYLE = f"""
QWidget {{ font-family: 'Segoe UI'; font-size: 10pt; color: #1d2733; }}
QMainWindow, QDialog {{ background: #F4F6F9; }}
#sidebar {{ background: {NAVY}; border: none; }}
#sidebar QPushButton {{ color: #D5DEEA; background: transparent; border: none; text-align: left;
    padding: 10px 18px; font-size: 10.5pt; border-left: 3px solid transparent; }}
#sidebar QPushButton:hover {{ background: #27496F; color: white; }}
#sidebar QPushButton:checked {{ background: #2C5282; color: white; border-left: 3px solid {ACCENT}; font-weight: 600; }}
#brand {{ color: white; font-size: 14pt; font-weight: 700; padding: 18px 18px 2px 18px; }}
#brandsub {{ color: #93A8C3; font-size: 8.5pt; padding: 0 18px 14px 18px; }}
#pageTitle {{ font-size: 16pt; font-weight: 600; color: {NAVY}; }}
QPushButton {{ background: white; border: 1px solid #C9D2DE; border-radius: 5px; padding: 6px 12px; }}
QPushButton:hover {{ background: #EEF3F9; border-color: #9FB2C9; }}
QPushButton:disabled {{ color: #9aa5b1; }}
QPushButton[primary="true"] {{ background: {NAVY}; color: white; border-color: {NAVY}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: #2C5282; }}
QPushButton[accent="true"] {{ background: {ACCENT}; color: white; border-color: {ACCENT}; font-weight: 600; }}
QPushButton[accent="true"]:hover {{ background: #F08A46; }}
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {{ background: white; border: 1px solid #C9D2DE;
    border-radius: 4px; padding: 4px 6px; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {NAVY}; }}
QTableView {{ background: white; border: 1px solid #D8DFE8; gridline-color: #EDF0F4;
    selection-background-color: #CFE0F5; selection-color: #1d2733; alternate-background-color: #F8FAFC; }}
QHeaderView::section {{ background: #E9EEF4; border: none; border-right: 1px solid #D8DFE8;
    padding: 5px; font-weight: 600; color: #34465c; }}
QTabWidget::pane {{ border: 1px solid #D8DFE8; background: white; border-radius: 4px; }}
QTabBar::tab {{ padding: 7px 14px; background: #E9EEF4; border: 1px solid #D8DFE8; border-bottom: none; }}
QTabBar::tab:selected {{ background: white; font-weight: 600; }}
QGroupBox {{ font-weight: 600; border: 1px solid #D8DFE8; border-radius: 6px; margin-top: 10px;
    padding-top: 8px; background: white; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {NAVY}; }}
#card {{ background: white; border: 1px solid #D8DFE8; border-radius: 8px; }}
#card:hover {{ border-color: {NAVY}; }}
#cardValue {{ font-size: 22pt; font-weight: 700; }}
#cardLabel {{ color: #5b6b7f; }}
#hint {{ color: #5b6b7f; font-size: 9pt; }}
#dropZone {{ border: 2px dashed #9FB2C9; border-radius: 8px; background: #F8FAFC; }}
#dropZone[state="hover"] {{ border: 2px solid {ACCENT}; background: #FDF0E6; }}
#dropZone[state="busy"] {{ border: 2px solid {NAVY}; background: #EEF3F9; }}
#dropText {{ color: #4A5D75; font-size: 10pt; background: transparent; }}
QStatusBar {{ background: white; border-top: 1px solid #D8DFE8; }}
"""

STATUT_COLORS = {
    "A_VERIFIER": ("#8A5A00", "#FFF4D6"),
    "NON_IDENTIFIE": ("#9B1C1C", "#FDE2E2"),
    "A_DENONCER": ("#1E4E8C", "#DCEBFF"),
    "EXPORTE": ("#5B3E96", "#EDE5FB"),
    "DEPOSE": ("#1F6B3A", "#DDF3E4"),
    "A_PAYER": ("#B45309", "#FFEDD5"),
    "PAYE": ("#6B4F1F", "#F3E9D8"),
    "REFACTURE": ("#374151", "#E5E7EB"),
    "CLOS": ("#4B5563", "#ECEFF3"),
    "ANNULE": ("#6B7280", "#F1F2F4"),
}


def open_path(path) -> None:
    if path and os.path.exists(str(path)):
        os.startfile(str(path))


def error_box(parent, title: str, err) -> None:
    QMessageBox.critical(parent, title, str(err))


class Worker(QThread):
    """Exécute `fn(progress=callback)` hors du thread graphique."""
    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(self.progress.emit))
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(f"{e}")


def dropped_paths(event) -> list[str]:
    return [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]


class DropZone(QFrame):
    """Zone de dépôt des scans : glisser-déposer de fichiers ou de dossiers, ou clic pour parcourir."""
    files_dropped = Signal(list)
    clicked = Signal()

    TEXT = ("📥  Déposez ici vos avis scannés  —  PDF, JPG, PNG, TIFF, ou un dossier entier\n"
            "ou cliquez pour parcourir. Plusieurs avis par PDF : découpage automatique.")

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(56 if compact else 90)
        self.label = QLabel(self.TEXT)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setObjectName("dropText")
        lay = QVBoxLayout(self)
        lay.addWidget(self.label)
        self._busy = False
        self._set_state("idle")

    def _set_state(self, state: str):
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_busy(self, text: str | None):
        """Affiche la progression (texte) ou revient à l'état d'attente (None)."""
        self._busy = text is not None
        self.label.setText(f"⏳  {text}" if text else self.TEXT)
        self._set_state("busy" if text else "idle")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and not self._busy:
            e.acceptProposedAction()
            self._set_state("hover")

    def dragLeaveEvent(self, e):
        self._set_state("busy" if self._busy else "idle")

    def dropEvent(self, e):
        paths = dropped_paths(e)
        self._set_state("idle")
        if paths:
            e.acceptProposedAction()
            self.files_dropped.emit(paths)

    def mouseReleaseEvent(self, e):
        if not self._busy:
            self.clicked.emit()


class RowsModel(QAbstractTableModel):
    """Modèle de table simple : liste de dicts + colonnes [(clé, titre, formateur|None)]."""

    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows: list[dict] = []
        self.color_fn = None  # fn(row, key) -> (fg, bg) | None

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = [dict(r) for r in rows]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.columns[section][1]
        return None

    def data(self, index, role=Qt.DisplayRole):
        row = self.rows[index.row()]
        key, _, fmt = self.columns[index.column()]
        val = row.get(key)
        if role == Qt.DisplayRole:
            return fmt(val, row) if fmt else ("" if val is None else str(val))
        if role == Qt.UserRole:  # valeur de tri
            return val if val is not None else ""
        if role == Qt.ToolTipRole and key in ("anomalie", "lieu", "nature", "notes"):
            return val
        if role in (Qt.ForegroundRole, Qt.BackgroundRole) and self.color_fn:
            c = self.color_fn(row, key)
            if c:
                return QColor(c[0] if role == Qt.ForegroundRole else c[1])
        return None

    def row(self, i) -> dict:
        return self.rows[i]


def make_table(model, parent=None) -> tuple[QTableView, QSortFilterProxyModel]:
    proxy = QSortFilterProxyModel(parent)
    proxy.setSourceModel(model)
    proxy.setSortRole(Qt.UserRole)
    proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
    proxy.setFilterKeyColumn(-1)
    view = QTableView(parent)
    view.setModel(proxy)
    view.setSortingEnabled(True)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QTableView.SelectRows)
    view.setEditTriggers(QTableView.NoEditTriggers)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(26)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    view.horizontalHeader().setStretchLastSection(True)
    view.setWordWrap(False)
    return view, proxy


def selected_rows(view: QTableView, proxy, model) -> list[dict]:
    rows = sorted({proxy.mapToSource(i).row() for i in view.selectionModel().selectedRows()})
    return [model.row(r) for r in rows]


# --- formateurs
def f_date(v, _row=None):
    return parser.fmt_date(v)


def f_dt(v, _row=None):
    if not v:
        return ""
    d = parser.to_date(v)
    return f"{parser.fmt_date(d)} {str(v)[11:16]}".strip()


def f_plate(v, _row=None):
    return plates.display(v)


def f_money(v, _row=None):
    return f"{v:.2f} €".replace(".", ",") if isinstance(v, (int, float)) else ""


def f_statut(v, _row=None):
    return db.STATUTS.get(v, v or "")


def f_bool(v, _row=None):
    return "Oui" if v else "Non"


def to_display(kind: str, col: str, v) -> str:
    if v is None:
        return ""
    if kind == "date":
        return parser.fmt_date(v)
    if kind == "datetime":
        return f_dt(v)
    if col == "immatriculation":
        return plates.display(v)
    if kind == "number":
        return f"{v:g}".replace(".", ",")
    return str(v)


class RecordDialog(QDialog):
    """Formulaire généré à partir de referentiel.FIELDS[table]."""

    def __init__(self, table: str, record: dict | None, parent=None):
        super().__init__(parent)
        self.table, self.record = table, record or {}
        self.setWindowTitle(("Modifier" if record else "Nouveau") + {"clients": " client", "vehicules": " véhicule",
                                                                     "contrats": " contrat",
                                                                     "conducteurs": " chauffeur"}[table])
        self.setMinimumWidth(520)
        self.widgets = {}
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        for col, label, kind in referentiel.FIELDS[table]:
            val = self.record.get(col)
            if kind == "bool":
                w = QCheckBox()
                w.setChecked(bool(val) if record else col == "actif")
            elif kind == "traitement":
                w = QCheckBox("oui — on paie les avis de ce client et on les lui refacture (pas de désignation)")
                w.setChecked(val == "PAIEMENT")
            elif kind == "civilite":  # choix imposés par l'ANTAI pour une personne
                w = QComboBox()
                for lab, code in (("—", None), ("M.", "M"), ("MME", "MME")):
                    w.addItem(lab, code)
                code = referentiel.coerce(table, col, "civilite", val) if val else None
                w.setCurrentIndex(max(0, w.findData(code)))
            elif kind == "type_client":
                w = QComboBox()
                w.addItem("Personne morale (entreprise)", "PM")
                w.addItem("Particulier", "PP")
                w.setCurrentIndex(1 if val == "PP" else 0)
            elif kind in ("vehicule", "client", "conducteur"):
                w = QComboBox()
                w.setEditable(True)
                w.setInsertPolicy(QComboBox.NoInsert)
                if kind == "vehicule":
                    items = [(plates.display(r["immatriculation"]) + (f"  ({r['marque'] or ''} {r['modele'] or ''})"
                              if r["marque"] else ""), r["id"])
                             for r in db.q("SELECT * FROM vehicules ORDER BY immatriculation")]
                elif kind == "conducteur":
                    items = [(f"{r['nom'] or ''} {r['prenom'] or ''}  ({r['matricule'] or '—'})", r["id"])
                             for r in db.q("SELECT * FROM conducteurs WHERE actif=1 OR id=? ORDER BY nom, prenom", (val,))]
                else:
                    items = [(f"{r['code_client'] or ''} – {r['raison_sociale'] or ((r['nom'] or '') + ' ' + (r['prenom'] or ''))}",
                              r["id"]) for r in db.q("SELECT * FROM clients ORDER BY raison_sociale, nom")]
                w.addItem("", None)
                for text, rid in items:
                    w.addItem(text, rid)
                w.completer().setFilterMode(Qt.MatchContains)
                w.completer().setCompletionMode(QCompleter.PopupCompletion)
                idx = w.findData(val)
                w.setCurrentIndex(max(idx, 0))
            else:
                w = QLineEdit(to_display(kind, col, val))
                if kind == "date":
                    w.setPlaceholderText("jj/mm/aaaa")
                elif kind == "datetime":
                    w.setPlaceholderText("jj/mm/aaaa hh:mm")
            self.widgets[col] = (w, kind)
            form.addRow(label, w)
        inner = QWidget()
        inner.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Enregistrer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(scroll)
        lay.addWidget(buttons)
        self.resize(560, min(140 + 34 * len(self.widgets), 760))

    def values(self) -> dict:
        out = {}
        for col, (w, kind) in self.widgets.items():
            if isinstance(w, QCheckBox) and kind == "traitement":
                out[col] = "PAIEMENT" if w.isChecked() else None
            elif isinstance(w, QCheckBox):
                out[col] = 1 if w.isChecked() else 0
            elif isinstance(w, QComboBox):
                out[col] = w.currentData()
            else:
                txt = w.text().strip()
                v = referentiel.coerce(self.table, col, kind, txt)
                if txt and v is None and kind in ("date", "datetime", "number"):
                    raise ValueError(f"Valeur invalide pour « {dict((c, l) for c, l, _ in referentiel.FIELDS[self.table])[col]} » : {txt}")
                out[col] = v
        return out

    def save(self):
        try:
            vals = self.values()
            key = referentiel.KEYS[self.table]
            if self.table == "contrats":
                if not vals["vehicule_id"] or not vals["client_id"] or not vals["date_debut"]:
                    raise ValueError("Véhicule, client et date de début sont obligatoires.")
                if not vals["numero"]:
                    v = db.q1("SELECT immatriculation FROM vehicules WHERE id=?", (vals["vehicule_id"],))
                    vals["numero"] = f"{v['immatriculation']}-{vals['date_debut'][:10]}"
                if vals["date_fin"] and vals["date_fin"] < vals["date_debut"]:
                    raise ValueError("La date de fin est antérieure à la date de début.")
            elif not vals.get(key) and self.table == "vehicules":
                raise ValueError("L'immatriculation est obligatoire.")
            if self.table == "clients":
                if vals["type"] == "PM" and not vals["raison_sociale"]:
                    raise ValueError("La raison sociale est obligatoire pour une personne morale.")
                if vals["type"] == "PP" and not vals["nom"]:
                    raise ValueError("Le nom est obligatoire pour un particulier.")
                if not vals["code_client"]:
                    vals["code_client"] = None
            if self.table == "conducteurs":
                if not vals["nom"]:
                    raise ValueError("Le nom du chauffeur est obligatoire.")
                if not vals["matricule"]:  # matricule généré : CH001, CH002…
                    n = max([int(r["matricule"][2:]) for r in db.q("SELECT matricule FROM conducteurs "
                             "WHERE matricule LIKE 'CH%'") if r["matricule"][2:].isdigit()] or [0])
                    vals["matricule"] = f"CH{n + 1:03d}"
            if self.record.get("id"):
                db.update(self.table, self.record["id"], vals)
                self.saved_id = self.record["id"]
            else:
                self.saved_id = db.insert(self.table, vals)
            self.accept()
        except Exception as e:
            msg = str(e)
            if "UNIQUE" in msg:
                msg = "Cette valeur existe déjà (code client, immatriculation ou n° de contrat en double)."
            QMessageBox.warning(self, "Enregistrement impossible", msg)
