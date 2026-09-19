# Plan de développement — MCP Charlemagne

*Connecter un agent IA (Claude, ChatGPT, Gemini, Copilot 365) aux données Charlemagne.*

---

## Mise à jour — deuxième pivot : export natif plutôt qu'accès direct à HFSQL

Le plan a d'abord basculé du pilotage RDP vers une connexion directe à HFSQL (driver ODBC officiel PC Soft). En pratique, deux découvertes ont fait échouer cette voie :

- Les tables HFSQL sont protégées par un **mot de passe fichier** distinct du mot de passe ODBC/DSN. Le catalogue ODBC (liste des tables/colonnes) fonctionne sans lui, mais toute lecture réelle (`SELECT`) échoue sans ce mot de passe.
- **Aplim a été sollicité et a explicitement refusé de le communiquer.** Ce n'est plus un problème de documentation manquante — c'est un refus délibéré de l'éditeur d'ouvrir un accès direct à la base sous-jacente.

Conséquence : on abandonne complètement la connexion HFSQL/ODBC en lecture directe. Le projet repart sur ce qui fonctionnait déjà avant l'exploration ODBC — **les exports natifs de Charlemagne, consolidés dans une base SQLite** (le pipeline CSV → SQLite déjà construit, avec dictionnaire de données). C'est un mécanisme documenté et fourni par Aplim lui-même, donc sans ambiguïté sur la légitimité, et c'est aussi l'architecture la plus adaptée si l'outil doit un jour être diffusé à d'autres établissements (chacun exporte sa propre base, personne ne partage un accès direct).

La contrepartie : les données ne sont plus "temps réel" mais "à la date du dernier export" — acceptable pour la quasi-totalité des cas d'usage identifiés (soldes, impayés, suivi mensuel).

---

## Ce qui change de direction (contexte historique — pilotage RDP abandonné)

Jusqu'ici, l'idée était de piloter Charlemagne à distance via son interface (RDP/écran). C'est fragile par nature (OCR, coordonnées, gateway non supporté par les outils existants) et ça ne peut pas devenir un produit distribuable.

Le fait que tu aies maintenant une machine Windows avec Charlemagne installé et une copie de la base change complètement l'angle d'attaque : on peut se brancher **directement sur les données**, sans jamais passer par l'interface graphique ni par le RD Gateway. C'est plus robuste, plus rapide, et c'est la seule approche qui a du sens si l'outil doit un jour servir à d'autres utilisateurs.

Point technique clé : Charlemagne est développé en WinDev/WebDev (PC Soft) et stocke ses données en **HFSQL** (les fichiers `.FIC`/`.FCX`/`.MMO` que tu avais déjà identifiés). PC Soft publie un **driver ODBC officiel pour HFSQL Classic et HFSQL Client/Serveur** — c'est la voie légitime pour se connecter (via `pyodbc` par exemple), plutôt que de reparser les fichiers binaires à la main. Aucune API web officielle d'Aplim pour l'intégration tierce n'est documentée publiquement — donc l'ODBC est probablement le chemin le plus propre disponible aujourd'hui.

---

## Phase 0 — Cadrage (à ne pas sauter)

Avant d'écrire une ligne de code, trois questions à trancher parce qu'elles orientent toute l'architecture :

1. **Portée des données de minors/RGPD.** Charlemagne contient des données d'élèves (souvent mineurs) et des données financières des familles. Un outil qui expose ça à un LLM — même en lecture seule — est un traitement automatisé de données sensibles. Si l'ambition va au-delà de ton propre usage dans ton établissement, il faudra probablement une analyse d'impact (AIPD/DPIA) avant toute diffusion, et une politique claire de minimisation (quelles données un outil a réellement besoin d'exposer, pas "toute la base").
2. **Relation avec Aplim.** Se connecter à la base sous-jacente d'un logiciel commercial, même via un driver officiel, reste hors du cadre contractuel prévu par l'éditeur. Avant d'envisager une diffusion à d'autres établissements, ça vaut le coup de vérifier les CGU/contrat de licence Charlemagne, et idéalement d'ouvrir le sujet avec Aplim directement — soit ils ont déjà une doctrine là-dessus, soit ça peut devenir un partenariat plutôt qu'un contournement.
3. **Lecture seule d'abord.** Techniquement et politiquement, commencer strictement en lecture (consultation, pas de modification via l'IA) réduit le risque de façon disproportionnée par rapport à l'effort économisé. L'écriture (import d'écritures, etc.) peut rester sur le circuit que tu as déjà validé (imports natifs Charlemagne), séparé du MCP.

Ces trois points ne bloquent pas l'expérimentation technique sur ta machine de test — ils bloquent la diffusion à d'autres. Tu peux avancer sur les phases suivantes en parallèle.

---

## Phase 1 — Construire et automatiser le pipeline export → SQLite

Trois étapes distinctes, à ne pas fusionner :

### 1. Déclencher l'export depuis Charlemagne

D'abord vérifier s'il existe une fonction d'export planifiée/en ligne de commande native dans Charlemagne (menus Administration/Outils, aide intégrée) — rien de confirmé publiquement là-dessus, donc à checker directement plutôt qu'à supposer que ça n'existe pas. Si ça existe, ça élimine le besoin de tout ce qui suit dans cette étape.

Sinon :
- **Sur la machine de test** (Charlemagne installé en local) : automatisable dès maintenant avec Claude Code, via **pywinauto** (pilotage par l'arbre d'accessibilité Windows, pas par coordonnées de pixels — plus robuste). Point de vigilance : les applis WinDev exposent parfois mal leurs contrôles à l'accessibilité Windows ; prévoir un mode de repli par coordonnées si besoin, à valider empiriquement.
- **Sur la production** (derrière le RD Gateway/TSE) : ni Cowork ni agent-rdp ne gèrent ce chemin pour l'instant (cf. exploration précédente). Pour démarrer, **étape manuelle assumée** : export lancé à la main dans la session TSE habituelle, fichier déposé dans un dossier partagé. Ça découple ce problème non résolu du reste du pipeline, qui lui peut être automatisé dès maintenant. L'automatisation de cette étape spécifique reste un chantier à part, à reprendre plus tard.

### 2. Charger le CSV dans SQLite

Le loader Python existe déjà. Deux améliorations avant de l'automatiser :
- Le rendre **idempotent** (upsert par clé primaire plutôt que vider/recharger toute la base à chaque fois) pour ne pas perdre d'historique sur un export partiel.
- Lui faire produire un **rapport de diff** à chaque exécution (lignes ajoutées/modifiées, alerte si le nombre de tables/colonnes attendu ne correspond plus) — pour détecter un export cassé avant que le MCP serve des données fausses.

### 3. Orchestrer et planifier

Script qui enchaîne les étapes 1 (ou surveille le dépôt manuel du fichier) et 2, planifié via le **Planificateur de tâches Windows** — quotidien ou hebdomadaire selon le besoin de fraîcheur. Pas besoin d'un outil plus élaboré à ce stade.

### Ordre de construction recommandé

Étapes 2 et 3 en automatique tout de suite (peu de risque, en grande partie déjà fait). Étape 1 en automatique seulement sur la machine de test pour l'instant ; dépôt manuel du fichier de prod le temps de trouver une solution propre pour le RD Gateway.

### Cartographie des données

Repartir du dictionnaire de données déjà documenté (schéma partiel, ~93 tables côté export CSV existant — la base complète compterait ~149 tables côté comptabilité d'après l'exploration ODBC, abandonnée depuis, donc ce chiffre reste indicatif). Vérifier que l'export actuel couvre bien les tables nécessaires aux cas d'usage cibles (TAB_PLAN_COMPTABLE, ECRITURE) ; sinon élargir le périmètre d'export via les fonctions natives Charlemagne, jamais autrement.

Créer une **vue applicative restreinte** : plutôt que d'exposer les tables brutes, définir dès maintenant un petit nombre de requêtes/vues nommées correspondant à des besoins réels (ex. "solde d'une famille", "statut d'une facture", "liste des impayés du mois") — c'est ce qui deviendra la surface d'outils du MCP à l'étape suivante, et ça évite de donner à un LLM un accès SQL libre sur une base sensible. Le solde étant porté par un compte familial (classe 411), pas par élève, chaque tool doit le refléter explicitement (nom de famille en retour, pas juste un chiffre attribué à un enfant précis).

## Phase 2 — Définir la surface d'outils du MCP

Un MCP, c'est un ensemble de fonctions nommées et typées (les "tools") qu'un agent peut appeler — pas un accès SQL générique. Lister concrètement, à partir de tes cas d'usage réels :

- Quelles questions veux-tu pouvoir poser à l'agent ? (ex. "quel est le solde de telle famille", "quelles factures sont en retard de plus de 30 jours", "évolution des effectifs par niveau")
- Pour chacune, quelle(s) table(s)/jointure(s) de la base SQLite consolidée ça mobilise, et quels filtres de sécurité s'appliquent (un utilisateur ne doit voir que ce qu'il a le droit de voir).
- Décider explicitement ce qui reste **hors périmètre** au démarrage (ex. rien sur la santé/infirmerie, rien de nominatif exportable en masse).

Ce découpage en tools nommés, plutôt qu'un accès SQL libre, est aussi ce qui rend l'outil auditable et donc défendable si un jour il faut expliquer à la direction ou à la CNIL ce que l'IA peut voir.

## Phase 3 — Implémenter le serveur MCP (local, transport stdio)

- Choix techno : SDK officiel MCP en Python (cohérent avec `sqlite3`/le loader existant) ou en TypeScript/Node. Python reste probablement le plus direct ici.
- Démarrer en **stdio local** — c'est le mode le plus simple, utilisable immédiatement avec Claude Desktop ou Claude Code sur la machine de test, sans se soucier d'authentification réseau.
- Chaque tool = une fonction Python qui exécute une requête paramétrée sur la base SQLite (jamais de concaténation de texte libre venant du modèle dans du SQL) et retourne un résultat structuré et minimal.

## Phase 4 — Tester avec Claude

- Brancher le serveur en local sur Claude Desktop (ou Claude Code) via sa configuration MCP.
- Faire tourner tes cas d'usage réels de la Phase 2, ajuster les descriptions d'outils (c'est souvent là que se joue la qualité des réponses — un LLM choisit un tool sur la base de sa description).
- Boucle itérative : cas d'usage → ajustement du tool → retest.

## Phase 5 — Durcissement avant toute diffusion

- Authentification et autorisation par utilisateur (pas de compte partagé unique).
- Journalisation de chaque appel (qui a demandé quoi, quand) — indispensable pour la traçabilité RGPD.
- Limitation de débit et quotas.
- Revue explicite : est-ce que chaque tool expose bien le minimum nécessaire ?

## Phase 6 — Passer en serveur MCP distant (HTTP + auth)

Le mode stdio local ne fonctionne que pour Claude Desktop/Code sur la même machine. Pour que **ChatGPT, Gemini et Copilot 365** puissent s'y connecter, il faut un serveur MCP accessible en réseau, avec le transport HTTP (streamable HTTP / SSE selon la spec) et une authentification OAuth2 — c'est le format que les quatre plateformes attendent aujourd'hui pour un connecteur tiers.

Ça implique un hébergement (ta machine de test ne suffira pas pour un usage en production — il faudra soit un petit serveur dédié, soit un hébergement cloud, en gardant en tête la question RGPD de la localisation des données).

## Phase 7 — Spécificités par plateforme

Bonne nouvelle : les quatre supportent maintenant officiellement les serveurs MCP externes (ce n'était pas vrai il y a un an). Mais l'intégration diffère :

- **Claude** : connecteur MCP configurable au niveau utilisateur (Settings), le plus simple des quatre.
- **ChatGPT** : via son "Developer Mode" / connecteurs personnalisés — accès utilisateur, mais certaines fonctionnalités restent en évolution.
- **Gemini** : le support MCP est côté "Gemini Enterprise" (Google Cloud), plutôt orienté admin d'organisation que compte personnel.
- **Copilot 365** : via Copilot Studio, connecteur géré par un administrateur Microsoft 365 — pas un ajout self-service pour un utilisateur final.

Concrètement, ça veut dire que même une fois le serveur prêt, l'intégrer à Gemini ou Copilot 365 pour "d'autres utilisateurs" dépendra de l'administrateur informatique de chaque établissement, pas seulement de toi.

## Phase 8 — Diffusion à d'autres utilisateurs (si tu vas jusque-là)

- Chaque établissement a sa propre base Charlemagne : l'outil doit être pensé multi-instance dès le départ (chaque utilisateur configure sa propre connexion), jamais une base centrale partagée.
- Pilote interne dans l'établissement sur plusieurs semaines avant toute idée de diffusion externe.
- Revenir sur les points de la Phase 0 (Aplim, RGPD) avec le recul de l'usage réel avant d'ouvrir à qui que ce soit d'autre.

---

## Par où commencer concrètement

La prochaine étape utile et à faible risque : Phase 1, étapes 2 et 3 — fiabiliser (idempotence, rapport de diff) et planifier le pipeline CSV → SQLite qui existe déjà, en te basant sur un export manuel déposé dans un dossier partagé pour l'instant. Une fois ce pipeline fiable et automatique tourne, on peut écrire les premiers tools MCP dessus et tester avec Claude dans la foulée — sans attendre d'avoir résolu l'automatisation de l'export lui-même.

Dis-moi si tu veux qu'on attaque ça maintenant, ou si tu préfères d'abord qu'on affine la liste des cas d'usage (Phase 2) pendant que le pipeline se stabilise en parallèle.
