"""Emplacements des fichiers : configuration locale + dossier de données (paramétrable)."""
import json
import os
import sys
from pathlib import Path

APP_NAME = "AntaiPV"
APP_TITLE = "ANTAI PV — Gestion des dénonciations"
VERSION = "1.7.3"
GITHUB_REPO = "Frye136/antai-pv"   # dépôt public : code source, releases et mises à jour automatiques

_LOCAL_CFG_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
_LOCAL_CFG = _LOCAL_CFG_DIR / "config.json"


def resource_path(rel: str) -> Path:
    """Chemin d'une ressource embarquée (compatible PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


def _load_local() -> dict:
    try:
        return json.loads(_LOCAL_CFG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_local(cfg: dict) -> None:
    _LOCAL_CFG_DIR.mkdir(parents=True, exist_ok=True)
    _LOCAL_CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def data_dir() -> Path:
    d = _load_local().get("data_dir")
    path = Path(d) if d else Path.home() / "Documents" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_data_dir(path: str) -> None:
    cfg = _load_local()
    cfg["data_dir"] = path
    _save_local(cfg)


def db_path() -> Path:
    return data_dir() / "antai_pv.db"


def sub(name: str) -> Path:
    """Sous-dossier du dossier de données (archive, exports, inbox...)."""
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p
