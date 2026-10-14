"""Relance de l'application dans un environnement propre (après une mise à jour).

L'exécutable « onefile » de PyInstaller décompresse ses fichiers dans un dossier temporaire (_MEIxxxx) et transmet
ce dossier à son processus Python par des variables d'environnement. Un programme relancé par l'application hérite
de ces variables : la nouvelle version croit alors devoir réutiliser le dossier de l'ancienne, que celle-ci vide en
se fermant, et plante (« cannot import name '_extra' »). D'où un environnement nettoyé, et l'option
PYINSTALLER_RESET_ENVIRONMENT qui force une instance indépendante.

Module volontairement minimal (bibliothèque standard uniquement) : il est utilisé avant tout autre import.
"""
import os
import subprocess
import sys

PROPRE = "--propre"   # marque une instance lancée dans un environnement propre


def env_propre() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("_PYI", "_MEI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def relancer(args: list[str]) -> None:
    """Démarre une nouvelle instance indépendante de l'exécutable courant."""
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen([sys.executable, *args, PROPRE], env=env_propre(), creationflags=flags, close_fds=True,
                     cwd=os.path.dirname(sys.executable))


def doit_se_relancer() -> bool:
    """Vrai si cette instance a été lancée par une version antérieure à 1.7.3 après une mise à jour : elle tourne
    alors sur le dossier temporaire de l'ancienne version et doit se relancer avant de charger ses bibliothèques."""
    return bool(getattr(sys, "frozen", False)) and "--apres-maj" in sys.argv and PROPRE not in sys.argv
