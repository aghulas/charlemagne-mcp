# Plan multi-plateforme — Charlemagne MCP

## Où en est-on

Le serveur tourne aujourd'hui uniquement en **stdio local** (`server.run(transport="stdio")`
dans `mcp_server.py`), lancé par Claude Desktop/Claude Code sur le Mac. C'est le mode le
plus sûr : la base ne quitte jamais la machine, aucune surface réseau.

Deux besoins distincts identifiés (8 sept. 2026) :

1. **Copilot 365**, déjà utilisé par le personnel de l'école — besoin réel de production,
   sécurité garantie par le tenant Microsoft de l'établissement.
2. **ChatGPT / Gemini / OpenClaw** — pour permettre à *d'autres écoles* de réutiliser le
   projet sur la plateforme de leur choix. Chaque école déploierait sa **propre instance**,
   pointée sur ses **propres données** : ce n'est pas un service partagé à opérer, mais un
   projet à bien documenter/templatiser (voir tâche séparée "guide de déploiement
   multi-plateforme").

Ce document couvre le point 1 : comment exposer Charlemagne-MCP à Copilot 365 en toute
sécurité, avec le tenant Microsoft de l'école.

## Ce qui a été validé (POC, données 100% synthétiques, hors du dossier réel)

Le SDK Python `mcp==2.2.0` déjà utilisé par le projet supporte **nativement** un transport
HTTP distant, sans changement d'architecture :

```python
server.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

`MCPServer` accepte aussi un `token_verifier` (protocole `TokenVerifier.verify_token`) et
des `AuthSettings` : le serveur devient alors un vrai serveur de ressources OAuth — il
publie automatiquement les métadonnées standard
(`/.well-known/oauth-protected-resource`) et rejette avec un `401` toute requête sans jeton
Bearer valide. Testé de bout en bout dans le sandbox : requête sans jeton → `401`,
requête avec jeton valide → poignée de main MCP puis appel d'outil (`liste_eleves`)
fonctionnel.

Conséquence concrète : **passer en HTTP distant est un changement de quelques lignes**
dans `mcp_server.py` (transport + un `TokenVerifier` qui valide un vrai jeton Entra ID au
lieu du stub de test), pas une réécriture.

**Mise à jour (16 sept. 2026) : fait.** `mcp_server.py` supporte désormais
`--transport {stdio,streamable-http}`, et la vérification de jeton Entra ID ne vit plus
dans ce dépôt : elle a été extraite dans un module partagé,
[`mcp-entra-auth`](https://github.com/aghulas/mcp-entra-auth) (dépôt privé, même compte
GitHub), réutilisé à l'identique par `ecoledirecte-admin-mcp` et
`edumoov-mcp-prototype` — un seul endroit à corriger/auditer pour les 3 projets, plutôt
que 3 copies divergentes du même code de sécurité. Chaque serveur garde son propre scope
Entra ID (`Charlemagne.Read` ici), ce qui garantit qu'un jeton valide pour un projet
n'est jamais accepté par un autre, même en partageant le module (voir les tests
`test_deux_serveurs_scopes_differents_sont_etanches` du dépôt partagé).

## Architecture recommandée avec le tenant Microsoft de l'école

Deux façons de faire, toutes deux officiellement documentées par Microsoft :

**A. Azure API Management (APIM) devant le serveur** — APIM valide le jeton Entra ID via
sa policy `validate-azure-ad-token` avant de transmettre la requête au serveur MCP.
Recommandé si l'école a déjà (ou prévoit) une passerelle API partagée pour plusieurs
services.

**B. Le serveur MCP valide lui-même le jeton** (ce qui a été testé dans le POC) — pas de
brique Azure supplémentaire, juste l'App Service/Container App qui héberge le process
Python. Plus simple, moins cher, aussi sûr côté sécurité (même mécanisme de jeton Entra
ID, juste vérifié à un autre endroit).

**Recommandation : partir sur B**, plus simple à opérer pour un seul service, et c'est
exactement ce que le POC a validé. On pourra migrer vers A plus tard si l'école
centralise plusieurs API internes derrière une passerelle commune.

### Ce qu'il faut créer dans Entra ID (2 inscriptions d'application)

1. **Application "ressource" (le serveur Charlemagne-MCP)** — expose une API avec un
   Application ID URI et un scope personnalisé (ex. `Charlemagne.Read`). C'est l'audience
   que le `TokenVerifier` du serveur vérifiera dans chaque jeton reçu.
2. **Application "client" (Copilot Studio)** — génère un secret client, obtient une
   permission déléguée sur le scope `Charlemagne.Read` de l'application ressource,
   consentement admin donné une fois par un administrateur du tenant.

Optionnel mais recommandé vu la sensibilité des données : restreindre l'accès à un groupe
de sécurité Entra ID (ex. "Personnel autorisé Charlemagne") et vérifier l'appartenance à
ce groupe dans le `TokenVerifier`, en plus de la validation du jeton — pas seulement
"authentifié sur le tenant" mais "autorisé explicitement".

### Côté serveur (Azure)

- Hébergement : Azure App Service ou Container Apps, HTTPS géré automatiquement par
  Azure (pas de certificat à gérer).
- `TokenVerifier` réel : fourni par le module partagé `mcp-entra-auth`
  (`entra_auth_kwargs(required_scope="Charlemagne.Read")` dans `mcp_server.py`) — valide
  la signature du jeton via le JWKS du tenant, vérifie `aud` = Application ID URI,
  l'issuer, l'expiration, et optionnellement le claim `groups`. Variables d'environnement
  à définir sur l'hébergement Azure (transport `streamable-http` uniquement) :
  `MCP_ENTRA_TENANT_ID`, `MCP_ENTRA_APP_ID_URI` (obligatoires), `MCP_ENTRA_ALLOWED_GROUP_ID`,
  `MCP_ENTRA_PUBLIC_URL` (optionnelles). Détail complet dans le README du dépôt partagé.
- Périmètre exposé : ne pas dupliquer tous les tools stdio tels quels. Recommandé de
  commencer volontairement restreint (ex. `liste_eleves` seul, en fonction des cas d'usage
  réels prévus pour les agents Copilot Studio du personnel), et d'élargir ensuite plutôt
  que l'inverse — c'est plus facile d'ajouter un accès que d'en retirer un une fois pris
  en habitude.

### Côté données

Le serveur Azure a besoin d'une base à jour, en continu, sans dépendre du Mac de [prénom].
Ça rejoint le test déjà prévu par ailleurs : export CSV planifié vers un SharePoint
accessible sans connexion à l'instance cloud. Ce même export peut alimenter un job
planifié côté Azure (Function App en timer trigger, par ex.) qui relit les CSV depuis
SharePoint et relance `loader/load_charlemagne.py` pour régénérer la base consolidée
utilisée par le serveur distant — sans jamais transiter par le Mac.

### Côté Copilot Studio

1. Créer l'outil MCP dans Copilot Studio, authentification "OAuth 2.0" (configuration
   manuelle).
2. Renseigner les URLs OAuth (autorisation/jeton du tenant Entra ID), le client ID/secret
   de l'application "client", et le scope `Charlemagne.Read`.
3. Configurer l'URI de redirection dans Entra ID avec l'URL fournie par Copilot Studio.
4. Tester la connexion — Copilot Studio gère alors le flux OAuth pour chaque utilisateur
   du personnel qui utilise l'agent.

## Prochaine étape technique

Le transport HTTP + `TokenVerifier` Entra ID sont portés et testés côté code (stdio
intact pour Claude Desktop, `--transport streamable-http` pour Copilot 365). Reste à
faire côté [prénom] dans le portail Entra ID (inscriptions d'application, groupe de sécurité,
consentement admin) avant de pouvoir tester en bout en bout avec un vrai tenant, puis
choisir et provisionner l'hébergement Azure (App Service ou Container Apps).
