# ANTAI PV — dénonciation des contraventions pour les loueurs de véhicules

[![Tests](https://github.com/Frye136/antai-pv/actions/workflows/tests.yml/badge.svg)](https://github.com/Frye136/antai-pv/actions/workflows/tests.yml)
[![Dernière version](https://img.shields.io/github/v/release/Frye136/antai-pv)](https://github.com/Frye136/antai-pv/releases/latest)
[![Licence MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

Logiciel Windows libre et autonome (un seul `AntaiPV.exe`, aucune installation) pour les loueurs et gestionnaires de
flotte qui reçoivent des avis de contravention sur leurs véhicules : lecture des scans, identification du locataire,
**désignation en masse sur l'espace gestionnaire de flotte de l'ANTAI** (fichier CSV), ou **paiement puis
refacturation** au client, notification par e-mail, archivage et suivi.

> Projet indépendant, sans lien avec l'ANTAI ni avec l'administration. Vérifiez toujours les désignations avant dépôt.

## Télécharger

**[⬇ AntaiPV.exe — dernière version](https://github.com/Frye136/antai-pv/releases/latest/download/AntaiPV.exe)**
(Windows 10/11, pack de langue Français pour l'OCR — présent sur un Windows français).

L'exécutable n'est pas signé : au premier lancement, Windows SmartScreen peut afficher « Windows a protégé votre
ordinateur » → *Informations complémentaires* → *Exécuter quand même*. Le logiciel se **met ensuite à jour tout seul** :
au démarrage il signale une nouvelle version, la télécharge, vérifie son empreinte SHA-256 et redémarre.

## Fonctions

- **Scans** : glisser-déposer de PDF / images / dossiers, dossier de dépôt du copieur surveillé, numérisation WIA.
  Plusieurs avis par PDF (découpage recto/verso automatique).
- **Lecture (OCR Windows intégré)** : n° d'avis, dates, heure, plaque, titulaire, lieu, nature, montant.
  Scans de travers redressés, pages tournées remises droites, résolution remontée à 300 dpi, seconde lecture si besoin.
- **Identification** : contrat du véhicule couvrant la date **et l'heure** de l'infraction ; plaques mal lues
  (0/O, 1/I, 8/B…) rapprochées de la flotte ; ambiguïtés signalées.
- **Deux filières** :
  - *Désignation ANTAI* : À dénoncer → Exporté (CSV) → Déposé ANTAI ;
  - *Payer et refacturer* (stationnement, FPS, majorées, ou client qui le préfère) :
    À payer → Payé – à refacturer → Refacturé – attente règlement → Clos.
- **CSV ANTAI** conforme au modèle officiel (18 colonnes, 100 désignations par fichier, contrôles du guide ANTAI).
- **E-mails** aux clients (SMTP ou Outlook), un par client, avis en pièce jointe, modèle propre à chaque filière.
- **Référentiel** clients / véhicules / contrats : import Excel ou CSV, ou formulaire unique « Nouvelle location ».
- **Suivi** : tableau de bord et échéances, lots ANTAI, accusés d'enregistrement, export « à facturer », journal,
  sauvegarde quotidienne.

## Démarrage

1. **Paramètres > Général** : raison sociale telle qu'imprimée sur vos avis, SIRET, frais de dossier, dossier de dépôt.
2. **Paramètres > E-mail** : SMTP (Office 365, OVH…) ou Outlook, puis « Tester la connexion ».
3. **Clients / Véhicules / Contrats** : « Modèle d'import » → remplir ou exporter depuis votre logiciel de location →
   « Importer Excel / CSV » (réimportable : mise à jour par code client, immatriculation, n° de contrat).
4. Déposez vos scans. Vérifiez les avis « À vérifier », générez le CSV, déposez-le sur
   [entreprises.antai.gouv.fr](https://entreprises.antai.gouv.fr/), marquez le lot déposé, notifiez les clients.

## Format du CSV ANTAI

Conforme au modèle officiel et au guide « Gestionnaires de parc non conventionnés » :
`Réf. Avis;Immatriculation;Date avis;Raison sociale désignant;SIRET;Civilité;Nom ou Raison sociale;Prénom;
Date de naissance;Email;N° Permis de conduire;Permis délivré le;N° Voie;Nom Voie;Complément adresse;Code postal;Ville;Pays`
— séparateur `;`, ANSI, dates `jj/mm/aaaa`.

- « Raison sociale désignant » = le contrevenant **tel qu'imprimé sur l'avis** (lu sur chaque avis ; l'ANTAI le contrôle).
- Entreprise désignée : civilité `SOCIETE`, raison sociale dans « Nom ou Raison sociale ».
  Particulier : `M.` / `MME`, nom, prénom, date de naissance, permis.
- Pays selon l'annexe 3 du guide, caractères interdits (`&`, `#`, `+`…) remplacés, code postal sur 5 chiffres.
- **Paramètres > Format export ANTAI** : tout est modifiable ; un nouveau modèle ANTAI s'importe en un clic.

## Données et confidentialité

Tout reste **sur le poste** (ou le dossier choisi) : `Documents\AntaiPV\` — base SQLite `antai_pv.db`,
`archive\AAAA\MM\<n°avis>_<plaque>.pdf`, `exports\` (lots CSV), `sauvegardes\` (30 jours), `depot_traites\`.
La base est prévue pour un poste à la fois.

- Aucune télémétrie. Seules connexions : votre serveur e-mail, et l'API publique de GitHub pour la recherche de mise à
  jour (aucune donnée envoyée ; désactivable dans *Paramètres > Mises à jour*).
- Le mot de passe SMTP est chiffré par Windows (DPAPI, lié à la session).
- Le logiciel traite des données personnelles (locataires, conducteurs) : vous restez responsable de traitement (RGPD).

## Développement

Python 3.11, PySide6, PyMuPDF, Pillow, OCR Windows (`Windows.Media.Ocr`), openpyxl, pywin32.

```
py -3.11 -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py                        # lancer depuis les sources
python tests\test_core.py [avis.pdf]                # tests (+ test optionnel sur un vrai scan)
.\build.ps1                                         # tests + dist\AntaiPV.exe
python tools\demo_data.py [--importer]              # jeu de démonstration fictif (demo\*.xlsx)
dist\AntaiPV.exe --diagnostic avis.pdf              # test OCR -> %TEMP%\antaipv_diagnostic.txt
```

| Module | Rôle |
|---|---|
| `app/ocr.py` | rendu, redressement, orientation, OCR Windows |
| `app/parser.py` | extraction des champs d'un avis |
| `app/plates.py` | immatriculations : normalisation, détection, rapprochement tolérant à l'OCR |
| `app/services.py` | import, archivage, identification, filières, paiements, échéances |
| `app/antai_export.py` | CSV de désignation (format paramétrable) |
| `app/mailer.py` | notifications SMTP / Outlook |
| `app/referentiel.py` | import/export Excel du référentiel, exports de suivi |
| `app/updater.py` | mises à jour automatiques (releases GitHub) |
| `app/ui/` | interface PySide6 |

### Publier une version

1. Mettre à jour `VERSION` dans `app/config.py` et ajouter la section correspondante dans `CHANGELOG.md`.
2. `git commit`, puis `git tag v1.5.0` et `git push origin main v1.5.0`.
3. GitHub Actions teste, construit `AntaiPV.exe`, calcule son SHA-256 et publie la release : les postes installés
   proposent la mise à jour au démarrage suivant.

Contributions bienvenues : voir [CONTRIBUTING.md](CONTRIBUTING.md). **Ne publiez jamais de vrais avis ni de données
clients** (issues, tests, captures) — utilisez des données fictives.

## Licence

[MIT](LICENSE)
