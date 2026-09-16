# Démarrer avec Claude Code pour le projet MCP Charlemagne

*Note de prudence avant de commencer : les détails de tarification et les noms exacts des commandes/flags CLI ci-dessous évoluent vite. Vérifie le plan/prix réel dans les paramètres de ton compte sur claude.ai, et une fois Claude Code installé, confirme la syntaxe exacte des commandes avec `claude --help` plutôt que de copier-coller aveuglément — le principe de chaque mécanisme (CLAUDE.md, hooks, subagents, skills, mode headless) est solide, les détails syntaxiques peuvent avoir légèrement changé.*

---

## 1. Cowork vs Claude Code

Ce sont deux produits distincts qui partagent le même moteur d'agent :
- **Cowork** (ce que tu utilises actuellement) : automatisation de tâches, gestion de fichiers, orchestration multi-outils depuis une interface desktop/cloud.
- **Claude Code** : outil en ligne de commande pensé pour le développement — accès terminal complet, Git, boucles de test/itération, hooks, subagents.

Même compte Anthropic pour les deux ; ce sont des sessions séparées (le contexte de nos conversations Cowork ne se transfère pas automatiquement dans Claude Code).

**Accès** : Claude Code nécessite un abonnement payant (Pro au minimum, ou Max/Team/API selon ton usage). Vérifie ton plan actuel dans les paramètres de ton compte sur claude.ai — si tu es déjà sur un plan payant qui inclut Cowork, Claude Code est probablement inclus aussi ou accessible en complément léger.

**Installation sur Mac** :
```bash
curl -fsSL https://claude.ai/install.sh | bash
claude --version
claude
```
À la première exécution, connexion avec ton compte Anthropic habituel.

---

## 2. CLAUDE.md — la mémoire de projet

Un fichier `CLAUDE.md` à la racine du dépôt, lu automatiquement à chaque session. Garde-le court et actionnable — les règles qui, si elles sont oubliées, coûtent cher :

```markdown
# MCP Charlemagne Server (HFSQL/ODBC)

## Stack
- Python 3.10+, SDK MCP officiel, pyodbc (driver HFSQL PC Soft)
- Lecture seule uniquement — aucune requête INSERT/UPDATE/DELETE

## Règles non négociables
- Jamais de concaténation de chaînes SQL — requêtes paramétrées pyodbc uniquement
- Jamais d'identifiants en dur dans le code — variables d'environnement uniquement
  (CHARLEMAGNE_DSN, CHARLEMAGNE_USER, CHARLEMAGNE_PASSWORD)
- Timeout obligatoire sur chaque connexion pyodbc
- Chaque nouvel outil MCP = une fonction + un test associé, jamais l'un sans l'autre

## Structure
charlemagne-mcp/
├── mcp_server.py
├── tools/          # un fichier par domaine fonctionnel
├── db/             # connexion HFSQL, pooling
├── tests/
└── schema-dictionary.md   # référence des 93 tables

## Commandes
pytest -v                  # tests
ruff check . && ruff format .   # lint
python mcp_server.py       # lancer le serveur (stdio)
```

Mets-le à jour à chaque fois que tu découvres une subtilité HFSQL (ex. une table sans clé primaire propre, un encodage particulier) — c'est ce genre de détail qui évite à Claude Code de retomber dans la même erreur.

---

## 3. Subagents utiles pour ce projet

Trois rôles séparés, chacun avec un contexte et un accès limités à ce dont il a besoin — dans `.claude/agents/` :

- **schema-explorer** : lit `schema-dictionary.md`, aide à traduire un besoin métier en requête/jointure correcte sur les 93 tables. Outils en lecture seule (Read, Grep) — pas d'écriture.
- **test-runner** : lance `pytest`, rapporte les échecs, vérifie qu'un nouvel outil se charge correctement. Accès Bash restreint aux commandes de test.
- **security-auditor** : relit tout changement touchant `tools/` ou `db/` pour vérifier l'absence d'injection SQL, de credentials en dur, de fuite dans les logs, et que le read-only est bien respecté.

Le principe qui compte : le security-auditor tourne **systématiquement** avant qu'un nouvel outil touchant la base soit considéré comme terminé — vu la sensibilité des données (élèves mineurs, données financières), ça vaut la peine d'en faire une étape obligatoire du workflow plutôt qu'une option.

---

## 4. Hooks

Un hook peut relancer automatiquement lint + tests après chaque édition de fichier dans `tools/` ou `db/`, pour donner un feedback immédiat à Claude Code sans attendre que tu le demandes. Se configure via `/hooks` dans une session Claude Code, ou directement dans `.claude/settings.json`. Vérifie la syntaxe exacte attendue avec `/hooks` une fois Claude Code installé — le format peut différer légèrement de ce qu'on imagine à l'avance.

---

## 5. Un "skill" projet : ajouter un outil MCP

Un skill réutilisable (`.claude/skills/add-mcp-tool/`) qui documente la recette standard : écrire la fonction paramétrée, ajouter le test, lancer pytest, documenter dans `schema-dictionary.md`. L'intérêt : chaque nouvel outil suit exactement le même moule, ce qui garde le code homogène même après des dizaines d'itérations.

---

## 6. Automatisation "headless" (mode non interactif)

Claude Code peut tourner sans interface interactive (`claude -p "..."`), ce qui permet des boucles scriptées : par exemple un script qui, pour chaque table restante à couvrir, demande à Claude Code d'implémenter l'outil correspondant, lance les tests, et ne passe à la suivante que si ça passe. C'est la bonne approche une fois que le patron (Section 5) est stable et validé sur 2-3 outils faits à la main — pas avant, sinon tu scales une erreur de conception 93 fois.

De la même façon, une étape de validation automatique (lint + tests + audit sécurité) peut tourner en CI à chaque commit, pour ne jamais fusionner un outil qui n'a pas été vérifié par le security-auditor.

---

## Par où commencer concrètement

1. Installer Claude Code, vérifier l'accès.
2. Écrire le `CLAUDE.md` initial (section 2) dans le dépôt existant.
3. Faire à la main 2-3 outils MCP avec Claude Code en session interactive, pour caler le patron avant d'automatiser.
4. Une fois le patron stable, définir les subagents (section 3) et le skill "add-mcp-tool" (section 5).
5. Seulement à ce stade, envisager la boucle headless (section 6) pour couvrir le reste du schéma plus vite.
