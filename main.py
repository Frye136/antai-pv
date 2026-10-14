"""ANTAI PV — point d'entrée."""
import sys
import traceback

from app import relance

# Lancé par une ancienne version après une mise à jour : se relancer proprement AVANT de charger les bibliothèques
# (le dossier temporaire hérité est en train d'être vidé par l'ancienne version). Voir app/relance.py.
if relance.doit_se_relancer():
    relance.relancer([a for a in sys.argv[1:]])
    sys.exit(0)

from PySide6.QtCore import QLocale  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import config, db, instance, updater  # noqa: E402
from app.ui.common import STYLE  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def excepthook(exc_type, exc, tb):
    msg = "".join(traceback.format_exception(exc_type, exc, tb))
    log = config.data_dir() / "erreurs.log"
    with open(log, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    QMessageBox.critical(None, "Erreur inattendue", f"{exc}\n\nDétail enregistré dans :\n{log}")


def diagnostic(pdfs: list[str]) -> None:
    """AntaiPV.exe --diagnostic avis.pdf … : teste la lecture (OCR) sans toucher aux données,
    résultat dans %TEMP%\\antaipv_diagnostic.txt."""
    import os
    import tempfile
    from app import ocr, parser
    out = os.path.join(tempfile.gettempdir(), "antaipv_diagnostic.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"{config.APP_TITLE} v{config.VERSION}\n")
        for pdf in pdfs:
            try:
                doc = ocr.open_as_pdf(pdf)
                text = ocr.page_text(doc[0])
                f.write(f"\n== {pdf} ({doc.page_count} p.)\n{parser.parse(text)}\n")
            except Exception:
                f.write(f"\n== {pdf}\n{traceback.format_exc()}\n")
    QMessageBox.information(None, "Diagnostic", f"Résultat : {out}") if "--quiet" not in sys.argv else None


def main():
    if "--diagnostic" not in sys.argv:
        # instance unique ; après une mise à jour, attendre que l'ancienne version ait fini de se fermer
        if not instance.acquire(wait_ms=20000 if "--apres-maj" in sys.argv else 0):
            if "--mettre-a-jour" not in sys.argv:
                instance.activate_existing()
            sys.exit(2)
    updater.cleanup()  # ancien exécutable laissé par une mise à jour
    updater.sync_installed_version()
    if "--mettre-a-jour" in sys.argv:
        # mise à jour silencieuse (dépannage à distance, script) : installe la dernière release si elle est plus récente
        info = updater.check()
        if info:
            updater.install(updater.download(info), relaunch="--relancer" in sys.argv)
        return
    if "--diagnostic" in sys.argv:
        app = QApplication(sys.argv)
        diagnostic([a for a in sys.argv[1:] if not a.startswith("--")])
        return
    apres_maj = "--apres-maj" in sys.argv
    QLocale.setDefault(QLocale(QLocale.French, QLocale.France))
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    sys.excepthook = excepthook
    db.get()
    try:
        db.backup()
    except Exception:
        pass
    win = MainWindow()
    win.show()
    if apres_maj:
        db.log("Mise à jour installée", f"version {config.VERSION}")
        win.status(f"Mise à jour installée : version {config.VERSION}")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
