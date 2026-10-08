---
name: "charlemagne-formats-import-aplim"
description: "Préparer un fichier d'import pour Charlemagne (Aplim) au format officiel des notes du support — enseignants et personnels, écritures comptables, fournisseurs, immobilisations, subventions, badges, entreprises, import standard élèves/responsables — et retrouver ou mettre à jour ces notes sur aplim.fr. Utiliser quand l'utilisateur veut importer des données dans Charlemagne par fichier, demande le format attendu par un écran d'import, ou cite une note Aplim « Formats d'imports »."
---

# Formats d'import Charlemagne (notes Aplim)

Aplim publie une note par format d'import sur https://www.aplim.fr/ressources/support
(« Documents & téléchargements › Charlemagne › Formats d'imports »). Cette skill dit comment les retrouver
et comment produire un fichier conforme. Le détail colonne par colonne est dans la doc projet
`claude/formats-import-charlemagne.md` (projet Claude « Connecteurs MCP — École ») ; la lire avant de
générer, et relire la note Aplim d'origine pour tout format non encore testé.

Formats qui ont leur propre skill : informations complémentaires élèves
(`charlemagne-import-infos-complementaires`), e-mail / téléphone (`charlemagne-import-mail-telephone`),
frais et avoirs de facturation (`charlemagne-import-frais-facturation`), emplois du temps
(`charlemagne-import-emploi-du-temps`), photos (`charlemagne-affectation-photos`).

## Retrouver les notes

- La page support est une application Next.js : l'arborescence des documents est dans un chunk
  `/_next/static/chunks/*.js` (objets `{id,label,type,downloadUrl}`), les fichiers sur
  `https://strapi.aplim.fr/uploads/<Nom>_<hash>.pdf`, en accès libre.
- Télécharger depuis le Mac (`curl -A "Mozilla/5.0"`) : le proxy du cloud bloque `aplim.fr`. Extraire le
  texte avec `pdftotext -layout`. Copies locales : `~/Charlemagne/aplim_formats/` (PDF et `txt/`).
- Chaque note porte une date de mise à jour en pied de page : la noter dans la doc projet, et
  revérifier le catalogue (nouveaux fichiers, hash changé) avant de s'appuyer sur une note ancienne.

## Règles communes

- Fichier **texte tabulé** `.txt` (exceptions : info comp élèves en `.csv` point-virgule ; import standard
  et mail-téléphone en classeur Excel). Construire sous Python ou Excel, enregistrer en « Texte (séparateur
  tabulation) ».
- Encodage **CP-1252**, fins de ligne CRLF ; remplacer les caractères absents de CP-1252.
- Ordre des colonnes imposé, champs vides laissés **vides** ; dates `AAAAMMJJ` ; nombres sans séparateur
  de milliers ni devise, **virgule** décimale ; codes et noms en MAJUSCULES quand la note le dit.
- **En-tête** : obligatoire pour enseignants/personnels, écritures, fournisseurs, immobilisations,
  subventions, import standard, paie ; interdit pour frais, badges, anciens élèves, entreprises.
- Informations complémentaires typées (enseignants, import standard, immobilisations) : en-tête
  `Type-Libellé` avec `N` nombre, `D` date `AAAAMMJJ`, `H` heure `HHmm`, `T` texte ≤ 60 ; sans en-tête,
  libellé générique.
- Identifiants : toujours les identifiants Charlemagne résolus par les outils du connecteur
  (`liste_eleves`, `liste_personnels`, `fiche_famille`, `responsables_eleves`), jamais devinés par le nom.
- Longueurs maximales (colonne « Lg » des notes) : tronquer en le signalant.

## Déroulé

1. Identifier l'écran d'import visé et la note correspondante (tableau de la doc projet) ; si la note
   n'existe pas (ex. informations complémentaires des responsables), le dire : pas d'import, liste de
   saisie manuelle.
2. Rassembler les données source et résoudre les identifiants ; lister les lignes ambiguës ou
   incomplètes plutôt que de deviner.
3. Générer le fichier (script Python jetable, hors dépôt, ou `openpyxl` pour les classeurs) en suivant
   la table des colonnes de la doc projet ; vérifier le nombre de colonnes sur chaque ligne et
   l'encodage (`file`, `iconv -f cp1252`).
4. Montrer un récapitulatif (lignes, colonnes, anomalies) et livrer le fichier à l'utilisateur ; **essai sur
   une ligne** avant un lot pour tout format jamais testé, puis contrôle sur l'export suivant
   (`comparer_exports`).
5. Reporter dans la doc projet ce qui a été appris (format accepté, rejet, comportement à l'import).

## Formats et vigilances par écran

| Écran Charlemagne | Fichier | Points clés |
|---|---|---|
| Administratif › import des enseignants et personnels | `.txt` tabulé, en-tête, 27 colonnes A→AA (+ infos comp) | NOM obligatoire ; `0` = oui pour « Recevoir des SMS » ; dates `AAAAMMJJ` ; création d'adultes en masse — pour une mise à jour, préférer `charlemagne-personnel-annuaire` / mail-téléphone |
| Compta › Outils › Import d'écritures › Fichier txt | `.txt` tabulé, en-tête, 10 colonnes (16 avec analytique en colonne, ou lignes `An` intercalées) | montant **positif** + sens `D`/`C` ; écritures d'une pièce consécutives ; journal/compte/pièce en MAJUSCULES ; colonnes I–J réservées aux fournisseurs (`C`/`V`, échéance) ; l'utilisateur importe et contrôle la balance, jamais un script |
| Compta › fournisseurs | `.txt` tabulé, en-tête, 32 colonnes A→AF | compte et raison sociale obligatoires ; P–S (codes banque) vides ; IBAN/BIC jamais renseignés par l'assistant |
| Compta › immobilisations | `.txt` tabulé, en-tête, 18 colonnes (+4 avec taxe d'apprentissage : valeur et 3 comptes) + infos comp | **écrase les immobilisations existantes** (assistance Aplim si le dossier en a déjà) ; durées en mois ; variante « avec taxe » à cocher à l'import |
| Compta › subventions | `.txt` tabulé, en-tête, 15 colonnes | **écrase les subventions existantes** ; table de correspondance des financements à l'import |
| Administratif › badges | `.txt` tabulé, sans en-tête, 4 colonnes (élèves) / 5 (adultes, colonne A = `adulte`) | sans objet sans badges |
| Entreprise › import | `entreprises.txt` (29 col.) + `intervenants.txt` (15 col.), tabulés, sans en-tête, noms imposés | intervenants jamais seuls |
| Administratif › import standard | classeur Excel, 4 fichiers (élèves, responsables, autres responsables, cursus) | migration initiale seulement ; variante 2018 décale les colonnes élèves |
| Administratif › IBAN responsables ; Paie V3 (salariés, IBAN, variables) | — | **hors périmètre de l'assistant** : IBAN, NIR, salaires ; documentés pour mémoire |

## Ce qu'on ne fait pas

- Aucun import lancé par un script ou un outil : l'utilisateur importe depuis Charlemagne.
- Aucun IBAN, BIC, NIR ni donnée de paie dans un fichier préparé par l'assistant.
- Pas de données réelles (élèves, familles, personnels) dans un dépôt ou un exemple versionné.
