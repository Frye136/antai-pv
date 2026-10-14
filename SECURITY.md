# Sécurité

## Signaler une vulnérabilité

Merci de ne pas ouvrir d'issue publique : utilisez le signalement privé de GitHub
(onglet *Security* → *Report a vulnerability*).

## Points de conception

- Les données (base, avis archivés) restent sur le poste ou dans le dossier choisi par l'utilisateur.
- Le mot de passe SMTP est chiffré avec DPAPI (session Windows de l'utilisateur).
- Mises à jour : uniquement depuis les releases de ce dépôt, en HTTPS ; l'exécutable téléchargé est refusé si son
  empreinte SHA-256 ne correspond pas à celle publiée avec la release.
- Aucune télémétrie.
