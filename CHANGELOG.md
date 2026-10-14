# Journal des versions

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Chaque section `## [x.y.z]` sert de notes à la
release GitHub correspondante.

## [1.5.1] - 2026-10-14

- Mise à jour automatique fiabilisée : l'exécutable en cours est renommé puis remplacé immédiatement
  (plus de script externe qui pouvait être interrompu à la fermeture). Ancienne version supprimée au démarrage suivant.
- Mise à jour silencieuse en ligne de commande : `AntaiPV.exe --mettre-a-jour`.

## [1.5.0] - 2026-10-14

- Projet publié en open source (licence MIT).
- Mises à jour automatiques : recherche d'une nouvelle version au démarrage (désactivable), téléchargement,
  vérification SHA-256 et remplacement de l'exécutable. Onglet *Paramètres > Mises à jour*.
- Publication automatisée des versions par GitHub Actions.

## [1.4.0] - 2026-10-14

- Filière « payer et refacturer » (stationnement, FPS, majorées, autres, ou client qui le préfère) :
  À payer → Payé – à refacturer → Refacturé – attente règlement → Clos.
- Enregistrement du paiement, du n° de facture et du règlement ; export « à facturer » (débours + frais).
- Mail client dédié aux avis payés ; échéance FPS à 90 jours ; nouvelles cartes du tableau de bord.

## [1.3.0] - 2026-10-14

- Zone de dépôt (glisser-déposer de fichiers et de dossiers).
- Formulaire unique « Nouvelle location » (véhicule + client + contrat).
- Journal déplacé dans les Paramètres.

## [1.2.0] - 2026-10-14

- Scans de travers : redressement, orientation automatique, résolution remontée à 300 dpi, seconde lecture.
- Bouton « Relire le scan ».

## [1.1.0] - 2026-10-14

- CSV conforme au modèle officiel ANTAI à 18 colonnes et au guide utilisateur (SIRET, civilité SOCIETE,
  100 lignes par fichier, pays, caractères autorisés).
- Raison sociale du contrevenant lue sur chaque avis ; accusés d'enregistrement ANTAI rattachés aux avis.

## [1.0.0] - 2026-10-13

- Première version : OCR des avis, identification du locataire, CSV de désignation, e-mails, archivage.
