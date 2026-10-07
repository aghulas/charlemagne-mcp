---
name: "charlemagne-import-mail-telephone"
description: "Use when preparing the Charlemagne 'ImportMailTelephone' Excel file to bulk-update email/phone for students or staff (École Sainte Marie), imported natively from within Charlemagne."
---

# Import Charlemagne — email / téléphone (élèves et adultes)

Cette skill prépare le fichier Excel à importer dans Charlemagne pour mettre à jour en masse l'email et le téléphone d'élèves et/ou d'adultes (enseignants, personnels). Le fichier généré n'est jamais importé automatiquement — il est livré à l'utilisateur pour import manuel dans Charlemagne, via le même écran qui fournit le modèle `ImportMailTelephone.xlsx`.

## Contrat du fichier (déduit du modèle officiel fourni par l'utilisateur — aucun article d'aide en ligne trouvé pour cette fonctionnalité, contrairement aux imports "informations complémentaires élèves" et "affectation des photos")

- Format **.xlsx** (pas de CSV ici), une seule feuille nommée `Import`.
- En-tête exact, 4 colonnes dans cet ordre : `Identifiant` | `Type (ELEVE ou ADULTE)` | `Mail` | `Téléphone`.
- **Identifiant** : l'identifiant logiciel Charlemagne — IDELEVE si la ligne est de type ELEVE, IDPERSONNEL si elle est de type ADULTE. Pas de variante par nom documentée pour cet import (contrairement à "informations complémentaires élèves") : toujours résoudre vers l'identifiant, jamais laisser un nom en colonne A.
- **Type (ELEVE ou ADULTE)** : valeur littérale exacte `ELEVE` ou `ADULTE` (respecter la casse telle qu'affichée dans l'en-tête). `ADULTE` correspond aux enseignants/personnels de l'établissement (table `COM_PERSONNELS`, même périmètre que l'affectation des photos), pas aux responsables/parents d'élèves (`COM_RESPONSABLES`) — c'est une déduction du contexte (menu Charlemagne "Adultes - Autres tiers"), pas confirmée par une doc explicite : le signaler à l'utilisateur et recommander un test sur 1-2 lignes avant un import en masse s'il a un doute.
- **Mail**, **Téléphone** : un seul champ de chaque dans le fichier ; c'est **l'écran d'import de Charlemagne** qui fait choisir le champ cible : mail **Personnel** ou **Professionnel**, téléphone **Domicile** ou **Portable** (constaté le 02/10/2026). Conséquence : **un fichier par champ cible** (ex. un fichier « mails personnels + portables », un autre « mails professionnels »), et indiquer à l'utilisateur, pour chaque fichier, quelles cases cocher à l'import.
- Comportement sur les cellules vides (effacement ou conservation) : non vérifié — ne pas mettre de cellule vide pour une personne dont on ne veut pas toucher le champ ; la retirer du fichier.

## Déroulé

1. Clarifier avec l'utilisateur : quelle donnée source (fichier, liste, réponses collectées...), s'agit-il d'élèves, d'adultes, ou d'un mélange, et quelles colonnes source correspondent à mail/téléphone.
2. Résoudre l'identifiant Charlemagne de chaque ligne de façon fiable plutôt que par déduction :
   - Type ELEVE : outil MCP `liste_eleves` (IDELEVE, nom, prénom, classe) si le serveur MCP Charlemagne est disponible, sinon la table `COM_ELEVES` de la base SQLite consolidée si elle est accessible directement.
   - Type ADULTE : outil MCP `liste_personnels` (IDPERSONNEL, nom, prénom, particule) ou la table `COM_PERSONNELS`.
   - Signaler les cas non trouvés ou ambigus (homonymes) à l'utilisateur plutôt que de choisir à sa place — une ligne mal résolue met à jour la mauvaise fiche.
3. Construire le fichier Excel en respectant exactement l'en-tête et l'ordre de colonnes du modèle officiel (feuille `Import`, colonnes `Identifiant` / `Type (ELEVE ou ADULTE)` / `Mail` / `Téléphone`).
4. Avant de livrer, résumer à l'utilisateur : nombre de lignes par type, identifiants non trouvés ou ambigus, et pour chaque fichier le champ cible à choisir à l'import (Personnel/Professionnel, Domicile/Portable). Livrer d'abord un **fichier test d'une seule ligne** (personne connue), à vérifier dans Charlemagne, puis les fichiers complets — méthode suivie le 02/10/2026 pour le personnel (test, personnel, mails professionnels, puis une correction isolée).
5. Après import, vérifier sur l'export suivant (`comparer_exports` du connecteur Charlemagne) que les champs attendus ont changé, et seulement eux.
6. Livrer les fichiers comme n'importe quel livrable, jamais d'import automatique dans Charlemagne — c'est toujours l'utilisateur qui importe depuis l'écran Charlemagne qui fournit ce modèle.

## Téléphones : format et parents

- **Format attendu** pour l'envoi de SMS depuis EcoleDirecte : `06 12 34 56 78` (5 groupes de 2 chiffres).
  Normaliser : retirer points/tirets, `+33` / `0033` → `0`. Ne **pas** reformater automatiquement les
  numéros étrangers, les mentions (« priorité », « bureau »), ni les cellules contenant plusieurs
  numéros : les lister pour traitement manuel.
- Cet import ne couvre que les **élèves** et les **adultes de l'établissement**. Pour les
  **responsables (parents)**, passer par l'outil `ed_admin_demande_telephones` du connecteur
  EcoleDirecte admin : demande de modification des coordonnées au nom de la famille (simulation,
  puis accord, puis envoi), validée ensuite par le secrétariat dans Charlemagne. En septembre 2026,
  465 numéros de parents ont été reformatés ainsi ; 4 cas ont dû être traités à la main.

## Personnel : au-delà du mail et du téléphone

Pour une mise à jour complète des fiches du personnel (adresses, dates, fonctions, création d'adultes, annuaire et tableau du personnel), suivre la skill `charlemagne-personnel-annuaire` ; cet import n'en couvre que la partie mail/téléphone.

## Vigilance données

Ce fichier contient des coordonnées (email, téléphone) d'élèves mineurs et d'adultes. Même discipline que le reste du projet Charlemagne : pas de données réelles dans des exemples ou du code versionné, fichier livré uniquement à l'utilisateur qui en a fait la demande.
