---
name: charlemagne-affectation-photos
description: Préparer un dossier de photos élèves/adultes pour l'affectation automatique Charlemagne et guider pas à pas la session RDP : dépôt en ZIP dans Downloads, RAZ, copie, affectation, contrôle, envoi et vérification EcoleDirecte.
---

# Affectation des photos dans Charlemagne

> Skill générique livrée avec le connecteur. Adaptez les chemins, le compte utilisé pour la vérification EcoleDirecte et le rangement des photos à votre établissement.

À utiliser quand l'utilisateur veut charger des photos d'élèves ou d'adultes dans Charlemagne (Administratif › Outils › Affectation des photos › Élèves – Adultes), qu'elles viennent de maclasse.photo (outil MCP `maclasse_preparer_photos`) ou d'un autre lot (clé du photographe, dossier en vrac). La skill prépare le dossier et accompagne l'utilisateur dans la session Charlemagne ; elle ne lance jamais elle-même l'affectation, la RAZ ni le transfert EcoleDirecte.

## Contrat Charlemagne (aide Aplim « AFFECTATION DES PHOTOS : Affecter les photos des élèves et des adultes » et « PHOTO : Comment affecter des photos sur EcoleDirecte ? »)

- Fichiers **.jpg uniquement**, **≤ 100 Ko**, résolution conseillée 480×640 (400×533 convient). Pas de données d'orientation EXIF (photos à l'envers sinon) : livrer des JPEG réencodés sans métadonnées.
- Nom de fichier : **`NOM Prénom`** exactement comme la fiche (casse respectée, **sans particule** : « DE LA TOUR Paul » → `TOUR Paul.jpg`) **ou** l'**identifiant logiciel** (IDELEVE élève, IDPERSONNEL adulte : `672.jpg`). Préférer l'identifiant : aucune ambiguïté d'homonyme, de particule ou d'accent ; joindre un CSV de contrôle (IDELEVE ; nom ; prénom ; classe ; fichier ; statut) pour la lecture humaine. L'identifiant Charlemagne est aussi l'`id` des comptes élèves EcoleDirecte.
- Une photo mal nommée écrase la mauvaise fiche : jamais d'appariement deviné.
- **Session RDP (Charlemagne Cloud)** : seul `~/Downloads` du poste est visible, sous `\\tsclient\Downloads`. **Livrer un ZIP** (`photos_<lot>.zip`) dans `~/Downloads/charlemagne_auto/` en plus du dossier : la copie fichier par fichier depuis `\\tsclient` est très lente et le bouton de copie Charlemagne pointé directement sur le dossier redirigé peut bloquer Charlemagne. Dans la session : copier le ZIP sur le disque local (Bureau ou `%LOCALAPPDATA%`), l'extraire là, puis pointer le bouton de copie sur ce dossier local. Photos seules dans le dossier (CSV de contrôle, LISEZMOI et exclus à côté, pas dedans). Rien ne s'installe côté serveur.
- Après la copie et l'affectation, Charlemagne range les photos dans `T:\Photos\Eleves\<établissement>\<année>\` (ex. `2026-2027\`) et renseigne `COM_ELEVES.EL_PHOTO` avec le nom du fichier affecté (`<IDELEVE>.jpg` pour un lot nommé par identifiant) : l'export CSV suffit pour compter les fiches avec photo et lister les élèves présents qui n'en ont pas.
- Les photos ne remontent pas seules sur EcoleDirecte : transfert manuel depuis Charlemagne Outils › EcoleDirecte (case « À intégrer au prochain envoi », flèche grise) ou Administratif › EcoleDirecte › Transfert vers EcoleDirecte ; si les espaces familles montrent encore d'anciennes photos, vider le cache du navigateur.
- La RAZ ne supprime aucune photo du serveur : elle casse seulement le lien photo ↔ fiche.

## Déroulé

1. **Source et cible** : demander le dossier source, élèves et/ou adultes, et confirmer la convention (identifiant par défaut). Lot maclasse.photo : partir de `charlemagne_ideleve/` produit par `maclasse_preparer_photos` (déjà nommé par IDELEVE, optimisé, silhouettes écartées) ; lot arbitraire : rapprocher chaque photo via l'outil MCP Charlemagne `liste_eleves` (IDELEVE, nom, prénom, classe) ou `liste_personnels` (IDPERSONNEL, particule), sinon `COM_ELEVES` / `COM_PERSONNELS` de la base consolidée ; cas ambigus listés pour arbitrage, jamais tranchés seul.
2. **Contrôle du lot** (shell du poste, ImageMagick ou Pillow) : extension .jpg, poids ≤ 100 Ko (réencoder `-strip -quality 92→60` sinon), pas d'EXIF, **silhouettes/pictogrammes « pas de photo »** (image à quelques dizaines de couleurs) à écarter dans un dossier `_exclus`, doublons d'identifiant. Compter : fichiers livrés = élèves appariés − exclus.
3. **Dépôt** : copier le dossier dans `~/Downloads/charlemagne_auto/photos_<lot>/` et le zipper en `photos_<lot>.zip` (accès au dossier Downloads demandé à l'utilisateur), écrire à côté `photos_<lot>_controle.csv` et `photos_<lot>_LISEZMOI.txt` (ASCII, étapes ci-dessous). Vérifier avec `COM_ELEVES.EL_PHOTO` combien de fiches ont déjà une photo (vide = aucune).
4. **Guider la session Charlemagne**, étape par étape, en attendant le retour de l'utilisateur à chaque écran :
   1. Copier `\\tsclient\Downloads\charlemagne_auto\photos_<lot>.zip` sur le disque local de la session et l'extraire.
   2. Administratif › Outils › Affectation des photos › Élèves – Adultes.
   3. RAZ des photos (facultatif ; utile avant un nouveau millésime ou s'il existe des homonymes).
   4. Bouton de copie des photos → dossier local extrait → « Sélectionner un dossier » → Oui → OK (copie dans le répertoire photos de la base).
   5. Affectation automatique.
   6. Contrôle : ouvrir 2 ou 3 fiches (dont un élève à particule et un homonyme s'il y en a), photo à l'endroit, bon enfant ; relancer un export CSV de la base puis `comparer_exports` (MCP Charlemagne : autant de fiches `EL_PHOTO` modifiées que de photos livrées) et lister les élèves **présents** (sans date de sortie, avec classe) dont `EL_PHOTO` reste vide : absents à la prise de vue, arrivées récentes, silhouettes écartées.
   7. EcoleDirecte : Charlemagne Outils › EcoleDirecte → bonne année scolaire → cocher « À intégrer au prochain envoi » → flèche grise. Éviter le créneau de synchronisation automatique d'Aplim.
5. **Vérifier dans EcoleDirecte** (connecteurs MCP) : d'abord `journal_transferts_ecoledirecte` (MCP Charlemagne) — le transfert qui suit l'affectation doit porter « N photos envoyées - \\<serveur Aplim>\<UAI>$\Photos\Eleves\… » avec N = photos affectées ; les transferts suivants affichent « Sans - Dernier envoi le JJ/MM/AAAA » (normal : les photos ne repartent que si elles changent). Ensuite `ed_admin_synchros_etat` (les six modules à l'heure du transfert, « déroulée correctement ») ; puis `ed_perso_classe_eleves(id_classe, include_sensitive_fields=True)` d'un compte personnel qui voit les classes, sur 2 ou 3 classes : le champ `photo` doit être une URL `//doc1.ecoledirecte.com/PhotoEleves/…` pour chaque élève livré et vide pour les exclus/absents (le champ `photo` de `ed_admin_eleves_search` reste vide : pas probant). Les URL ne sont pas lisibles sans session (404 en direct) ; le contrôle visuel se fait sur un espace famille ou enseignant, cache vidé si besoin.
6. **Rapport** : livrés / exclus / sans photo / à arbitrer, résultat de la vérification EcoleDirecte, et ce qui reste à faire (adultes, absents à photographier, photos de classe : en général payantes auprès du photographe si l'école les veut sans filigrane).

Une sauvegarde du partage faite juste après peut compter des fichiers « disparus » côté serveur : ce sont en général les fichiers temporaires de réplication EcoleDirecte, pas des photos.

## Vigilance données

Photos nominatives d'élèves mineurs et d'adultes : pas de photos ni de noms réels dans des exemples ou du code versionné, dossier livré uniquement à l'utilisateur. Les métadonnées (EXIF, GPS) sont retirées avant dépôt. Aucune action dans Charlemagne n'est déclenchée par Claude.
