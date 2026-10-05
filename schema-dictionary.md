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
| `IDELEVE`, `IDRESPONSABLE`, `IDVALIDATION` | Clé déclarée par l'éditeur (`HE_CLEF_ELEVE_RESP_VALID`, analyse HFSQL `Eleves.wdd` lue le 05/10/2026). Les 12 « doublons » observés avec (`IDVALIDATION`, `IDELEVE`) étaient des élèves facturés à **deux responsables** pour une même validation (paires de signe opposé = transfert d'un responsable à l'autre). Chargée en upsert avec cette clé depuis le 05/10/2026 (0 doublon sur 411 lignes). |
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

   `COM_PERSONNELS_ED` (droits EcoleDirecte des adultes) : clé trouvée le
   30/09/2026, `ID_PERSO_ED` (362 valeurs distinctes sur 362 lignes) —
   le candidat `(IDPERSONNEL, PED_TYPE)` était insuffisant (337 doublons).
   Colonnes utiles : `PED_TYPE` (`ETAB` = établissement coché, `MODULE` =
   fonctionnalité), `PED_CLEF` (id d'établissement ou code de
   fonctionnalité : `MESSAGE`, `ADMIN`, `AGENDA`, `POSTIT`, `ABS`, `RET`,
   `CDT`, `NOTES`, `MOY`, `CONSEIL`, `APPEL`, `AFF_EL`, `BL_PARENTS`,
   `CARNET_CORRESP`, `SANCTION`, `ENCOURAGE`, `EDT`, `PAIEMENT`),
   `PED_AUTORIS` (`1`/`0`). Voir `tools/personnels.py`.

   Restent ignorées, clé non trouvée : `FAC_COMPTA_GENERAL`
   (probablement pas de clé naturelle — table d'agrégation par compte
   général, vraisemblablement dupliquée quand une famille a plusieurs
   enfants), et 7 tables jamais encore testées : `ADM_ANC_CURSUS`,
   `ADM_LISTES_RUBRIQUES`, `ADM_STAT_RUBRIQUES`, `COM_BADGE`,
   `COM_FORM_MULTIPLE`, `COM_LOGS`, `VS_EDITION_PARAM`. — voir la sortie du
   loader pour la liste à jour à chaque exécution.

---

## Inventaire des tables peuplées non couvertes par les cas d'usage (exploration des 02-03/10/2026)

Point de départ : 119 tables peuplées dans l'export 2026-2027, 51 citées dans la documentation ou le code, **68 jamais
regardées**. Toutes ont été classées ; douze ont été explorées (contenu, clés, jointures). Chiffres sur l'export du 02/10/2026.

### Tables métier explorées — candidates pour de nouveaux tools ou l'enrichissement des existants

#### ADM_HISTO_CLASSE_MEF — parcours de classe par année (3 252 lignes)

| Colonne | Sens |
|---|---|
| `IDELEVE`, `IDCLASSE` | Élève et classe de l'année ; `IDCLASSE` joint `COM_CLASSES` à 100 % (vérifié sur 2025-2026) |
| `ANNEE_SCOLAIRE` | `2018-2019` → `2025-2026` : une ligne par élève et par année **passée** (≈405/an) ; l'année en cours n'y est pas, elle est dans `COM_ELEVES` |
| `DATE_ENTREE`, `DATE_SORTIE` | `AAAAMMJJ`, toujours renseignées (rentrée → fin d'année) ; une sortie en cours d'année y apparaît par sa date |
| `CODE_MEF_INTERNE` | Niveau : libellé court (`CP`, `CM1`…) ou code MEF numérique selon les années — normaliser avant usage |

Usage : ancienneté dans l'école, parcours d'un élève, détection des arrivées/départs en cours d'année (prorata). 407 élèves actuels ont un historique.

#### ADM_CURSUS — cursus par année (1 518 lignes)

`IDELEVE`, `CUR_ANNEE_SCOLAIRE`, `CUR_CLASSE`, `CUR_NIVEAU` (`C1 Cycle 1` / `C2 Cycle 2` / `C3 Cycle 3`), `CUR_DIPLOME` (toujours vide en primaire).
Format d'année **incohérent** (`2017-2018` puis `2018/2019`…) et effectif croissant par année (3 → 407) : c'est le cursus connu des élèves **actuels**, pas un historique complet — préférer `ADM_HISTO_CLASSE_MEF` pour le passé.

#### COM_PROFS_PRINCIPAUX — enseignant principal par classe (17 lignes)

`IDPERSONNEL` → `COM_PERSONNELS`, `IDCLASSE` → `COM_CLASSES`, `NUM_LIGNE` (rang). Jointures à 100 %. Une classe peut avoir deux lignes (co-enseignement, ex. CE1A). À brancher dans `liste_personnels` / `liste_eleves` (« enseignant de la classe »).

#### VS_CONGE — calendrier des jours sans classe (226 lignes) et VS_TAB_PERIODES (5 lignes)

`VS_CONGE` : `CO_JOUR` (`AAAAMMJJ`) du 01/08/2026 au 31/07/2027, `IDCLASSE = 0` = toute l'école (week-ends, vacances, fériés). `VS_TAB_PERIODES` : trimestres `T1`–`T3` et semestres `S1`–`S2` avec dates. Usage : nombre de jours de classe par mois (prorata cantine/garderie), bornes de périodes.

#### COM_OPTIONS_EL — options par élève (277 lignes) et COM_OPTIONS_MOINS1 (275, année précédente)

Une seule option utilisée : `OE_TYPE = 1`, `OE_CODE_MATIERE = 0302` = **ANGLAIS** (`TAB_MATIERE`, jointure sur `MA_CODE_GESTION`/`MA_CODE_INTERNE`). 277 élèves inscrits. Probablement l'atelier d'anglais (cf. `PA_SUIVI_INSCRIPTION`).

#### COM_JOURNAL_MODIF — fiches à envoyer vers EcoleDirecte (6 lignes)

`TYPE` (`Eleve_ATraiter` / `Resp_ATraiter`), `TYPE_FICHIER`, `ID_CHARLEMAGNE`, `DATE_HEURE_MODIF`, `DATE_HEURE_ENVOI`, `UTILISATEUR`, `STATUT` (`En attente`), `DETAIL` (vide).
**File de sortie Charlemagne → EcoleDirecte** (établi le 03/10/2026) : chaque fiche modifiée dans Charlemagne y est inscrite « à traiter » par la synchro, puis supprimée une fois envoyée (identifiants 679 → 1197 : ~1 200 entrées passées, 6 restantes). `UTILISATEUR` = l'utilisateur Charlemagne qui a modifié. Preuves : la table n'est pas dans la liste des 66 tables répliquées vers EcoleDirecte (`Replica_EtablissementAD.rpm`) ; les deux lignes `Resp_ATraiter` du 23/09 21h49-21h50 suivent de 4 minutes des demandes de téléphone envoyées par le connecteur et validées dans Charlemagne (plus aucune demande en attente côté EcoleDirecte, numéros à jour) ; les six lignes restantes concernent des élèves sortis (04/07, 01/09) ou leurs responsables, hors périmètre de la synchro, donc jamais envoyées. Ce n'est **pas** la file des demandes entrantes des familles (console EcoleDirecte). Tool `modifications_ecoledirecte_en_attente` avec `motif_probable`.

#### Module Passage (cantine / garderie) — PA_SUIVI_INSCRIPTION (6), PA_SUIVI_JOURNALIER (6), PA_PORTE_MONNAIE (2), PA_PDP (1)

Activités paramétrées : `MATIN` (Garderie Matin), `MIDI` (Restauration du midi), `SOIR` (Restauration du Soir), `ETUDE` (Etude / Garderie Soir), `ATELIERANGLAIS`, `ATELIERANGLAISSOIR`. `PA_SUIVI_JOURNALIER` ne contient que des essais du 23/09 ; porte-monnaie `GARDERIE`/`ETUDE` à 0 : **module non encore en production** — à revoir quand l'appel cantine/garderie sera pris dans EcoleDirecte (chantier « appel »).

#### Emploi du temps — VS_HORAIRE (3), VS_HORAIRE_CLASSE (~105), VS_EDT_TYPE_ENTETE, VS_EDT_TYPE_COURS (~546), VS_EDT_COURS (~23 500), VS_EDT_ALTERNANCES (53)

`VS_HORAIRE` : horaires de l'établissement (`HO_DEBUT`/`HO_FIN` `HHMM`, `HO_TYPE` cours/repas). `VS_HORAIRE_CLASSE` : « Affinage classe » (cours, récréation, repas par `IDCLASSE`), prioritaire pour l'affichage. `VS_EDT_TYPE_ENTETE` : semaines types (`LIBELLE` « Import EDT », `DESCRIPTION` « Import EDT du JJ/MM/AAAA ») — un nouvel `IDENTETE` à chaque import. `VS_EDT_TYPE_COURS` : `JOUR` (1 = lundi), `HEURE_DEBUT`/`HEURE_FIN`, `CODE_MATIERE` → `TAB_MATIERE.MA_CODE_GESTION`, `SEMAINE` (vide/A/B) ; enseignants et salles dans `VS_EDT_TYPE_PROF` / `VS_EDT_TYPE_SALLE` (colonnes `IDPERSONNEL`/`IDSALLE` de la table de cours restent à 0). `VS_EDT_COURS` : cours générés date par date (`ANNULE`, `MODIFIE`), liens `VS_EDT_PROF` / `VS_EDT_SALLE`. `VS_EDT_ALTERNANCES` : semaine A/B par lundi (`SE_DEBUT`), alternance continue y compris pendant les vacances. Les générations et suppressions de semaine type sont tracées dans `COM_LOGS` (module Vie Scolaire). Tool `emploi_du_temps_classe`.

#### Appels — VS_APPEL_PROF (~300), VS_ABSENCE, VS_ABSENCE_JOUR

`VS_APPEL_PROF` : un appel par enseignant/classe/demi-journée (`AP_COURS_DATE`, `AP_COURS_HEURE_DEBUT` 0800/1300, `AP_EFFECTIF`, `AP_NB_ABSENCE`, `AP_TOUSPRESENTS`, `AP_DATE` = horodatage de saisie, `AP_DATE_INTEGRATION`). Clé côté Charlemagne : enseignant + classe + `AP_DATE` à la seconde (deux appels saisis la même seconde fusionnent). `VS_ABSENCE` : absences (`AB_ORIGINE = AppelEd`, demi-journées consécutives fusionnées, `AB_NB_DEMIJ`) ; `VS_ABSENCE_JOUR` : détail par jour (`AJ_DEMIJ_AM`, `AJ_DEMIJ_PM`). Journal d'intégration : `COM_LOGS` titres « Appel enseignant » et « Appels ED ». Tool `appels_enseignants`.

#### INS_DOC_A_SIGNER — documents des inscriptions en ligne (3 lignes)

`Convention de Scolarisation`, `Reglement Financier`, `Reglement Interieur`, créés le 28/09/2026 (`HASH` du document). Paramétrage des documents à signer par les familles.

### Paramétrage de la facturation — à relier à la skill `charlemagne-facturation`

| Table | Contenu | Remarque |
|---|---|---|
| `FAC_PERIODE` (1) | une seule période `TARIF`, `PE_MOIS_DEBUT = 9`, libellés des 12 mois de facturation | |
| `FAC_GRILLE_PERIODE` (49) | par ligne de facturation (`GPE_CODE_LIGNE`), `GPE_CODE_FREQUENCE` (`FAMILLE`) et 12 drapeaux `GPE_MOIS1..12` = **mois où la ligne est facturée** | clé des prorata ; joint `FAC_GRILLE_PRIX.GP_CODE` |
| `FAC_REM_AUTO` (3) | remises automatiques Aplim par défaut (`Contribution`, `Demi Pensionnaire`, `Internat`, à partir de 2 enfants, en %) | seule `Contribution` est pertinente (fratrie) ; `RA_STATIM = 1` = standard éditeur |
| `FAC_FORMULE_MOT` (46) | **variables utilisées par les formules de l'école** : `FAMCOTAPEL`, `JUSTIFAPEL`, `FOYERSEPARE`, `FAMNBENFANTS`, `FAMNBENFANTSEXT`, `FAMQUOTIENT2`, `JUSTIFRTEXT`… avec leur origine (`Fiche Famille` / `Infos Comps Famille`) | à citer dans la skill facturation |
| `FAC_FORMULE_MOTFICHE` (65) | catalogue des variables disponibles (dont bourses collège/lycée, sans objet ici) | |
| `FAC_FORMULE_MOTCLE` / `FAC_FORMULE_SEP` | langage des formules : `SI ALORS SINON FIN ET OU RENVOYER PRIX QUANTITE APAYER GRILLE` et opérateurs | |
| `FAC_SOCIETE` (1), `COM_ETABLISSEMENT` (1) | identité de l'OGEC et de l'école (adresse, RNE, direction), libellés des 3 quotients (`SOC_QUOT_LIBEL1..3`), mois de facturation | |
| `FAC_HISTO_IBAN` (131) | historique des IBAN par responsable | **donnée bancaire : ne jamais exposer dans un tool** |

### Tables de libellés — à utiliser dans les jointures plutôt que des codes bruts

| Table | Clé | Joint depuis | Taux |
|---|---|---|---|
| `TAB_CSP` (41) | `CSP_CODE` | `COM_RESPONSABLES.RE_CSP1` | 602/614 (12 vides) ; `RE_CSP2` jamais renseigné |
| `TAB_SIT_FAM` (6) | `IDTAB_SIT_FAM` | `COM_RESPONSABLES.RE_ID_SITFAM` | 560/614 |
| `TAB_LIENS` (30) | `LIE_CODE` | `COM_LIENER.LER_LIEN` (et `LER_LIEN2`) | 947/947 |
| `TAB_CIVILITE` (4) | `CI_CODE` | `RE_CIVILITE1/2` | |
| `TAB_PAYS` (241) | `PA_CODE` | `RE_PAYS` | |
| `COM_NIVEAU` (3) | `IDNIVEAU` | cycles C1/C2/C3 | |
| `TAB_MATIERE` (70) | `MA_CODE_GESTION` / `MA_CODE_INTERNE` | `COM_OPTIONS_EL.OE_CODE_MATIERE` | |

### Référentiels nationaux — volumineux, sans valeur métier propre

`TAB_ETAB_ORI` (87 959 établissements d'origine), `TAB_VILLE` (53 514), `TAB_COMMUNE` (38 841), `TAB_DEPARTEMENT` (113), `REC_BE1D` (444 correspondances ONDE), `REC_TABLES` (12), `REC_FORMATION` (9), `NO_TABLE_NOTE_COMP` (10), `VS_PACTE_BRIQUES` / `VS_PACTE_MOTIFS_ABSENCE` / `VS_PACTE_TYPES_REMPLACANT` / `VS_PACTE_TYPES_REMPLACEMENT` (pacte enseignant). Ne pas explorer ; ces trois premières font 180 000 lignes à elles seules.

### Configuration d'écrans, d'éditions et préférences — sans intérêt pour le connecteur

`ADM_PARAMETRES_LISTES`, `ADM_LISTE_ENTETE`, `ADM_STAT_ENTETE`, `ADM_PROFS_COMPOSITION`, `ADM_PROFS_EDITION`, `ADM_BADGE_CHAMPS`, `ADM_BADGE_ENTETE`, `ADM_ETIQUETTES`, `ADM_TROMBIS`, `TAB_BADGE_CONFIG`, `VS_EDITION`, `VS_EDT_COULEURS`, `VS_SALLES`, `VS_LOCALISATION`, `TAB_SITE`, `VS_PARAMETRE`, `VS_PARAMETRES_ETAB`, `VS_PROFIL`, `VS_APPEL_PROF` (3 appels d'essai), `DASH_CONFIGURATION`, `PA_PREFERENCES`, `PA_UTILISATEUR`, `PA_PDP_PARAM`, `PA_FACTU_PMONNAIE`, `FAC_STAT_CHAMP`, `COM_MESSAGES_PREDEFINIS`.

### Évolution des exports du 03 au 04/10/2026

- **Vie Scolaire en production** : emploi du temps importé (`VS_EDT_TYPE_COURS` 546 cours types, `VS_EDT_COURS` 23 532 cours
  datés et leurs tables `_PROF`/`_SALLE`, `VS_EDT_ALTERNANCES`, `VS_HORAIRE(_CLASSE)`, `VS_PARAMETRES_CLASSE`, `VS_IMPORT_PARAM`,
  12 matières du primaire ajoutées à `TAB_MATIERE`) ; appel de septembre intégré (`VS_APPEL_PROF` 299 appels du 01 au 29/09,
  `VS_ABSENCE` 86 absences, `VS_ABSENCE_JOUR` 126 ; `AP_NB_ABSENCE` total = 224 = « Absence=224 » du journal d'import). Toutes
  les absences sont non justifiées (`AB_JUSTIF = 0`). Créneaux : `0800-1200` et `1300-1700`.
- **Suppression de quatre classes vides** (`GSA` 17, `PSA` 19, `GS` 22 ; `GSB` 18 renommée `GS`) : aucune incidence sur les
  élèves ni sur les factures, mais Charlemagne a supprimé en cascade leurs grilles (`FAC_GRILLE_PRIX` −129, `FAC_GRILLE_COMPTE`
  −125), leurs filières (`COM_FORM_MULTIPLE`), un enseignant principal, des préférences d'affichage (`VS_PROFIL`) — et
  **remis à `IDCLASSE = 0` 180 lignes d'`ADM_HISTO_CLASSE_MEF`** (parcours 2021-2022 → 2025-2026) : le niveau
  (`CODE_MEF_INTERNE`) reste, le lien vers la classe de l'époque est perdu. Ne pas supprimer d'autres classes d'années
  passées si l'historique compte.
- Module Passage : `PA_PDP`, `PA_PDP_PARAM` (paramètres d'impression de tickets), `PA_UTILISATEUR` vidées — sans effet tant
  que le module n'est pas utilisé.
- `COM_PREFERENCES.CONSO_TOKEN_OPENAI` (mis à jour chaque jour, valeur vide, compteur 0) et `COM_METRIC_OAI` (vide) :
  Charlemagne embarque des fonctions s'appuyant sur OpenAI ; non utilisées à ce jour.
- Nouvelle table exportée `VS_EDT_TYPE_COURS_COMMENTAIRE` (vide) : 620 tables chargées.

### Suites proposées — état au 03/10/2026

1. **Fait** : tool `modifications_ecoledirecte_en_attente` sur `COM_JOURNAL_MODIF` (`tools/modifications.py`), interprétation
   établie le 03/10 (file de sortie vers EcoleDirecte, voir ci-dessus) et `motif_probable` pour les lignes bloquées.
2. **Fait** : `liste_eleves` expose `enseignants`, `premiere_annee`, `nb_annees_precedentes` ; `liste_personnels` expose
   `classes` ; `responsables_eleves` / `fiche_famille` renvoient les libellés CSP, situation familiale et lien lus dans
   `TAB_CSP`, `TAB_SIT_FAM`, `TAB_LIENS` (`tools/referentiels.py`, repli sur un dictionnaire si la table manque).
3. **Fait** : tool `jours_de_classe` (`tools/calendrier.py`, `VS_CONGE` + `VS_TAB_PERIODES`) ; section « Tables de
   paramétrage à connaître » dans la skill `charlemagne-facturation`.
4. **Ouvert** : reprendre le module Passage (`PA_*`) quand l'appel cantine/garderie sera en production.
5. **Ouvert** : aucun encaissement n'est exporté ; le signal d'impayé (`TYPE_ENCAISSEMENT = 'IMPAYE'` vu côté ODBC) n'a pas
   d'équivalent dans l'export CSV.

### Structure déclarée par l'éditeur — analyse WinDev `Eleves.wdd` (05/10/2026)

Méthode : l'analyse WinDev livrée avec Charlemagne (`Eleves.wdd`, sans mot de passe) a été importée dans une base HFSQL
**vide** via le Centre de Contrôle HFSQL, puis la structure a été lue par ODBC (scripts et résultat dans le dépôt privé
`charlemagne-tools/scripts/hfsql/`, rapport `rapport_structure_eleves.md`). Aucune donnée réelle n'a transité : seules
les tables, colonnes, clés et libellés de l'éditeur. Les .wdd ne contiennent pas le mot de passe des fichiers de
production, l'accès direct reste impossible (voir « Historique » ci-dessous).

Ce que cela a apporté :

- **Clés primaires corrigées dans le loader** (`COMPOSITE_KEYS`, 05/10/2026) : `FAC_HISTO_ELEVE` = (`IDELEVE`,
  `IDRESPONSABLE`, `IDVALIDATION`) — fin des 12 doublons ; `FAC_GRILLE_PRIX` + `GP_PERIODE` ; `FAC_GRILLE_COMPTE` +
  `ID_CATEGORIETVA` ; `ADM_PROFIL` + `PR_VALEUR` ; `FAC_QUOTIENT` = (`QU_CODE`, `QU_TYPE`) ; `COM_BADGE` = `IDBADGE` ;
  `COM_FORM_MULTIPLE` = (`FM_CL_IDENTIFIANT`, `FM_FO_GESTION_CODE`, `FM_FO_SPECIALITE`) ; `FAC_GESTION_HISTO` =
  `IDGESTION_HISTO` ; `INS_DOC_A_SIGNER` = `IDDOC_A_SIGNER` ; `VS_PARAMETRES_CLASSE` = `ID_PARAM_ETAB`. Toutes
  vérifiées uniques sur l'export du 04/10. Les 9 tables encore sur `_rowkey` (`FAC_COMPTA_GENERAL`, `COM_LOGS`,
  `ADM_ANC_CURSUS`, `ADM_LISTES_RUBRIQUES`, `ADM_STAT_RUBRIQUES`, `FAC_FORMULE_MOT`, `VS_APPEL_PROF`,
  `VS_EDITION_PARAM`, `VS_IMPORT_PARAM`) n'ont **pas de clé déclarée par l'éditeur non plus** : le repli est légitime.
- **Aucune liaison (intégrité référentielle) déclarée** dans l'analyse : le modèle relationnel repose sur les conventions
  de nommage (`IDELEVE`, `IDRESPONSABLE`, `IDCLASSE`…), ce qui confirme l'approche de ce dictionnaire.
- **Colonnes** : l'export CSV est complet, aux colonnes binaires près (37 tables : `DOCUMENT`, `IMAGE`, `PHOTO`,
  `SIGNATURE`, `GLYPHE`, `PJ`, `REGLEMENT_INTERIEUR` ne sont pas exportées — normal). Seule anomalie de casse :
  `PA_SUIVI_INSCRIPTION.Si_DELAI_JOUR2/3` dans le CSV pour `SI_DELAI_JOUR2/3` dans l'analyse.
- **Tables jamais exportées** (77) : contrôle d'accès `CC_*` (dont `CC_JOURNAL`, `CC_UTILISATEURS` avec mots de passe),
  formation continue / CFA `ENT2_CF*`, **infirmerie `INF_*`** (allergies, pathologies, vaccins, visites — données de santé
  qu'il est heureux de ne pas voir dans l'export), `VS_APPEL_INTERNAT*`. Ne pas chercher à les obtenir.
- **`COM_ELEVES.EL_NUM_SECU`** (numéro de sécurité sociale) existe dans l'export — vide pour les 510 élèves ; à ne jamais
  exposer dans un tool, comme l'IBAN.
- **Découvertes métier** : `COM_FORM_MULTIPLE` = classes à double niveau (`FM_CL_IDENTIFIANT` = `IDCLASSE`,
  `FM_FO_GESTION_CODE` = niveau) : classes 16 (MS/PS), 20 (PS/TP), 21 (GS/MS) ; `FAC_QUOTIENT` est typé (`QU_TYPE` 4 =
  tranche de revenu A/B, 5 = personnel ENS_SM/SAL_SM/ENS_EC/SAL_EC) ; la grille de prix est par période (`GP_PERIODE`).
- **Libellés de l'éditeur** pour chaque colonne (ex. `EL_55_IDELEVE` « Ancien identifiant élève », `EL_PUPILLE`,
  `EL_BOURSE*`) : dans le rapport privé — à consulter avant d'interpréter une colonne inconnue.
- **Dump incomplet** : 42 tables exportées manquent dans la structure lue (`ADM_ANCIEN` … `ADM_ICP_SAISIE`, dont
  `ADM_GED_INDEX`, `ADM_HISTO_CLASSE_MEF`, `ADM_ENCAISSEMENT`, `ADM_CURSUS`) — probablement les tables du premier essai
  d'import, créées dans une autre base. À reprendre côté PC Windows, puis refaire tourner `comparer_structure.py`.
  Idem pour `Compta2.wdd` (base Comptabilité) quand elle aura été importée.

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
