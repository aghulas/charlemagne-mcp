# MCP Charlemagne Server (export CSV → SQLite)

## Stack
- Python 3.10+, SDK MCP officiel (`mcp[cli]`, **v2.x** — `MCPServer`, pas `FastMCP` qui a été renommé
  entre la v1 et la v2 ; voir `mcp_server.py`), `sqlite3` (bibliothèque standard), `pandas` (loader
  uniquement)
- Source de données : base **SQLite consolidée** (`data/administration_consolidee.db`, **jamais commit**
  — voir `.gitignore`), alimentée par les **exports natifs Charlemagne** (module "Administration", 618
  CSV possibles ; jamais un accès direct à HFSQL — voir "Piste abandonnée" ci-dessous)
- Lecture seule uniquement — aucune requête INSERT/UPDATE/DELETE sur la base SQLite servie au MCP
  (le loader, lui, écrit — c'est le seul composant du projet qui écrit en base)

## Piste abandonnée — HFSQL/ODBC en accès direct
La Phase 1 initiale visait une connexion directe à la base HFSQL via le driver ODBC officiel PC Soft
(`pypyodbc`, DSN `Charlemagne Compta`). Deux découvertes ont mis fin à cette voie :
- Les fichiers HFSQL sont protégés par un **mot de passe fichier** distinct de l'ODBC ; le catalogue
  (liste des tables/colonnes) fonctionne sans lui, mais toute lecture réelle (`SELECT`) échoue.
- **Aplim a été sollicité et a explicitement refusé de communiquer ce mot de passe.** Ce n'est pas un
  blocage technique temporaire — ne pas retenter cette piste sans un changement de position d'Aplim.

Ne pas réintroduire `pyodbc`/`pypyodbc`/de DSN HFSQL dans ce projet sur cette base. Si l'exploration
ODBC doit être consultée (schéma détaillé de ~149 tables comptables trouvé à l'époque), voir
`schema-dictionary.md` et l'historique git — mais elle ne doit plus être une dépendance du pipeline.

## Pipeline de données (architecture actuelle)
Trois étapes distinctes, à ne pas fusionner (cf. `Plan_MCP_Charlemagne.md`, Phase 1) :
1. **Export** : déclenché depuis Charlemagne (fonction native si elle existe, sinon automatisation
   `pywinauto` sur la machine de test ; dépôt manuel dans un dossier partagé pour la prod le temps de
   trouver une solution pour le RD Gateway). En attendant, un export réel est disponible dans
   `C:\Users\<utilisateur>\OneDrive - <Ecole>\Charlemagne\csv` (fichiers UTF-16-LE,
   séparateur `,`).
2. **Chargement CSV → SQLite** : `loader/load_charlemagne.py`, **idempotent** (upsert par clé primaire,
   jamais de vider/recharger complet) et produit un **rapport de diff** à chaque exécution (lignes
   ajoutées/modifiées/supprimées, alerte si le schéma d'une table change). Testé deux fois sur l'export
   réel : 2e exécution → 0 ajout/0 modification confirmés (idempotence validée).
   - Clé = 1ère colonne du CSV par défaut (convention WinDev `ID...`, confirmée sur les 618 tables).
     Quelques tables ont une clé composite déclarée dans `COMPOSITE_KEYS` en tête du script
     (`FAC_HISTO_FAMILLE`, `FAC_COMPTA_FAMILLE`, `COM_LIENER`, `COM_PIECE_RECU`, `PA_SUIVI_CONSOMMATEUR`,
     `COM_PREFERENCES`...). **Une table dont la clé a des doublons n'est plus ignorée** (02/10/2026) :
     elle est chargée avec la clé de secours `_rowkey` (hash de la ligne + rang d'occurrence, les
     doublons exacts de `FAC_COMPTA_GENERAL` sont conservés) et *remplacée* à chaque export (sans
     identité stable, une ligne modifiée serait sinon cumulée avec l'ancienne). Avant cette correction,
     le flux « un clic » servait une base à 102 tables au lieu de 123 — sans `PA_SUIVI_CONSOMMATEUR`,
     `FAC_COMPTA_GENERAL`, `COM_PIECE_RECU`, `FAC_HISTO_ELEVE` — et l'audit, la fiche famille et la
     comparaison d'exports ne fonctionnaient plus.
   - **Clés alignées sur l'analyse WinDev de l'éditeur (05/10/2026)** : la structure déclarée dans
     `Eleves.wdd` (lue depuis une base HFSQL vide, outillage dans le dépôt privé `charlemagne-tools`)
     a donné les vraies clés de 10 tables (`FAC_HISTO_ELEVE` = élève + responsable + validation,
     `FAC_GRILLE_PRIX` + période, `COM_BADGE` = `IDBADGE`…, voir `schema-dictionary.md`). Il ne reste
     que 9 tables sur `_rowkey`, toutes sans clé déclarée par l'éditeur. **Toutes les clés déclarées
     sont livrées dans `loader/cles_declarees.json`** (632 tables), consulté après `COMPOSITE_KEYS` et
     avant la 1ère colonne du CSV — y compris pour les tables encore vides, dont 92 auraient eu une
     clé fausse en se remplissant. Ne pas deviner une clé : la lire dans ce fichier, et le régénérer
     depuis `charlemagne-tools/scripts/hfsql` si l'analyse change.
   - Un CSV vide (en-tête seul) crée la table, ou la vide si elle avait des lignes : `FAC_GESTION_*`
     redevient vide après validation. Si la clé d'une table en base change, la table est reconstruite.
   - **Réplication complète (02/10/2026, soir)** : les lignes en base absentes de l'export sont
     désormais **supprimées** (le rapport les liste toujours). Le flux « un clic » produit toujours un
     export complet, donc une ligne absente a été supprimée dans Charlemagne — constaté avec la pièce
     à verser retirée d'une fiche responsable : `COM_PIECE_RECU` passe à « Non Reçue » et l'entrée
     `ADM_GED_INDEX` du document disparaît ; avant, elle restait en fantôme. Seule protection : une
     table dont le CSV est absent de l'export n'est pas touchée ; `--conserver` rétablit l'ancien
     comportement pour un export que l'on sait partiel. Une valeur vide dans une colonne clé est
     stockée `''` (deux NULL ne sont jamais égaux dans une clé SQLite : la ligne était réinsérée à
     chaque export — `COM_PREFERENCES`).
   - Aucun DDL requis : structure déduite des en-têtes CSV (colonnes `TEXT`).
   - Sur le Mac, c'est `~/Charlemagne/automatisation/charlemagne_load_inbox.sh` (launchd) qui appelle ce
     loader. Depuis la VM Cowork (dossier monté), SQLite échoue en écriture (« disk I/O error ») :
     charger dans `$HOME` puis copier la base.
3. **Orchestration (fait)** : tâche planifiée Windows `"Charlemagne CSV Loader"`, quotidienne à 6h30, mode
   "Interactive only" (tourne seulement session ouverte — nécessaire pour l'accès OneDrive). Commande :
   `pythonw.exe loader\run_scheduled_load.py`. Testée par déclenchement manuel (`schtasks /run`), log
   confirmé dans `logs/latest.log`, `Last Result: 0`.
   - `loader/run_scheduled_load.py` : wrapper qui capture tout (le Planificateur ne capture pas stdout)
     dans `logs/load_<horodatage>.log` + `logs/latest.log`, ne plante jamais silencieusement (trace
     complète loguée + code de sortie non-nul en cas d'erreur, visible dans l'historique du
     Planificateur), purge les logs au-delà de 30 exécutions. Chemin CSV/DB par défaut en dur (contexte
     non interactif = pas de cwd garanti), surchargeable via `CHARLEMAGNE_CSV_DIR` / `CHARLEMAGNE_DB`.
   - Gère explicitement le cas "dossier CSV introuvable" (OneDrive pas synchronisé) sans crash.
   - Commandes utiles : `schtasks /query /tn "Charlemagne CSV Loader" /v /fo list` (statut, dernier
     résultat), `schtasks /run /tn "Charlemagne CSV Loader"` (déclenchement manuel pour tester),
     `schtasks /delete /tn "Charlemagne CSV Loader" /f` (suppression).

Conséquence pour le MCP : les données ne sont jamais "temps réel", mais "à la date du dernier export" —
acceptable pour les cas d'usage identifiés (soldes, impayés, suivi mensuel). Chaque tool devrait pouvoir
indiquer la fraîcheur des données qu'il sert.

## Modèle de données à garder en tête
Détail complet et vérifié sur données réelles dans `schema-dictionary.md`. Résumé :

- `COM_ELEVES` (élève) → `COM_LIENER` (liaison, clé composite `IDRESPONSABLE`+`IDELEVE`, **un élève peut
  avoir plusieurs responsables**) → `COM_RESPONSABLES` (famille payeuse, équivalent du compte 411 côté
  ancien monde HFSQL : `RE_CODE_COMPTABLE` a le même format que `TAB_PLAN_COMPTABLE.COMPTE`, ex.
  `4111BONELLE`).
- Facturation : `FAC_VALIDATION` (un événement de facturation) → `FAC_COMPTA_FAMILLE` /
  `FAC_HISTO_FAMILLE` (impact/détail par famille, clé composite `IDVALIDATION`+`IDRESPONSABLE`) →
  `FAC_HISTO_LIGNE` (détail des lignes facturées).
- Ne jamais supposer un seul responsable par élève, ni traiter "solde d'un élève" comme une clé simple —
  toujours passer par `COM_LIENER` et retourner explicitement le nom du responsable/famille concerné.
- **Points ouverts à ne pas oublier** (détaillés dans `schema-dictionary.md`) : pas de statut de facture
  fiable trouvé (`HF_ETAT` n'a qu'une seule valeur observée) ; pas de table de règlements peuplée dans
  l'export actuel (`ADM_ENCAISSEMENT*` vides) → "impayés" n'est pas encore implémentable proprement ;
  `FAC_HISTO_ELEVE` a une clé composite non garantie unique (12 lignes ambiguës sur 1113, table exclue
  du chargement pour l'instant).

## Premier tool MCP — solde_eleve (Phase 3, fait)
`mcp_server.py` expose `solde_eleve(id_eleve)` (implémentation dans `tools/facturation.py`, connexion
dans `db/connection.py`). Testé de bout en bout via `server.call_tool(...)` réel (pas juste la fonction
Python) contre la vraie base : élève facturé, élève sans facturation (plusieurs responsables), élève
inexistant — voir `scripts/smoke_test_mcp_server.py`. Test unitaire associé dans
`tests/test_facturation.py`, sur **données synthétiques uniquement** (jamais de vraies données d'élèves
dans un fichier commité — voir Phase 0 du plan).

Patron à réutiliser pour chaque nouveau tool :
1. Fonction pure dans `tools/<domaine>.py` : prend une connexion + des paramètres, retourne un `dict`,
   ne lève que des erreurs "attendues" (`ValueError` pour une entrée invalide).
2. Wrapper `@server.tool(...)` dans `mcp_server.py` : ouvre/ferme la connexion, **attrape les
   `ValueError` et les convertit en `{"error": ...}`** plutôt que de laisser l'exception remonter brute
   (sinon elle atterrit dans une stack trace visible du modèle — vu en testant le cas "élève inexistant").
3. Test unitaire sur données synthétiques dans `tests/test_<domaine>.py`.
4. Toujours inclure une note de fraîcheur/limites dans le résultat quand le tool touche un domaine où on
   sait qu'une donnée n'est pas fiable (ex. `solde_eleve` rappelle que "statut de facture"/"impayés" ne
   sont pas déductibles de ce résultat).

## Audit de facturation et comparaison d'exports (fait)
Deux tools pour le cycle « nouvel export -> qu'est-ce qui a change -> la facturation est-elle juste ? » :
- `comparer_exports(archive=None)` (`tools/comparaison.py`) : compare la base servie a une archive
  (la plus recente de `CHARLEMAGNE_ARCHIVES_DIR` par defaut). Volumes par table, parametrage de la
  facturation (FAC_FORMULE, FAC_LIGNE, grilles de prix et de comptes, remises, regimes, quotients),
  fiches eleves/responsables/foyers, COM_LIENER (payeur, %, responsable principal), informations
  complementaires, facturation recalculee ou validee. Les champs bancaires ne sortent jamais en clair :
  liste `CHAMPS_MASQUES` + filet par motif `est_masque()` (IBAN, BIC, banque, guichet, RIB, domiciliation,
  titulaire `TIRE`, mandat, RUM, numero de securite sociale) ; un champ masque qui change est signale
  « renseigné (modifié) ». Corrige le 30/09/2026 : `RE_DOMICILIATION` et `RE_TIRE` sortaient en clair et
  `RE_GUICHET` ne correspondait a aucune colonne (vraie colonne : `RE_CODE_GUICHET`).
  Alerte si les formules ont change sans que la preparation ait ete relancee.
- `audit_de_facturation(validee=False)` (`tools/audit_facturation.py`) : controle la preparation
  (FAC_GESTION_*) ou la facturation validee (FAC_HISTO_* + FAC_COMPTA_* : numerotation, equilibre
  produits - reductions = clients). **Generique** : tarifs, codes de lignes et regles viennent du
  fichier JSON `CHARLEMAGNE_REGLES_FACTURATION` (format : `docs/regles_facturation.exemple.json`),
  jamais du code — le fichier reel de l'etablissement vit hors du depot.

Comportements du moteur de formules Charlemagne qui justifient ces controles (constates sur une
facturation reelle, a garder en tete) :
- la premiere condition vraie d'une formule l'emporte (exclusions a placer en premier) ;
- une ligne a une formule de quantite ET une formule de prix ; reutiliser une ancienne formule de prix
  comme quantite multiplie le montant ;
- `FAMNBENFANTS` ne compte que les enfants dont le responsable porteur de la ligne est responsable
  principal (LER_TYPE_RESP = 1) : un payeur a 100 % non principal ne recoit aucune reduction fratrie ;
- la valeur « Non » de COT_APEL n'est pas 0 ; un champ vide n'est pas egal a 0 ;
- une ligne n'est facturee a une classe que si elle a un compte dans FAC_GRILLE_COMPTE ;
- le code de frequence reste « TARIF » meme avec un echeancier mensuel : lire GF_ECHE_PRIXn.
Tests : `tests/test_comparaison.py`, `tests/test_audit_facturation.py` (donnees synthetiques).
Bout en bout : `scripts/smoke_test_audit.py` (vraie base, ne rien commiter de sa sortie).

## Pièces à verser : suppression côté Charlemagne (constaté le 02/10/2026)
Une pièce déposée par une famille (ou pour elle, via `ed_admin_deposer_piece`) et récupérée par
Charlemagne est « verrouillée » dans EcoleDirecte : aucun écran ni endpoint EcoleDirecte ne permet de
la télécharger, remplacer ou supprimer, et le fichier est chiffré sur le serveur Aplim. La suppression
se fait dans Charlemagne Administratif (fiche du responsable/élève, pièces du dossier) : effet
**immédiat** dans EcoleDirecte (`ed_admin_pieces_etat` → non déposée, déverrouillée, la famille peut
redéposer), et à l'export suivant `COM_PIECE_RECU` passe à « Non Reçue » et l'entrée GED disparaît.
Pour contrôler le contenu d'une pièce (année scolaire, nature) : seules les pièces déposées par l'école
(chaîne scans → EcoleDirecte) ont un PDF source lisible, dans `~/Charlemagne/plan_depot_scans.json`
→ SharePoint du secrétariat ; les scans n'ont pas de couche texte (lecture visuelle).

## Suivi de la facturation en cours d'annee (fait, 02/10/2026)
Charlemagne ne recalcule pas une facture validee : apres la facturation initiale, les changements
(forfaits, justificatifs tardifs, arrivees, departs, reglement) passent par une **facture
complementaire ou un avoir manuel** (formation Aplim CFP12 : complementaire calculee ou manuelle, avoir
manuel ou automatique, reactualisation de l'echeancier). Constate sur la validation n° 2 du 01/10/2026
(type `Manuelles`, factures 271-272) : les lignes manuelles sont saisies dans `FAC_GESTION_HISTO`
(`GH_CODE_LIGNE`, `GH_QTE`, `GH_PRIX`, `GH_LIBELLE`), la validation cree une nouvelle `FAC_HISTO_FAMILLE`
par responsable dont `HF_ORI_SOLDE` est le **solde restant des factures precedentes** (pas une dette ;
`HF_SOLDE_PRIS` vaut 1 partout, ce n'est pas le discriminant) et dont l'echeancier re-etale ce solde +
la complementaire sur les mois restants ; `FAC_VALIDATION.VA_TYPE_FACTURE` = `Toutes` / `Manuelles` ;
`FAC_LOG` garde la trace d'une facture supprimee.
- `tools/regles_facturation.py` : moteur commun « lignes attendues » (`Contexte`, `attendu_eleve`,
  `fratrie_attendue`, `apel_attendue`) + prorata au mois (`regles["prorata"]`, defaut 9 → 10 mois,
  tout mois commence est du). Utilise par l'audit et par les deux tools ci-dessous.
- `regularisations_a_preparer(date_effet, id_eleve)` (`tools/suivi_facturation.py`) : cumul facture
  (toutes validations, hors lignes de regroupement) vs attendu, par eleve et par code ; propose les
  lignes de facture manuelle (code, quantite 1, prix plein et prix au prorata, libelle, quote-part des
  payeurs). Modele : une ligne de la facturation initiale couvre l'annee ; une ligne d'une
  complementaire couvre les mois a partir du mois de la facture, **sauf si son montant est le tarif
  annuel entier** (alors elle couvre l'annee — choix de Remi pour une prestation suivie depuis la
  rentree). Rubriques : regularisations, departs (avoir sur les mois suivant la sortie), nouveaux eleves
  (contribution = lignes de la classe sur la facturation initiale), apel (sans prorata), remise
  personnel absente, lignes manuelles en attente (avec controle : conforme / deja conforme / a
  verifier), justificatifs recus sans information saisie (`regles["pieces_justificatifs"]`) et
  l'inverse.
- `suivi_echeanciers(id_responsable)` : factures de l'annee, echeances passees / a venir, reste a
  prelever, alertes (echeancier incoherent, mode de reglement modifie depuis la facture, prelevement
  sans IBAN, echeances irregulieres, payeur modifie, enfant du payeur non facture). Pas de statut
  paye/impaye (aucun encaissement exporte).
- `audit_de_facturation` et `fiche_famille` sont devenus **cumulatifs** : lignes additionnees sur toutes
  les validations, echeancier lu sur la derniere facture, solde reporte lu sur la premiere ; rubriques
  informatives `ligne_de_regularisation` et `ligne_au_prorata` ; `fiche_famille` renvoie le detail par
  facture (`factures`) et les lignes manuelles en attente.
Tests : `tests/test_suivi_facturation.py`, `tests/test_loader.py`. Bout en bout : `scripts/smoke_test_suivi.py`.

## Droits EcoleDirecte des adultes (fait, 30/09/2026)
`droits_ecoledirecte_personnels(id_personnel=None, actifs_seulement=True)` (`tools/personnels.py`,
fonction `droits_ecoledirecte`) : pour chaque adulte, coche « Utilisateur EcoleDirecte »
(`COM_PERSONNELS.PE_AVECED`), fonctions (`TAB_FONCTIONS` / `ADM_FONCTION_PERSONNEL` — sans fonction,
un personnel est invisible des familles dans la messagerie ED), établissements cochés et
fonctionnalités autorisées (`COM_PERSONNELS_ED`, `PED_TYPE` = `ETAB` / `MODULE`, clé `ID_PERSO_ED`),
notifications (`COM_PERSONNELS_PREFERENCE`, `PEP_TYPE` = `INT_*`), points d'attention calculés, et
options des profils utilisateurs Charlemagne (`ADM_PROFIL`, dont `EcoleD_LoginPass`). Libellés des
codes rapprochés du support de formation Aplim « CED4 – Ecole Directe » (§3.1, §7.3) ; un code inconnu
est renvoyé tel quel. Les enseignants (`PE_TYPE = 'prof'`) héritent de leurs droits par leur
catégorie : pas de point d'attention pour eux, et renvoyés en résumé sauf `detail_enseignants=True` ou
`id_personnel` précis. Hors export : case « Activer les notifications
EcoleDirecte » de Charlemagne Outils, profil administrateur de la console ED.
Tests : `tests/test_droits_ecoledirecte.py` (données synthétiques).

## Historique des mails envoyés (fait, 01/10/2026)
`historique_mails_charlemagne(recherche, destinataire, depuis, jusqu_a, id_histo, limite)`
(`tools/historique_mails.py`) : mails envoyés depuis Charlemagne (`COM_HISTORIQUE_MAILS`, une ligne
par envoi), du plus récent au plus ancien. Format de la table, relevé sur l'export réel :
- `DATE_ENVOI` en AAAAMMJJ, sans heure ; l'heure se lit dans `NOM_CAMPAGNE`
  (`<etab>_<AAAAMMJJHHMMSSmmm>_<n>`) ;
- trois listes **parallèles** séparées par « ; » (parfois avec un « ; » final) : `LISTE_CLIENTS`
  (« NOM Prénom(Perso) » — type d'adresse entre parenthèses), `LISTE_MAILS`, `LISTE_TYPES`
  (famille, prof) ;
- `CORPS` en HTML, avec les variables de publipostage non résolues (#SITE, #LOGIN, #PASS) ; le renvoi
  des codes depuis la fiche famille (« renvoyer par e-mail ») produit un message automatique, sans ces
  variables ;
- `IDPERSONNEL` = fiche adulte liée à l'utilisateur Charlemagne qui a envoyé (0 si aucune) — ce n'est
  pas forcément la personne physique derrière le poste ;
- **aucun statut de remise** : la liste noire des adresses en erreur existe dans Charlemagne mais n'est
  pas exportée.
Le filtre `destinataire` revérifie la correspondance entrée par entrée (un LIKE sur la liste brute
peut chevaucher deux adresses). Tests : `tests/test_historique_mails.py` (données synthétiques).

`journal_transferts_ecoledirecte(depuis, jusqu_a, avec_documents_seulement, limite)`
(`tools/journal_ecoledirecte.py`) : journal des transferts Charlemagne → EcoleDirecte, lu dans la
copie locale du fichier texte `EcoleDirecte Journal <RNE>.txt` du partage serveur (variable
`CHARLEMAGNE_JOURNAL_ED` ; ce fichier n'est pas dans l'export CSV, il arrive avec la sauvegarde du
partage). Par transfert : début/fin, version, poste, mode (automatique de nuit / manuel),
réplications par module, erreurs (message tronqué, sans l'URL du webservice), abandons, nombre de
documents PDF envoyés. `publications_documents` liste les transferts qui ont publié des PDF dans
l'espace Documents d'EcoleDirecte (circulaires, factures, documents à signer) — publication qui
ne notifie pas les familles. Le journal ne donne ni intitulé ni destinataires : les lire côté
EcoleDirecte (`ed_admin_documents_ecole`, connecteur ecoledirecte-admin-mcp). Fichier ANSI (cp1252)
ou UTF-8. Tests : `tests/test_journal_ecoledirecte.py` (journal fictif).

## Enrichissements et nouveaux tools issus de l'inventaire des tables (fait, 03/10/2026)
Inventaire complet des 119 tables peuplées dans `schema-dictionary.md` (§ Inventaire) : 68 tables
classées, 12 explorées. Résultat dans le code :
- `tools/referentiels.py` : libellés `TAB_LIENS` (lien de parenté, 30 codes — remplace le petit
  dictionnaire codé en dur), `TAB_CSP`, `TAB_SIT_FAM` ; enseignants principaux par classe
  (`COM_PROFS_PRINCIPAUX`, plusieurs lignes possibles en co-enseignement) ; ancienneté par élève
  (`ADM_HISTO_CLASSE_MEF`, une ligne par année scolaire passée). Toutes les fonctions **tolèrent
  l'absence d'une table** (retour vide) pour qu'un outil ne casse jamais sur une base ancienne ou de test.
- `liste_eleves` : `enseignants`, `premiere_annee`, `nb_annees_precedentes` ; `liste_personnels` :
  `classes` ; `responsables_eleves` et `fiche_famille` : `lien_libelle` ; `fiche_famille` : aussi
  `situation_familiale` et `csp` en libellé (identité/contexte, jamais de données bancaires).
- `modifications_ecoledirecte_en_attente(statut='En attente')` (`tools/modifications.py`) :
  `COM_JOURNAL_MODIF` = **file de sortie** Charlemagne → EcoleDirecte : fiches (élève/responsable) modifiées
  dans Charlemagne, à envoyer par la synchro (les lignes envoyées sont supprimées ; la table n'est pas répliquée
  vers EcoleDirecte). Utilisateur Charlemagne qui a modifié, dates de modification et d'envoi (zéro = jamais
  envoyé), statut, `motif_probable` quand la ligne est bloquée (élève sorti, responsable sans élève actif).
  Établi le 03/10/2026 : la validation dans Charlemagne d'une demande EcoleDirecte crée une ligne ; les six
  lignes restantes de l'export concernent des élèves sortis. Ce n'est **pas** la liste des demandes des
  familles en attente (celle-ci est dans la console EcoleDirecte).
- `jours_de_classe(id_classe=None)` (`tools/calendrier.py`) : jours de classe par mois d'après `VS_CONGE`
  (jours sans classe, `IDCLASSE = 0` = toute l'école) et `VS_TAB_PERIODES` (T1 → T3) — 139 jours sur
  2026-2027. Base des prorata au jour ; le prorata au mois reste la règle des forfaits.
- Non exploités volontairement : `FAC_HISTO_IBAN` (bancaire), module Passage (`PA_*`, pas encore en
  production), référentiels nationaux (`TAB_ETAB_ORI`, `TAB_VILLE`, `TAB_COMMUNE` : 180 000 lignes).
Tests : `tests/test_referentiels_enrichissements.py` (données synthétiques).

## Vie scolaire : emploi du temps et appels (fait, 04/10/2026)
- `emploi_du_temps_classe(classe, date_debut=None, date_fin=None)` (`tools/vie_scolaire.py`) : horaires
  applicables (`VS_HORAIRE_CLASSE` s'ils existent, sinon `VS_HORAIRE`), semaine type la plus récente
  (`VS_EDT_TYPE_COURS` + `VS_EDT_TYPE_PROF`/`VS_EDT_TYPE_SALLE`, semaine A/B, nombre de cours sans
  matière) et, si une date est donnée, cours générés (`VS_EDT_COURS` + `VS_EDT_PROF`/`VS_EDT_SALLE`) avec
  le calendrier A/B (`VS_EDT_ALTERNANCES`). `classe` = id, code (`CM2A`) ou libellé (`CM2 A`).
- `appels_enseignants(date_debut, date_fin, classe, detail_absences=False)` : appels saisis dans
  EcoleDirecte et intégrés (`VS_APPEL_PROF`), par classe et demi-journée, avec récapitulatif ;
  `detail_absences` ajoute les élèves absents (`VS_ABSENCE_JOUR`).
- Constats utiles (04/10/2026) : l'import EDT de Charlemagne **recale à l'import** (pas à la génération)
  tout début/fin à 10 min ou moins des bornes des horaires de l'**établissement** (`VS_HORAIRE`), même
  quand la classe a ses propres horaires ; les bornes de récréation ne recalent rien. Charlemagne garde
  **un seul appel par enseignant, classe et horodatage de saisie à la seconde** : deux demi-journées
  envoyées dans la même seconde n'en font qu'une dans `VS_APPEL_PROF` (les absences, elles, sont toutes
  dans `VS_ABSENCE`).
Tests : `tests/test_vie_scolaire.py` (données synthétiques).

## Règles non négociables
- Jamais de concaténation de chaînes SQL — requêtes paramétrées uniquement (`sqlite3` avec `?`)
- Jamais d'identifiants en dur dans le code — variables d'environnement / config uniquement
- Le loader CSV → SQLite doit être idempotent et produire un rapport de diff à chaque exécution
- Chaque nouvel outil MCP = une fonction + un test associé, jamais l'un sans l'autre

## Structure
```
charlemagne-mcp/
├── mcp_server.py                        # serveur MCP stdio - tools declares ici
├── tools/
│   ├── facturation.py                   # solde_eleve
│   ├── personnels.py                    # liste_personnels, droits_ecoledirecte_personnels
│   ├── referentiels.py                  # libelles (liens, CSP, situation fam.), enseignants/classe, anciennete
│   ├── modifications.py                 # modifications_ecoledirecte_en_attente (COM_JOURNAL_MODIF)
│   ├── calendrier.py                    # jours_de_classe (VS_CONGE, VS_TAB_PERIODES)
│   ├── vie_scolaire.py                  # emploi_du_temps_classe, appels_enseignants (VS_EDT_*, VS_APPEL_PROF)
│   ├── regles_facturation.py            # moteur commun : lignes attendues, prorata au mois (regles JSON)
│   ├── audit_facturation.py             # audit_de_facturation (regles : CHARLEMAGNE_REGLES_FACTURATION)
│   ├── suivi_facturation.py             # regularisations_a_preparer, suivi_echeanciers (cours d'annee)
│   ├── comparaison.py                   # comparer_exports (archives : CHARLEMAGNE_ARCHIVES_DIR)
│   ├── historique_mails.py              # historique_mails_charlemagne (COM_HISTORIQUE_MAILS)
│   └── journal_ecoledirecte.py          # journal_transferts_ecoledirecte (CHARLEMAGNE_JOURNAL_ED)
├── db/
│   └── connection.py                    # connexion SQLite lecture seule (CHARLEMAGNE_DB ou defaut)
├── loader/
│   ├── load_charlemagne.py              # CSV -> SQLite, idempotent, rapport de diff
│   └── run_scheduled_load.py            # wrapper pour le Planificateur de taches (logging, pas de crash silencieux)
├── data/                                # base(s) SQLite generees - jamais commit (donnees sensibles)
├── logs/                                # logs du chargement planifie - jamais commit
├── tests/
│   └── test_facturation.py              # donnees synthetiques uniquement
├── scripts/
│   └── smoke_test_mcp_server.py         # test bout-en-bout du serveur contre la vraie base
├── schema-dictionary.md                 # reference des tables utiles aux cas d'usage (pas les 618)
├── load_erp.py, load_erp_combined.py    # OBSOLETES (racine) - remplaces par loader/, a supprimer
└── test_connection.py, venv/, venv32/,
    scripts/inspect_schema.py,           # exploration ODBC HFSQL abandonnee - a nettoyer
    scripts/peek_sample.py
```

## Commandes
```
venv\Scripts\python.exe loader\load_charlemagne.py <dossier_csv> [--db data\administration_consolidee.db]
venv\Scripts\python.exe mcp_server.py                        # lancer le serveur (stdio)
venv\Scripts\python.exe scripts\smoke_test_mcp_server.py 920 # tester un tool contre la vraie base
pytest -v                        # tests (donnees synthetiques)
ruff check . && ruff format .    # lint
```

## Déploiement Azure (streamable-http)

```
python mcp_server.py --transport streamable-http --host 0.0.0.0 --port 8000
```

Web App Azure : `charlemagne-mcp-fontainebleau` (resource group `rg-charlemagne-mcp`,
plan `plan-charlemagne-mcp`), **port 8000** (`WEBSITES_PORT=8000`) — cette commande
exacte est le Startup Command posé dans Configuration → Stack settings (relevé le
22/09/2026, ne pas deviner une autre valeur). Variables d'environnement : voir le
dépôt partagé `mcp-entra-auth` pour `MCP_ENTRA_TENANT_ID` / `MCP_ENTRA_APP_ID_URI` /
`MCP_ENTRA_ALLOWED_GROUP_ID` / `MCP_ENTRA_PUBLIC_URL`. CI/CD : GitHub Actions via
Deployment Center, branché sur ce dépôt.

Mets ce fichier à jour à chaque fois que tu découvres une subtilité du schéma ou de l'export (ex. une
table sans clé primaire propre, un encodage particulier, un décalage entre l'export CSV et les colonnes
attendues) — c'est ce genre de détail qui évite de retomber dans la même erreur.

## Comptabilite : FEC -> SQLite, encaissements et impayes (fait, 08/10/2026)
Le module Comptabilite de Charlemagne n'a ni export CSV de ses tables ni ligne de commande (essais du
04/10 : `ADMDuplication` refuse le dossier comptable, aucune tache planifiee compta). Source retenue :
l'export **Outils > DGI/FEC**, fait a la main en session RDP (destinataire « Non DGI », type Texte, periode
du debut de l'exercice ouvert a la date du jour), depose dans le dossier d'echange du Mac.
- `loader/load_fec.py <FEC> [--db ...]` : remplace entierement la base comptable (`CPT_ECRITURE`,
  `CPT_EXPORT`), construite dans un fichier temporaire puis substituee. Base par defaut :
  `CHARLEMAGNE_COMPTA_DB`, sinon `comptabilite_consolidee.db` **a cote de `CHARLEMAGNE_DB`** (meme regle
  dans `db/connection_compta.py` : aucune configuration a ajouter a Claude Desktop). Refuse un FEC
  desequilibre. Lignes de paie (journal « PAIE », comptes 42x/43x/64x) chargees sans libelle ni compte
  auxiliaire. Particularites du FEC Charlemagne « Non DGI » : 19 champs pour 18 noms d'en-tete (19e =
  journal+piece, colonne `cle_piece`), `EcritureNum` et `DateLet` vides ; nom de fichier = date de cloture
  de l'exercice, pas de la periode (un export prolonge ecrase le precedent).
- `db/connection_compta.py` : base Administratif en lecture seule + base comptable attachee en lecture
  seule sous le schema `compta`. Jointure famille : `COM_RESPONSABLES.RE_CODE_COMPTABLE` =
  `CPT_ECRITURE.compte_aux` (270 payeurs sur 270 retrouves le 08/10).
- `tools/comptabilite.py` : `encaissements_famille` (solde 411, factures, reglements avec mode presume,
  impayes, frais, statut de chaque echeance) et `impayes_et_retards` (liste et resume). Regles :
  - les comptes 411 ne sont **pas lettres** : retard = solde - echeances a venir de la derniere facture
    validee (`FAC_HISTO_FAMILLE.HF_ECHE_*`) ; le solde est cumule depuis le debut de l'exercice ouvert,
    comme `HF_ORI_SOLDE` repris dans l'echeancier ;
  - une echeance n'est echue que `delai_jours` (5) apres sa date : la remise du 29/09 est comptabilisee
    le 01/10 ; date de reference par defaut = derniere ecriture du FEC ;
  - impaye = debit du 411 hors facturation et a-nouveaux, libelle `impay|rejet|represent` ; frais =
    debit dont la piece a un credit de meme montant sur un compte 758 (ou libelle « frais »/« frs ») ;
    journaux de facturation et d'a-nouveaux reconnus a leur libelle (« FACTUR »/« VENTE », « NOUVEAU ») ;
  - un cheque recu mais pas encore saisi en comptabilite apparait comme un retard (familles « Cheque » a
    echeance unique au 15/09) : le resultat le rappelle.
  Valide le 08/10/2026 sur le FEC reel (8 312 lignes, 01/09/2025 -> 07/10/2026) : 23 familles en retard
  dont les 4 impayes de septembre non regularises (prelevement, 220 a 306 EUR), 18 familles « Cheque » sans
  cheque saisi, 1 ancien compte avec impayes ; 14 familles a impaye regularise.
Tests : `tests/test_comptabilite.py` (donnees synthetiques). Ne jamais commiter un FEC (`*FEC*.txt` ignore).
