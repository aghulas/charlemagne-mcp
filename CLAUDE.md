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
   `C:\Users\<utilisateur>\OneDrive - l'établissement\Charlemagne 2025-2026\csv` (618 fichiers UTF-16-LE,
   séparateur `,`).
2. **Chargement CSV → SQLite** : `loader/load_charlemagne.py`, **idempotent** (upsert par clé primaire,
   jamais de vider/recharger complet) et produit un **rapport de diff** à chaque exécution (lignes
   ajoutées/modifiées/supprimées, alerte si le schéma d'une table change). Testé deux fois sur l'export
   réel : 2e exécution → 0 ajout/0 modification confirmés (idempotence validée).
   - Clé = 1ère colonne du CSV par défaut (convention WinDev `ID...`, confirmée sur les 618 tables).
     Quelques tables ont une clé composite déclarée dans `COMPOSITE_KEYS` en tête du script
     (`FAC_HISTO_FAMILLE`, `FAC_COMPTA_FAMILLE`, `COM_LIENER`...) — à compléter si une nouvelle table
     à clé non fiable apparaît (le loader la liste dans son rapport plutôt que de deviner).
   - Aucun DDL requis : structure déduite des en-têtes CSV (colonnes `TEXT`).
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
│   └── facturation.py                   # solde_eleve (+ prochains tools du domaine facturation)
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

Mets ce fichier à jour à chaque fois que tu découvres une subtilité du schéma ou de l'export (ex. une
table sans clé primaire propre, un encodage particulier, un décalage entre l'export CSV et les colonnes
attendues) — c'est ce genre de détail qui évite de retomber dans la même erreur.
