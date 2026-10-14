"""Mises à jour automatiques depuis les « Releases » GitHub du projet.

Une release publiée par l'intégration continue contient :
  - AntaiPV.exe          : l'exécutable
  - AntaiPV.exe.sha256   : son empreinte SHA-256 (vérifiée avant installation)

Seule requête réseau faite par le logiciel (hors envoi des e-mails) : lecture de la dernière release sur
api.github.com. Aucune donnée n'est transmise. Désactivable dans Paramètres > Mises à jour.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from . import config, instance, relance

# ANTAIPV_RELEASE_URL : release simulée pour les tests de bout en bout uniquement
API_LATEST = (os.environ.get("ANTAIPV_RELEASE_URL")
              or f"https://api.github.com/repos/{config.GITHUB_REPO}/releases/latest")
EXE_NAME = "AntaiPV.exe"
TIMEOUT = 15


def is_frozen() -> bool:
    """Vrai pour l'exécutable PyInstaller (le seul qui sait se remplacer)."""
    return bool(getattr(sys, "frozen", False))


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3]) or (0,)


def _get(url: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"{config.APP_NAME}/{config.VERSION}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def check() -> dict | None:
    """Dernière release si elle est plus récente que la version installée, sinon None."""
    data = json.loads(_get(API_LATEST))
    tag = data.get("tag_name") or ""
    if parse_version(tag) <= parse_version(config.VERSION):
        return None
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    if EXE_NAME not in assets:
        return None
    return {
        "version": tag.lstrip("v"),
        "notes": (data.get("body") or "").strip(),
        "page": data.get("html_url"),
        "exe_url": assets[EXE_NAME],
        "sha_url": assets.get(EXE_NAME + ".sha256"),
    }


def download(info: dict, progress=None) -> Path:
    """Télécharge le nouvel exécutable et vérifie son empreinte. Renvoie le chemin du fichier téléchargé."""
    if not info.get("sha_url"):
        raise RuntimeError("La release ne contient pas d'empreinte SHA-256 : installation refusée.")
    expected = _get(info["sha_url"], "application/octet-stream").decode().split()[0].lower()
    folder = _download_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"AntaiPV-{info['version']}.exe"
    req = urllib.request.Request(info["exe_url"], headers={"User-Agent": f"{config.APP_NAME}/{config.VERSION}"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(f"Téléchargement de la version {info['version']} : {done * 100 // total} %")
    if h.hexdigest().lower() != expected:
        dest.unlink(missing_ok=True)
        raise RuntimeError("Empreinte SHA-256 incorrecte : fichier corrompu ou altéré, installation annulée.")
    return dest


def install(new_exe: Path, relaunch: bool = True) -> None:
    """Remplace l'exécutable en cours d'exécution puis relance la nouvelle version.

    Windows interdit d'écraser un .exe ouvert mais autorise de le renommer : l'exe courant devient
    « AntaiPV.old.exe » (supprimé au démarrage suivant), la nouvelle version prend sa place immédiatement.
    Aucun script externe : rien ne peut être interrompu par la fermeture de l'application.
    L'appelant doit quitter l'application juste après."""
    if not is_frozen():
        raise RuntimeError("Mise à jour possible uniquement depuis AntaiPV.exe.")
    current = Path(sys.executable)
    # une autre copie ouverte ou en train de démarrer lirait le nouvel exe en cours de route et planterait
    others = instance.other_processes(str(current), {os.getpid(), os.getppid()})
    if others:
        raise RuntimeError("Une autre fenêtre d'ANTAI PV est ouverte ou en cours de démarrage. "
                           "Fermez-la, puis relancez la mise à jour (Paramètres > Mises à jour).")
    old = current.with_name(current.stem + ".old.exe")
    try:
        old.unlink(missing_ok=True)
        os.replace(current, old)
    except OSError as e:
        raise PermissionError(f"Impossible de remplacer {current} ({e}). Placez AntaiPV.exe dans un dossier "
                              "personnel (Bureau, Documents…) ou mettez à jour manuellement.") from e
    try:
        shutil.copy2(new_exe, current)
    except OSError:
        os.replace(old, current)  # retour à l'état initial
        raise
    try:
        new_exe.unlink(missing_ok=True)
    except OSError:  # encore ouvert par l'antivirus : supprimé au prochain démarrage (cleanup)
        pass
    if relaunch:
        if os.environ.get("ANTAIPV_TEST_RELANCE_ANCIENNE") == "1":
            # test uniquement : reproduit la relance des versions < 1.7.3 (environnement hérité)
            subprocess.Popen([str(current), "--apres-maj"], close_fds=True, cwd=str(current.parent),
                             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
        else:
            relance.relancer(["--apres-maj"])


INSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{7D3F6A2B-9C1E-4F5A-8B2D-3E6C1A9F4B70}_is1"


def sync_installed_version() -> None:
    """Version affichée dans « Applications installées » alignée sur la version réelle après une mise à jour
    automatique (installation par AntaiPV-Setup.exe uniquement)."""
    if not is_frozen():
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INSTALL_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            location = Path(winreg.QueryValueEx(k, "InstallLocation")[0])
            if location.resolve() == Path(sys.executable).parent.resolve() and \
                    winreg.QueryValueEx(k, "DisplayVersion")[0] != config.VERSION:
                winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, config.VERSION)
    except OSError:
        pass  # exécutable autonome (pas d'installation) : rien à faire


def _download_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / config.APP_NAME / "mises_a_jour"


def cleanup() -> None:
    """Au démarrage : supprime les téléchargements restants et l'ancien exécutable laissé par une mise à jour."""
    for f in _download_dir().glob("AntaiPV-*.exe") if _download_dir().is_dir() else []:
        try:
            f.unlink()
        except OSError:
            pass
    if is_frozen():
        old = Path(sys.executable).with_name(Path(sys.executable).stem + ".old.exe")
        for _ in range(10):  # l'ancienne instance peut mettre quelques secondes à se fermer
            try:
                old.unlink(missing_ok=True)
                return
            except OSError:
                time.sleep(0.5)
