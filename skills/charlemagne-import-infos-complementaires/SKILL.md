---
name: charlemagne-import-infos-complementaires
description: "Use when preparing a CSV file to import/update Charlemagne 'informations complémentaires élèves' via Administratif > Outils > Récupération d'informations complémentaires élèves."
---

# Import Charlemagne — informations complémentaires élèves

Cette skill prépare un fichier CSV prêt à être importé dans Charlemagne pour mettre à jour des "informations complémentaires" sur des élèves (catégories personnalisées de type TEXTE : ex. régime alimentaire, transport, activité, etc.). Le fichier généré n'est jamais importé automatiquement — il est livré à l'utilisateur pour import manuel dans Charlemagne (Administratif / Outils / Récupération d'informations complémentaires élèves).

## Contrat du fichier (documenté par Aplim, aide.aplim.mayday.cx)

- Format .CSV, **séparateur point-virgule**.
- **Ligne d'en-tête obligatoire**, ordre des colonnes strict.
- Deux variantes pour la première colonne (choisir celle qui correspond à ce que l'utilisateur a déjà préparé côté Charlemagne) :
  - **Par identifiant** : première colonne = IDELEVE Charlemagne. Variante préférée : pas d'ambiguïté de matching.
  - **Par nom** : première colonne intitulée exactement `NOM PRENOM` (le nom seul ne suffit pas), contenu = nom et prénom **orthographiés exactement comme dans Charlemagne**. Un onglet "Élèves" dans l'écran d'import Charlemagne permet à l'utilisateur de vérifier/ajuster la correspondance après coup.
- Colonnes suivantes = une colonne par catégorie d'info complémentaire à importer. **Les champs non renseignés doivent rester vides** (jamais la chaîne "NULL" ou "None").
- Prérequis côté Charlemagne (à rappeler à l'utilisateur, pas à faire soi-même) : les catégories cibles doivent déjà exister, créées en type TEXTE, dans *Tables / Informations complémentaires élèves / Catégories* — et l'utilisateur doit ensuite faire correspondre chaque catégorie à la colonne du fichier lors de l'import.
- **Piège du comportement cumulatif** : un nouvel import conserve par défaut les valeurs précédemment importées pour les élèves absents du nouveau fichier — ça peut faire apparaître plus d'élèves que prévu après import. Si l'utilisateur veut un remplacement complet (pas un ajout/complément), le prévenir explicitement qu'il doit d'abord importer un CSV vide (mêmes colonnes, aucune ligne) pour réinitialiser, puis importer le fichier réel ensuite. Ne pas faire ce choix à la place de l'utilisateur — demander s'il veut un import cumulatif ou un remplacement complet avant de livrer le fichier final.

## Déroulé

1. Clarifier avec l'utilisateur : quelle donnée source (fichier fourni, texte collé, réponses à un formulaire...), quelles catégories cibles (les noms de colonnes doivent correspondre à des catégories déjà créées dans Charlemagne — demander leur intitulé exact si l'utilisateur ne l'a pas donné), cumulatif ou remplacement complet.
2. Résoudre l'identifiant Charlemagne de chaque élève de façon fiable plutôt que par déduction :
   - Si le serveur MCP Charlemagne est disponible dans la session, utiliser son outil `liste_eleves` (filtrable par classe, exclut par défaut les élèves sortis) pour obtenir IDELEVE/nom/prénom/classe et faire le matching.
   - Sinon, si la base SQLite consolidée (`data/administration_consolidee.db`) est accessible directement, interroger `COM_ELEVES` (IDELEVE, EL_NOM1, EL_PRENOM1) de la même façon.
   - Si ni l'un ni l'autre n'est disponible, ou en cas de doute (homonymes, orthographe qui ne colle pas), utiliser la variante "NOM PRENOM" et signaler explicitement à l'utilisateur les cas ambigus ou non trouvés plutôt que de deviner — un élève mal apparié écrase la mauvaise fiche.
   - Rappel : cette recherche ne couvre jamais les anciens élèves (table ADM_ANCIEN, identifiants dans un espace séparé) — un ancien élève ne peut pas être ciblé par cet import.
3. Construire le CSV : en-tête exact, séparateur `;`, encodage compatible Excel (UTF-8 avec BOM, ou celui que l'utilisateur précise), champs vides laissés vides.
4. Avant de livrer, résumer à l'utilisateur : nombre de lignes, colonnes/catégories couvertes, élèves non trouvés ou ambigus (s'il y en a), et rappeler le comportement cumulatif si un remplacement complet a été demandé (fournir aussi le CSV vide de réinitialisation dans ce cas).
5. Livrer le fichier comme n'importe quel livrable (SendUserFile), jamais d'import automatique dans Charlemagne — c'est toujours l'utilisateur qui importe depuis l'interface Charlemagne.

## Vigilance données

Ce fichier contient des données d'élèves mineurs. Le traiter avec la même discipline que le reste du projet Charlemagne : pas de données réelles dans des exemples ou du code versionné, fichier livré uniquement à l'utilisateur qui en a fait la demande.