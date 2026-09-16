---
name: charlemagne-import-mail-telephone
description: "Use when preparing the Charlemagne 'ImportMailTelephone' Excel file to bulk-update email/phone for students or staff (l'établissement), imported natively from within Charlemagne."
---

# Import Charlemagne — email / téléphone (élèves et adultes)

Cette skill prépare le fichier Excel à importer dans Charlemagne pour mettre à jour en masse l'email et le téléphone d'élèves et/ou d'adultes (enseignants, personnels). Le fichier généré n'est jamais importé automatiquement — il est livré à l'utilisateur pour import manuel dans Charlemagne, via le même écran qui fournit le modèle `ImportMailTelephone.xlsx`.

## Contrat du fichier (déduit du modèle officiel fourni par l'utilisateur — aucun article d'aide en ligne trouvé pour cette fonctionnalité, contrairement aux imports "informations complémentaires élèves" et "affectation des photos")

- Format **.xlsx** (pas de CSV ici), une seule feuille nommée `Import`.
- En-tête exact, 4 colonnes dans cet ordre : `Identifiant` | `Type (ELEVE ou ADULTE)` | `Mail` | `Téléphone`.
- **Identifiant** : l'identifiant logiciel Charlemagne — IDELEVE si la ligne est de type ELEVE, IDPERSONNEL si elle est de type ADULTE. Pas de variante par nom documentée pour cet import (contrairement à "informations complémentaires élèves") : toujours résoudre vers l'identifiant, jamais laisser un nom en colonne A.
- **Type (ELEVE ou ADULTE)** : valeur littérale exacte `ELEVE` ou `ADULTE` (respecter la casse telle qu'affichée dans l'en-tête). `ADULTE` correspond aux enseignants/personnels de l'établissement (table `COM_PERSONNELS`, même périmètre que l'affectation des photos), pas aux responsables/parents d'élèves (`COM_RESPONSABLES`) — c'est une déduction du contexte (menu Charlemagne "Adultes - Autres tiers"), pas confirmée par une doc explicite : le signaler à l'utilisateur et recommander un test sur 1-2 lignes avant un import en masse s'il a un doute.
- **Mail**, **Téléphone** : un seul champ de chaque, alors que la base a plusieurs colonnes possibles côté élève/adulte/responsable (ex. `PE_TELDOMICILE` vs `PE_TELPORTABLE`, `PE_EMAILPERSO` vs `PE_EMAIL_PRO`). On ignore lequel Charlemagne met à jour côté base — ne pas deviner : le signaler explicitement à l'utilisateur et, en cas de doute, recommander de tester l'import sur une ligne connue puis de vérifier dans Charlemagne quel champ a changé.
- Comportement à l'import (écrasement vs conservation de l'existant, gestion des cellules vides) non documenté non plus : le signaler à l'utilisateur plutôt que de supposer un comportement (voir le précédent cumulatif découvert sur l'import "informations complémentaires élèves" — ce genre de piege est courant sur les imports Charlemagne).

## Déroulé

1. Clarifier avec l'utilisateur : quelle donnée source (fichier, liste, réponses collectées...), s'agit-il d'élèves, d'adultes, ou d'un mélange, et quelles colonnes source correspondent à mail/téléphone.
2. Résoudre l'identifiant Charlemagne de chaque ligne de façon fiable plutôt que par déduction :
   - Type ELEVE : outil MCP `liste_eleves` (IDELEVE, nom, prénom, classe) si le serveur MCP Charlemagne est disponible, sinon la table `COM_ELEVES` de la base SQLite consolidée si elle est accessible directement.
   - Type ADULTE : outil MCP `liste_personnels` (IDPERSONNEL, nom, prénom, particule) ou la table `COM_PERSONNELS`.
   - Signaler les cas non trouvés ou ambigus (homonymes) à l'utilisateur plutôt que de choisir à sa place — une ligne mal résolue met à jour la mauvaise fiche.
3. Construire le fichier Excel en respectant exactement l'en-tête et l'ordre de colonnes du modèle officiel (feuille `Import`, colonnes `Identifiant` / `Type (ELEVE ou ADULTE)` / `Mail` / `Téléphone`).
4. Avant de livrer, résumer à l'utilisateur : nombre de lignes par type, identifiants non trouvés ou ambigus, et rappeler les deux zones d'incertitude ci-dessus (quel champ téléphone/mail est visé côté base, comportement écrasement/conservation) pour qu'il valide sur un petit échantillon avant un import complet.
5. Livrer le fichier comme n'importe quel livrable, jamais d'import automatique dans Charlemagne — c'est toujours l'utilisateur qui importe depuis l'écran Charlemagne qui fournit ce modèle.

## Vigilance données

Ce fichier contient des coordonnées (email, téléphone) d'élèves mineurs et d'adultes. Même discipline que le reste du projet Charlemagne : pas de données réelles dans des exemples ou du code versionné, fichier livré uniquement à l'utilisateur qui en a fait la demande.