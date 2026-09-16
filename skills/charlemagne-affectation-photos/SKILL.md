---
name: charlemagne-affectation-photos
description: "Use when preparing a folder of student/staff photos for Charlemagne's automatic photo assignment (l'établissement) via Administratif > Outils > Affectation des photos > Élèves – Adultes."
---

# Préparation des photos pour l'affectation automatique Charlemagne

Cette skill prépare un dossier de photos (élèves et/ou adultes) reçu dans un nommage arbitraire (numérotation photographe, prénom seul, orthographe approximative...) pour qu'il soit directement utilisable par la fonction native Charlemagne d'affectation automatique des photos. La skill ne fait jamais l'affectation elle-même dans Charlemagne — elle livre un dossier renommé et un rapport, l'utilisateur lance ensuite le traitement natif.

## Contrat attendu par Charlemagne (documenté par Aplim, aide.aplim.mayday.cx)

- Fichiers **.jpg uniquement**, idéalement ≤ 100 Ko, résolution conseillée 480x640.
- Le nom de fichier (sans extension) doit être **soit** :
  - `NOM Prénom` exactement comme sur la fiche Charlemagne (respect de la casse), **sans la particule** (ex. l'élève/adulte "DE LA TOUR Paul" → fichier `TOUR Paul.jpg`, jamais `DE LA TOUR Paul.jpg`) ;
  - **soit** l'identifiant logiciel Charlemagne (IDELEVE pour un élève, IDPERSONNEL pour un adulte), ex. `672.jpg`.
- Côté Charlemagne, le processus reste en deux temps, à rappeler à l'utilisateur mais jamais à faire soi-même : RAZ des photos (optionnel, casse juste le lien existant, ne supprime rien sur le serveur) puis Affectation automatique en pointant vers le dossier préparé. Les photos des élèves ne remontent pas automatiquement sur EcoleDirecte : un envoi manuel supplémentaire depuis Charlemagne Outils (case "À intégrer au prochain envoi") est nécessaire si l'utilisateur veut les y voir.

## Déroulé

1. Demander à l'utilisateur : le dossier source des photos, s'il s'agit d'élèves et/ou d'adultes (enseignants/personnels), et quelle convention de nommage cible il préfère (nom, ou identifiant — l'identifiant évite toute ambiguïté d'homonymie mais est moins lisible pour une vérification humaine).
2. Résoudre chaque photo vers le bon élève/adulte de façon fiable plutôt que par déduction :
   - Élèves : utiliser l'outil MCP `liste_eleves` (IDELEVE, nom, prénom, classe) si le serveur MCP Charlemagne est disponible dans la session ; sinon interroger directement `COM_ELEVES` dans la base SQLite consolidée si elle est accessible.
   - Adultes : même logique avec l'outil MCP `liste_personnels` (IDPERSONNEL, nom, prénom, particule) ou la table `COM_PERSONNELS`.
   - Ne jamais deviner un appariement incertain (nom approchant, homonymes, plusieurs candidats) : lister ces cas séparément dans le rapport final pour arbitrage par l'utilisateur, plutôt que de choisir à sa place — une photo mal affectée écrase la mauvaise fiche.
3. Renommer les fichiers dans une copie du dossier (jamais en écrasant les originaux sans un dossier de sortie séparé, sauf si l'utilisateur le demande explicitement), en respectant le format choisi à l'étape 1 (nom sans particule, ou identifiant).
4. Signaler dans le rapport : fichiers non-.jpg ou hors gabarit de poids/résolution recommandé, photos sans correspondance trouvée, correspondances ambiguës (plusieurs élèves/adultes possibles), et élèves/adultes de la liste qui n'ont pas de photo dans le lot fourni.
5. Rappeler explicitement à l'utilisateur les étapes Charlemagne natives à faire ensuite (RAZ optionnelle, puis Affectation automatique sur le dossier livré, puis envoi manuel vers EcoleDirecte si besoin) — cette skill ne les déclenche jamais elle-même.

## Vigilance données

Ces photos identifient nominativement des élèves mineurs et des adultes. Même discipline que le reste du projet Charlemagne : pas de photos ni de noms réels dans des exemples ou du code versionné, dossier livré uniquement à l'utilisateur qui en a fait la demande.