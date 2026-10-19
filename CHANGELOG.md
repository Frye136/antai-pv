# Journal des versions

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Chaque section `## [x.y.z]` sert de notes à la
release GitHub correspondante.

## [1.9.0] - 2026-10-19

- Avis à **conducteur interpellé** (« le véhicule … conduit par M. X a fait l'objet d'un contrôle », p. ex. surcharge
  constatée au pesage) : nouveau type « Conducteur interpellé », non désignable, classé automatiquement en
  « payer et refacturer ». Le nom du conducteur, la tranche (« 2e tranche / 3 ») et le montant minoré sont notés
  sur l'avis.
- Le verso / formulaire de requête portant le même n° est rattaché à l'avis (au lieu d'être rejeté comme doublon).
- Lecture plus robuste : n° d'avis séparé de son libellé par du bruit d'OCR, nature lue avant « Prévue par … »
  (évite les faux mots-clés), lieu sur deux lignes (« RUE … » puis « COMMUNE - 80 »).

## [1.8.0] - 2026-10-16

- Véhicules de la société : désignation directe d'un chauffeur salarié, sans société cliente.
  - Nouvelle page « Chauffeurs » (import Excel par matricule, contrôle de complétude ANTAI).
  - Véhicule : case « véhicule de la société » et chauffeur habituel.
  - Avis : choix du « Chauffeur désigné » dans la fiche. Le chauffeur habituel est seulement proposé
    (« À vérifier ») et doit être confirmé ; un chauffeur choisi à la main passe « À dénoncer ».
  - Utilisable aussi pour un véhicule de location en usage interne (non loué ce jour-là).
  - FPS / stationnement sur un véhicule de la société : à payer, sans refacturation.

## [1.7.3] - 2026-10-14

- Correctif du plantage après une mise à jour automatique (« cannot import name '_extra' ») : la nouvelle version,
  relancée par l'ancienne, réutilisait le dossier temporaire de celle-ci, vidé à sa fermeture. Elle démarre
  désormais dans un environnement propre, y compris lorsqu'elle est lancée par une version antérieure.
- `AntaiPV.exe --mettre-a-jour --relancer` : mise à jour silencieuse puis redémarrage de l'application.

## [1.7.2] - 2026-10-14

- Correctif : corriger la plaque ou le n° d'un avis dans sa fiche provoquait une erreur « fichier utilisé par un
  autre processus » et créait des copies du PDF. L'aperçu ne verrouille plus le fichier ; le renommage se fait sans
  copie et, s'il est impossible (PDF ouvert ailleurs), il est simplement reporté et signalé au journal.
- Lecture de la plaque plus robuste : libellé mal lu par l'OCR (« lmmatriculation », sans deux-points), caractère
  parasite collé (« 7AB-123-CD ») ; les plaques imprimées avec tirets sont prioritaires.

## [1.7.1] - 2026-10-14

- Correctif : ouvrir ANTAI PV une deuxième fois pendant une mise à jour pouvait provoquer un plantage
  (« cannot import name '_extra' »). Le logiciel n'accepte plus qu'une seule fenêtre : un nouveau lancement
  ramène la fenêtre existante au premier plan.
- La mise à jour refuse de remplacer l'exécutable si une autre copie est ouverte ou en cours de démarrage.
- Chaque version publiée est désormais lancée par l'intégration continue avant d'être mise en ligne.

## [1.7.0] - 2026-10-14

- Suppression d'un ou plusieurs avis avec confirmation : touche Suppr, clic droit ou bouton « Supprimer » de la
  fiche. Avertissement si l'avis est déjà exporté, déposé, payé ou refacturé ; option pour supprimer aussi le PDF.
- Suppression des lots ANTAI avec confirmation (Suppr, clic droit, bouton) : les avis d'un lot non déposé
  repassent « À dénoncer », ceux d'un lot déposé restent « Déposé ANTAI » ; option pour supprimer le CSV.
  Remplace « Annuler le lot ».
- Toutes les suppressions sont inscrites au journal.

## [1.6.0] - 2026-10-14

- Installateur Windows `AntaiPV-Setup.exe` : installation dans le profil de l'utilisateur (sans droits
  administrateur), menu Démarrer, raccourci Bureau en option, désinstallation depuis « Applications installées ».
  Les mises à jour automatiques continuent de fonctionner ; la version affichée par Windows suit les mises à jour.
- L'exécutable autonome `AntaiPV.exe` reste disponible.

## [1.5.2] - 2026-10-14

- Les fichiers téléchargés par les mises à jour sont supprimés au démarrage (évite 80 Mo restants par mise à jour
  quand l'antivirus garde le fichier ouvert).

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
