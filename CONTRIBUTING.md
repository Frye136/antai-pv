# Contribuer

Merci de votre intérêt ! Le projet vise les loueurs et gestionnaires de flotte français ; issues et discussions en
français de préférence.

## Données personnelles : règle absolue

**Ne joignez jamais de vrais avis de contravention, plaques, noms, adresses ou n° de permis** (issues, captures,
tests, jeux d'essai). Anonymisez ou utilisez des données fictives (`tools/demo_data.py`). Pour un problème de
lecture OCR, recopiez les lignes utiles en remplaçant les valeurs réelles.

## Proposer une modification

1. Créez une branche depuis `main`.
2. Environnement : `py -3.11 -m venv .venv` puis `.venv\Scripts\pip install -r requirements.txt`.
3. Ajoutez ou adaptez un test dans `tests/test_core.py` et vérifiez : `python tests\test_core.py`.
4. Ouvrez une pull request en décrivant le besoin métier (cas d'avis, règle ANTAI…).

Style : celui du code existant (Python 3.11, commentaires et libellés en français, interface PySide6).

## Publier une version (mainteneurs)

Voir la section « Publier une version » du [README](README.md).
