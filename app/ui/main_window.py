"""Fenêtre principale : navigation latérale + pages, surveillance du dossier de dépôt."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import config, db, services, updater
from .common import Worker, dropped_paths
from .pages import DashboardPage, LotsPage, ReferentielPage
from .pv_page import PvPage
from .settings_page import SettingsPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{config.APP_TITLE}  —  v{config.VERSION}")
        icon = config.resource_path("assets/icon.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1480, 900)

        self.watcher = None  # import automatique du dossier de dépôt
        self.stack = QStackedWidget()
        self.pv_page = PvPage(self)
        self.dashboard = DashboardPage(self)
        self.pages = [
            ("📊  Tableau de bord", self.dashboard),
            ("🚨  Contraventions", self.pv_page),
            ("📤  Lots ANTAI", LotsPage(self)),
            ("🏢  Clients", ReferentielPage(self, "clients")),
            ("🚐  Véhicules", ReferentielPage(self, "vehicules")),
            ("👷  Chauffeurs", ReferentielPage(self, "conducteurs")),
            ("📝  Contrats", ReferentielPage(self, "contrats")),
            ("⚙  Paramètres", SettingsPage(self)),
        ]

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 12)
        sl.setSpacing(2)
        brand = QLabel("ANTAI PV")
        brand.setObjectName("brand")
        sub = QLabel("Dénonciation des contraventions")
        sub.setObjectName("brandsub")
        sl.addWidget(brand)
        sl.addWidget(sub)
        self.nav = QButtonGroup(self)
        for i, (label, page) in enumerate(self.pages):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.nav.addButton(b, i)
            sl.addWidget(b)
            self.stack.addWidget(page)
        sl.addStretch()
        # espace insécable de largeur nulle après chaque « \ » : le chemin peut passer à la ligne proprement
        self.data_label = QLabel("Données :\n" + str(config.data_dir()).replace("\\", "\\​"))
        self.data_label.setStyleSheet("color:#7F94AF; font-size:8pt; padding:0 14px;")
        self.data_label.setWordWrap(True)
        sl.addWidget(self.data_label)
        self.nav.idClicked.connect(self.go)

        central = QWidget()
        cl = QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(side)
        cl.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Prêt")

        self.go(0)
        self.setAcceptDrops(True)  # dépôt de scans n'importe où dans la fenêtre
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.watch_depot)
        self.timer.start(60_000)
        QTimer.singleShot(1500, self.watch_depot)
        self.updater_worker = None
        if db.setting("maj_auto") == "1" and updater.is_frozen():
            QTimer.singleShot(4000, lambda: self.check_updates(manual=False))

    def go(self, i: int):
        self.nav.button(i).setChecked(True)
        self.stack.setCurrentIndex(i)
        self.pages[i][1].refresh()

    def show_pv(self, filter_label: str):
        self.go(1)
        self.pv_page.set_filter(filter_label)

    # ------------------------------------------------------------------ mises à jour
    def check_updates(self, manual: bool = True):
        """Recherche une nouvelle version publiée sur GitHub (silencieux au démarrage si rien de neuf / hors ligne)."""
        if self.updater_worker and self.updater_worker.isRunning():
            return
        self.updater_worker = Worker(lambda progress: updater.check(), self)

        def done(info):
            if info:
                self.offer_update(info)
            elif manual:
                QMessageBox.information(self, "Mises à jour", f"Vous avez la dernière version ({config.VERSION}).")

        def failed(err):
            if manual:
                QMessageBox.warning(self, "Mises à jour", f"Impossible de joindre GitHub : {err}")

        self.updater_worker.done.connect(done)
        self.updater_worker.failed.connect(failed)
        self.updater_worker.start()

    def offer_update(self, info: dict):
        notes = info["notes"][:1500] or "(pas de notes de version)"
        box = QMessageBox(self)
        box.setWindowTitle("Mise à jour disponible")
        box.setText(f"<b>Version {info['version']} disponible</b> (installée : {config.VERSION})")
        box.setInformativeText("Installer maintenant ? Le logiciel redémarrera ; vos données ne sont pas modifiées.")
        box.setDetailedText(notes)
        install = box.addButton("Installer et redémarrer", QMessageBox.AcceptRole)
        box.addButton("Plus tard", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not install:
            return
        if not updater.is_frozen():
            QMessageBox.information(self, "Mise à jour", "Version de développement : téléchargez l'exécutable depuis\n"
                                    + (info.get("page") or ""))
            return
        self.updater_worker = Worker(lambda progress: updater.download(info, progress), self)
        self.updater_worker.progress.connect(self.status)

        def downloaded(path):
            try:
                db.log("Mise à jour", f"{config.VERSION} -> {info['version']}")
                updater.install(path)
            except Exception as e:
                QMessageBox.warning(self, "Mise à jour", str(e))
                return
            QApplication.quit()

        self.updater_worker.done.connect(downloaded)
        self.updater_worker.failed.connect(lambda e: QMessageBox.warning(self, "Mise à jour", f"Échec : {e}"))
        self.updater_worker.start()

    def status(self, msg: str):
        self.statusBar().showMessage(msg)

    def refresh_all(self):
        for _, page in self.pages:
            if page is self.stack.currentWidget() or page in (self.dashboard, self.pv_page):
                page.refresh()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = dropped_paths(e)
        if paths:
            e.acceptProposedAction()
            self.pv_page.import_paths(paths)

    def watch_depot(self):
        """Import automatique des scans déposés dans le dossier surveillé."""
        folder = db.setting("dossier_depot")
        if db.setting("surveiller_depot") != "1" or not folder or not Path(folder).is_dir():
            return
        if self.pv_page.busy():
            return
        if not any(f.suffix.lower() in services.SUPPORTED for f in Path(folder).iterdir() if f.is_file()):
            return
        self.watcher = Worker(services.scan_depot, self)
        self.watcher.progress.connect(self.status)
        self.watcher.progress.connect(lambda m: self.pv_page._zones_busy(f"Dossier de dépôt — {m}"))

        def done(results):
            self.pv_page._zones_busy(None)
            n = len([r for r in results if r["pv_id"]])
            self.status(f"Dossier de dépôt : {n} nouvel(s) avis importé(s).")
            self.refresh_all()
            if n and not self.isActiveWindow():
                QApplication.alert(self)

        self.watcher.done.connect(done)
        self.watcher.failed.connect(lambda e: (self.pv_page._zones_busy(None),
                                               self.status(f"Dossier de dépôt : erreur – {e}")))
        self.watcher.start()

