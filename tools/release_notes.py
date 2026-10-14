"""Extrait du CHANGELOG.md la section d'une version (notes de la release GitHub).

    python tools/release_notes.py v1.5.0 notes.md
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def notes(version: str) -> str:
    version = version.lstrip("v")
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## \[?{re.escape(version)}\]?.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        raise SystemExit(f"Version {version} absente de CHANGELOG.md")
    return m.group(1).strip() + "\n"


if __name__ == "__main__":
    body = notes(sys.argv[1])
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(body, encoding="utf-8")
    else:
        sys.stdout.write(body)
