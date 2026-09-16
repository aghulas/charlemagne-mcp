# Dictionnaire de données — tables utiles aux cas d'usage Phase 2

Portée : uniquement les tables nécessaires aux 3 premiers cas d'usage
("solde d'un élève", "statut d'une facture", "liste des impayés du mois").
Ne couvre pas les 618 tables de l'export — à étendre au fur et à mesure des
cas d'usage suivants.

**Source (actuelle) :** base SQLite consolidée par `loader/load_charlemagne.py`
à partir de l'export CSV natif Charlemagne (module "Administration", 618
fichiers, dont 75 non vides à ce jour). Toutes les tables et colonnes
ci-dessous sont **vérifiées sur données réelles** (contenu, pas juste
structure) — voir aussi la section HFSQL/ODBC en fin de fichier, une
exploration antérieure et abandonnée mais gardée en référence.

---

## Modèle relationnel confirmé (élève ↔ famille ↔ facturation)

```
COM_ELEVES (IDELEVE)
     |
     |  COM_LIENER (IDRESPONSABLE, IDELEVE)  <- table de liaison, plusieurs
     |                                          responsables possibles par eleve
     v
COM_RESPONSABLES (IDRESPONSABLE)  --IDFOYER-->  COM_FOYER (IDFOYER)
     |
     |  RE_CODE_COMPTABLE (ex. "4111BONELLE")
     |  = meme format que TAB_PLAN_COMPTABLE.COMPTE cote HFSQL/Compta
     |  (confirme que les deux bases decrivent la meme realite comptable,
     |  meme si l'acces direct HFSQL est abandonne - cf plus bas)
     v
FAC_VALIDATION (IDVALIDATION)  <- un "evenement" de facturation (une ventilation)
     |
     +--> FAC_COMPTA_FAMILLE (IDVALIDATION, IDRESPONSABLE)  <- impact comptable par famille
     +--> FAC_HISTO_FAMILLE  (IDVALIDATION, IDRESPONSABLE)  <- detail/etat par famille
     +--> FAC_HISTO_ELEVE    (IDVALIDATION, IDELEVE)        <- detail par eleve (cle pas
     |                                                          totalement fiable, voir plus bas)
     +--> FAC_HISTO_LIGNE    (IDHISTOLIGNE)                 <- lignes de detail (articles factures)
```

### COM_ELEVES — élève (510 lignes)

Table large (124 colonnes). Colonnes utiles pour nos cas d'usage :

| Colonne | Sens |
|---|---|
| `IDELEVE` | Identifiant élève (clé) |
| `EL_NOM1`, `EL_PRENOM1` | Nom / prénom |
| `EL_IDCLASSE` | Classe |
| `EL_DATE_ENTREE`, `EL_DATE_SORTIE` | Scolarité |
| `EL_STATUT` | Statut de l'élève |

Pas de lien direct vers un responsable/compte ici — passer par `COM_LIENER`.

### COM_LIENER — liaison élève ↔ responsable(s) (1012 lignes)

| Colonne | Sens |
|---|---|
| `IDRESPONSABLE`, `IDELEVE` | Clé composite (0 doublon confirmé) |
| `LER_VERSQUI` | Indique qui reçoit la facturation (paramètre à creuser pour choisir le bon responsable si plusieurs) |
| `LER_TYPE_RESP`, `LER_LIEN` | Type de lien (père, mère, tuteur...) |
| `LER_HEBERGE_ELEVE` | Hébergement de l'élève |
| `LER_POURCENTAGE` | Répartition en cas de responsabilité partagée |

Un élève peut avoir plusieurs responsables — **ne pas supposer un seul
responsable par élève** dans les tools.

### COM_RESPONSABLES — responsable / famille payeuse (641 lignes)

| Colonne | Sens |
|---|---|
| `IDRESPONSABLE` | Clé |
| `RE_NOM1`, `RE_PRENOM1` | Identité |
| `RE_CODE_COMPTABLE` | Code compte comptable (ex. `4111BONELLE`) — pont vers l'ancien monde HFSQL/Compta |
| `IDFOYER` | Foyer de rattachement |
| `RE_IBAN`, `RE_BIC`, `RE_MODE_REGLEMENT` | Coordonnées bancaires / mode de règlement |
| `RE_ECHEANCE_JOUR`, `RE_ECHEANCE_MAX`, `RE_ECHEANCE_SPECIF` | Paramètres d'échéancier propres à la famille |

### FAC_VALIDATION — événement de facturation (33 lignes)

| Colonne | Sens |
|---|---|
| `IDVALIDATION` | Clé |
| `VA_TYPE_FACTURE` | "Manuelles" / "Toutes" observé |
| `VA_NB_FACTURES` | Nombre de factures générées lors de cet événement |
| `VA_DATE_HEURE` | Horodatage |
| `VA_ETAT` | **Attention : contient en réalité un libellé descriptif de l'événement ("Ventilation 26/09/2025 à 14h43"), pas un statut au sens attendu** — ne pas s'y fier comme statut de facture, à creuser |

### FAC_COMPTA_FAMILLE — impact comptable par famille et par événement (798 lignes)

| Colonne | Sens |
|---|---|
| `IDVALIDATION`, `IDRESPONSABLE` | Clé composite (0 doublon confirmé) |
| `CF_DEBIT`, `CF_CREDIT` | Mouvement de cet événement pour cette famille |
| `CF_SOLDE_PRIS` | Indicateur lié à la prise en compte du solde |
| `CF_NUMERO_FACTURE` | N° de facture |
| `CF_ECHE_PRIX1..12`, `CF_ECHE_DATE1..12` | Échéancier (jusqu'à 12 échéances) |
| `CF_MODE_REGLEMENT` | Mode de règlement retenu |

**Table candidate principale pour "solde d'un élève"** (en résolvant élève →
responsable via `COM_LIENER`, puis en sommant `CF_DEBIT - CF_CREDIT` sur les
événements de `IDRESPONSABLE`).

### FAC_HISTO_FAMILLE — détail/état par famille et par événement (798 lignes, 89 colonnes)

Reprend une grande partie des colonnes de `FAC_COMPTA_FAMILLE` (échéancier,
montants) plus :

| Colonne | Sens |
|---|---|
| `HF_APAYER_FAMILLE`, `HF_APAYER_FACTURE` | Montants à payer |
| `HF_ETAT` | **Une seule valeur observée sur tout l'export : "Imprimée"** — ne permet pas à ce stade de distinguer payée / impayée / en attente. À recouper avec les échéances (`HF_ECHE_DATE*`) et les paiements reçus (non trouvés dans cet export, voir "Écart" plus bas) |
| `HF_NOM`, `HF_PRENOM` | Nom du responsable au moment de la facturation |

### FAC_HISTO_ELEVE — détail par élève et par événement (1113 lignes)

| Colonne | Sens |
|---|---|
| `IDVALIDATION`, `IDELEVE` | Clé composite **non garantie unique** : 12 lignes sur 1113 partagent la même clé avec des montants différents (dont des paires signe opposé, ex. `643.66` / `-643.66` — probablement une ligne d'origine + une correction/annulation). Une 3e composante de clé existe probablement mais n'a pas été identifiée dans les colonnes disponibles. **Table exclue du chargement automatique tant que ce point n'est pas résolu** (voir `loader/load_charlemagne.py`, `COMPOSITE_KEYS`) |
| `HE_APAYER_ELEVE` | Montant à payer pour cet élève |

### FAC_HISTO_LIGNE — lignes de détail (5590 lignes)

| Colonne | Sens |
|---|---|
| `IDHISTOLIGNE` | Clé (colonne unique, fiable) |
| `IDVALIDATION`, `IDELEVE`, `IDRESPONSABLE` | Rattachement |
| `HL_LIBELLE_LIGNE` | Libellé de la ligne facturée (ex. cantine, activité...) |
| `HL_TOTAL`, `HL_APAYER_LIGNE_TTC` | Montants |

Utile pour le détail ligne par ligne d'une facture (ex. répondre à "de quoi
est composée cette facture").

---

## Écarts / points ouverts

1. **"Statut d'une facture" pas encore résolu proprement.** `HF_ETAT` n'a
   qu'une seule valeur ("Imprimée") sur tout l'export actuel — pas assez
   pour distinguer payée/impayée/en retard. `VA_ETAT` sur `FAC_VALIDATION`
   est un libellé, pas un statut. Il faudra soit trouver le bon signal
   ailleurs, soit le déduire (échéance passée + pas de règlement
   correspondant), une fois qu'on aura trouvé où sont tracés les règlements
   reçus (point 2).

2. **"Liste des impayés du mois" bloque sur l'absence de table de règlements
   peuplée.** Les tables candidates trouvées par nom (`ADM_ENCAISSEMENT`,
   `ADM_ENCAISSEMENT_LIGNE`, `ADM_TYPE_ENCAISSEMENT`) sont **vides** dans cet
   export (module caisse probablement non utilisé, ou règlements trackés
   ailleurs). Sans cette donnée, impossible de distinguer une échéance
   simplement "à venir" d'une échéance réellement impayée. À investiguer :
   soit un autre export/module Charlemagne à activer, soit un signal indirect
   via `FAC_COMPTA_FAMILLE` (solde qui ne redescend pas après la date
   d'échéance).

3. **`FAC_HISTO_ELEVE`** : 12 lignes à clé ambiguë, non chargées (voir
   ci-dessus). Impact limité (9 élèves sur 510) mais à trancher avant de
   construire un tool qui dépendrait de cette table pour un élève précis.

4. **Tables à clé non fiable (`loader/load_charlemagne.py`, `COMPOSITE_KEYS`)** —
   suite à une vérification croisée sur un export réel (2025-2026), 7 des 18
   tables listées dans le log du 2026-09-16 ont une clé de remplacement fiable,
   désormais déclarée dans `COMPOSITE_KEYS` : `COM_PERSONNELS` (`IDPERSONNEL`,
   pas `ID_UTILISATEUR` qui a des doublons), `REC_ENVOI_ONDE`
   (`IDRECENVOIONDE`), `VS_EDITION_ZONES` (`IDZONE`), `FAC_GRILLE_COMPTE`
   (`GC_CODE, IDCLASSE`), `FAC_GRILLE_PRIX` (`GP_CODE, IDCLASSE`),
   `ADM_PROFIL` (`ID_UTILISATEUR, PR_TYPE`), `REC_ENTREE_ELEVE`
   (`IDELEVE, EE_DATE`). Le loader ne rejette plus non plus une table sur la
   seule présence de valeurs nulles dans les colonnes clé quand la clé est
   par ailleurs sans collision (`COM_PREFERENCES` : clé `(PREF_TYPE1,
   PREF_TYPE2)` fiable, 2 lignes avec `PREF_TYPE2` null) — `pandas.duplicated()`
   traite toujours `NaN == NaN`, donc une vraie collision reste détectée et la
   table reste ignorée dans ce cas.

   Restent ignorées, clé non trouvée : `COM_PERSONNELS_ED` (candidat
   `(IDPERSONNEL, PED_TYPE)` insuffisant — 337 doublons sur 362 lignes,
   une 3e composante de clé n'a pas été identifiée), `FAC_COMPTA_GENERAL`
   (probablement pas de clé naturelle — table d'agrégation par compte
   général, vraisemblablement dupliquée quand une famille a plusieurs
   enfants), et 7 tables jamais encore testées : `ADM_ANC_CURSUS`,
   `ADM_LISTES_RUBRIQUES`, `ADM_STAT_RUBRIQUES`, `COM_BADGE`,
   `COM_FORM_MULTIPLE`, `COM_LOGS`, `VS_EDITION_PARAM`. — voir la sortie du
   loader pour la liste à jour à chaque exécution.

---

## Historique — exploration HFSQL/ODBC (abandonnée)

*Piste explorée avant le pivot vers le pipeline CSV → SQLite ci-dessus.
Conservée car `RE_CODE_COMPTABLE` (voir plus haut) confirme que les deux
bases décrivent la même réalité comptable — utile si l'accès direct
redevient un jour possible.*

Source : catalogue ODBC (`cursor.tables()` / `cursor.columns()`) via le DSN
`Charlemagne Compta`, driver HFSQL. Colonnes confirmées structurellement à
l'époque, mais **aucune lecture de données réelle n'a été possible** :

```
[01000] Invalid password for the <TABLE> data file.
```

Mot de passe **au niveau fichier HFSQL**, distinct de l'ODBC. **Aplim a été
sollicité et a explicitement refusé de le communiquer** — blocage devenu
définitif, à l'origine du pivot vers le pipeline CSV → SQLite (voir
`Plan_MCP_Charlemagne.md` et `CLAUDE.md`).

Tables identifiées à l'époque (structure seulement, non ré-vérifiées
depuis) : `TAB_PLAN_COMPTABLE` (COMPTE, LIBELLE, NOM, IBAN...),
`ECRITURE` (COMPTE, DEBIT, CREDIT, LETTRAGE...), `TAB_JOURNAL`,
`TAB_TYPE_PIECE`, `ECH_FAMILLE`, `REG_ENCAISSE` / `REG_ENCAISSE_LIG`
(avec `TYPE_ENCAISSEMENT = 'IMPAYE'` pour un prélèvement rejeté — le signal
d'impayé qu'on n'a pas encore retrouvé côté export CSV), `ED_REGLEMENT`,
`HIS_SOLDE`. Détail conservé dans l'historique git de ce fichier si besoin.
