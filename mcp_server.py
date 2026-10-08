"""Serveur MCP Charlemagne - transport stdio (Claude Desktop) ou streamable-http
(Copilot 365 / Copilot Studio, via Entra ID).

Chaque tool expose une fonction parametree sur la base SQLite consolidee
(jamais d'acces SQL libre depuis le modele). Lecture seule.

Usage :
  python3 mcp_server.py                                   # stdio (defaut, Claude Desktop)
  python3 mcp_server.py --transport streamable-http --port 8000
      # HTTP distant avec authentification Entra ID (voir docs/plan-multiplatform.md
      # pour les variables d'environnement requises : MCP_ENTRA_TENANT_ID,
      # MCP_ENTRA_APP_ID_URI, MCP_ENTRA_ALLOWED_GROUP_ID)
      # L'authentification elle-meme vient du module partage mcp-entra-auth
      # (github.com/aghulas/mcp-entra-auth), reutilise par ecoledirecte-admin-mcp
      # et edumoov-mcp-prototype - un seul endroit a corriger si besoin.
"""

import argparse
import sqlite3

from mcp.server.mcpserver import MCPServer

from db.connection import get_connection
from db.connection_compta import get_compta_connection
from tools import (
    audit_facturation,
    calendrier,
    comparaison,
    comptabilite,
    eleves,
    facturation,
    famille,
    historique_mails,
    journal_ecoledirecte,
    modifications,
    personnels,
    responsables,
    suivi_facturation,
    vie_scolaire,
)


def _avec_comptabilite(res: dict, **kw) -> dict:
    """Ajoute la situation comptable des responsables si la base FEC existe, sans jamais faire echouer l'outil."""
    try:
        cc = get_compta_connection()
    except FileNotFoundError:
        res["comptabilite"] = {"disponible": False,
                               "message": "Base comptable absente (aucun FEC charge) : situation comptable non jointe."}
        return res
    try:
        comptabilite.enrichir_responsables(cc, res, **kw)
    except (ValueError, sqlite3.Error) as exc:
        res["comptabilite"] = {"disponible": False, "message": f"Situation comptable indisponible : {exc}"}
    finally:
        cc.close()
    return res

INSTRUCTIONS = (
    "Acces en lecture seule aux donnees de gestion Charlemagne, "
    "a partir d'une base SQLite consolidee depuis les exports natifs Charlemagne. "
    "Les donnees ne sont pas temps reel : elles datent du dernier export charge."
)

# Scope Entra ID propre a ce serveur - jamais partage avec ecoledirecte-admin-mcp /
# ecoledirecte-perso-mcp / edumoov-mcp, meme s'ils utilisent tous mcp-entra-auth.
REQUIRED_SCOPE = "Charlemagne.Read"


def build_server(transport: str) -> MCPServer:
    """Construit le serveur MCP. En streamable-http, active la verification de
    jeton Entra ID (jamais en stdio - Claude Desktop n'a pas besoin d'OAuth,
    le process est deja local et prive)."""
    if transport == "stdio":
        return MCPServer(name="charlemagne", instructions=INSTRUCTIONS)

    from mcp_entra_auth import entra_auth_kwargs

    return MCPServer(
        name="charlemagne",
        instructions=INSTRUCTIONS,
        **entra_auth_kwargs(required_scope=REQUIRED_SCOPE),
    )


def register_tools(server: MCPServer) -> None:
    @server.tool(
        description=(
            "Solde d'un eleve, ventile par responsable financier lie (un eleve peut avoir "
            "plusieurs responsables). Le solde est la somme des montants factures moins les "
            "montants credites pour ce responsable, tous evenements de facturation confondus. "
            "Ne renseigne PAS le statut d'une facture (payee/impayee) : cette donnee n'est pas "
            "encore fiable dans la base consolidee actuelle."
        )
    )
    def solde_eleve(id_eleve: str) -> dict:
        """Recupere le solde d'un eleve a partir de son identifiant Charlemagne (IDELEVE)."""
        conn = get_connection()
        try:
            return facturation.solde_eleve(conn, id_eleve)
        except ValueError as exc:
            return {"error": str(exc)}
        finally:
            conn.close()

    @server.tool(
        description=(
            "Liste des eleves (IDELEVE, nom, prenom, sexe, classe), filtrable par classe et par "
            "statut actif (par defaut : exclut les eleves sortis en cours d'annee sur l'export "
            "charge). Sert a retrouver l'IDELEVE fiable d'un eleve a partir de son nom - par "
            "exemple avant de preparer un fichier a importer dans Charlemagne - plutot que de "
            "deviner un appariement par nom sans verification. Ne couvre PAS les anciens eleves "
            "(table ADM_ANCIEN, identifiants dans un namespace separe, hors perimetre)."
        )
    )
    def liste_eleves(classe: str | None = None, actifs_seulement: bool = True) -> dict:
        """Liste les eleves (avec enseignant(s) de la classe et anciennete), filtrable par classe et statut."""
        conn = get_connection()
        try:
            resultats = eleves.liste_eleves(conn, classe=classe, actifs_seulement=actifs_seulement)
            return {
                "nb_eleves": len(resultats),
                "eleves": resultats,
                "note": (
                    "Base a jour a la date du dernier export Charlemagne charge, pas en temps "
                    "reel. Ne couvre pas les anciens eleves (ADM_ANCIEN, namespace d'ID separe)."
                ),
            }
        finally:
            conn.close()

    @server.tool(
        description=(
            "Liste des adultes (enseignants et personnels de l'etablissement) : IDPERSONNEL, "
            "nom, prenom, particule, type. Filtrable par statut actif (par defaut : exclut les "
            "adultes sortis). Sert a retrouver l'IDPERSONNEL fiable d'un adulte a partir de son "
            "nom - par exemple avant une affectation de photos ou un import externe - plutot que "
            "de deviner un appariement par nom sans verification. Ne couvre PAS les responsables "
            "(parents/tuteurs d'eleves, table COM_RESPONSABLES) - perimetre distinct."
        )
    )
    def liste_personnels(actifs_seulement: bool = True) -> dict:
        """Liste les adultes (enseignants/personnels), avec filtre optionnel par statut actif."""
        conn = get_connection()
        try:
            resultats = personnels.liste_personnels(conn, actifs_seulement=actifs_seulement)
            return {
                "nb_personnels": len(resultats),
                "personnels": resultats,
                "note": (
                    "Base a jour a la date du dernier export Charlemagne charge, pas en temps "
                    "reel. Ne couvre pas les responsables (COM_RESPONSABLES, perimetre distinct)."
                ),
            }
        finally:
            conn.close()

    @server.tool(
        description=(
            "Droits EcoleDirecte des adultes tels que parametres dans Charlemagne (fiche adulte, "
            "onglet EcoleDirecte) : coche 'Utilisateur EcoleDirecte', fonctions (Secretariat, "
            "Direction... - sans fonction, un personnel est invisible des familles dans la "
            "messagerie), etablissements coches, fonctionnalites autorisees/refusees, "
            "notifications actives/inactives (messages en attente, demandes de modification de "
            "coordonnees, demandes de modifications eleve...), points d'attention calcules, et "
            "options des profils utilisateurs Charlemagne (visualisation des mots de passe "
            "EcoleDirecte). Filtrable par IDPERSONNEL. Les enseignants heritent de leurs droits "
            "par leur categorie : ils ne sont renvoyes qu'en resume, sauf detail_enseignants=True "
            "ou IDPERSONNEL precis. Lecture seule, a la date du dernier export."
        )
    )
    def droits_ecoledirecte_personnels(id_personnel: str | None = None,
                                       actifs_seulement: bool = True,
                                       detail_enseignants: bool = False) -> dict:
        """Droits, fonctions et notifications EcoleDirecte des adultes."""
        conn = get_connection()
        try:
            res = personnels.droits_ecoledirecte(conn, id_personnel=id_personnel,
                                                 actifs_seulement=actifs_seulement,
                                                 detail_enseignants=detail_enseignants)
            res["note"] = (
                "Base a jour a la date du dernier export Charlemagne charge, pas en temps reel. "
                "Libelles des codes rapproches du support de formation Aplim (CED4 - Ecole Directe)."
            )
            return res
        except ValueError as exc:
            return {"error": str(exc)}
        finally:
            conn.close()


    @server.tool(
        description=(
            "Responsables (parents/tuteurs) des eleves, groupes par eleve : lien (pere/mere), "
            "civilite, nom, prenom, emails perso et pro, telephones, code postal et ville. "
            "Filtrable par eleve (IDELEVE) ou par classe. Un eleve peut avoir plusieurs "
            "responsables : ils sont tous retournes, via la table de liaison COM_LIENER. Sert "
            "notamment a controler la coherence des coordonnees familiales avec un autre outil. "
            "N'expose AUCUNE coordonnee bancaire ni parametre de facturation. Ne couvre PAS les "
            "enseignants et personnels (COM_PERSONNELS, voir liste_personnels)."
        )
    )
    def responsables_eleves(
        id_eleve: str | None = None,
        classe: str | None = None,
        actifs_seulement: bool = True,
    ) -> dict:
        """Responsables d'un eleve, d'une classe, ou de tous les eleves actifs."""
        conn = get_connection()
        try:
            resultats = responsables.responsables_eleves(
                conn, id_eleve=id_eleve, classe=classe, actifs_seulement=actifs_seulement
            )
            return {
                "nb_eleves": len(resultats),
                "nb_responsables": sum(len(e["responsables"]) for e in resultats),
                "eleves": resultats,
                "note": (
                    "Base a jour a la date du dernier export Charlemagne charge, pas en temps "
                    "reel. Un eleve sans lien dans COM_LIENER n'apparait pas."
                ),
            }
        finally:
            conn.close()


    @server.tool(
        description=(
            "Audit complet de la facturation des familles, sur la preparation en cours "
            "(validee=False) ou sur la derniere facturation validee (validee=True). Compare "
            "chaque ligne facturee aux donnees sources (jours de cantine, activites, "
            "informations complementaires, liens eleve-responsable) et aux regles tarifaires "
            "de l'etablissement (fichier CHARLEMAGNE_REGLES_FACTURATION) : perimetre, "
            "repartition entre payeurs, cantine/etude/garderie/activites, reductions fratrie "
            "(regle, justificatifs, cumul avec le personnel, payeur non responsable principal), "
            "remises, APEL, echeances, soldes reportes ; pour une facturation validee, "
            "numerotation et equilibre comptable. En cours d'annee, la facturation validee est le "
            "cumul de toutes les validations (initiale + factures complementaires) ; les lignes de "
            "regularisation et les lignes au prorata sont signalees en information. A lancer apres "
            "chaque nouvelle preparation, avant de valider. N'expose aucune donnee bancaire."
        )
    )
    def audit_de_facturation(validee: bool = False) -> dict:
        """Audit de la facturation (preparation ou facturation validee)."""
        conn = get_connection()
        try:
            return audit_facturation.audit_facturation(conn, audit_facturation.charger_regles(), validee=validee)
        except ValueError as exc:
            return {"error": str(exc)}
        finally:
            conn.close()

    @server.tool(
        description=(
            "Suivi de la facturation en cours d'annee : compare, eleve par eleve, le cumul deja "
            "facture (toutes validations : facturation initiale + factures complementaires) a ce que "
            "donnent les donnees sources actuelles (jours de cantine, regime, etude, garderie, "
            "activites, informations complementaires, fratrie et justificatifs, APEL) et propose les "
            "lignes a saisir en facture complementaire manuelle dans Charlemagne : code de ligne, "
            "quantite, prix plein et prix au prorata (tout mois commence est du, a partir de "
            "date_effet - AAAA-MM-JJ, aujourd'hui par defaut), libelle, quote-part de chaque payeur, "
            "sens (complement ou avoir). Couvre les forfaits modifies, les reductions (justificatifs "
            "tardifs), les nouveaux eleves (contribution de la classe + forfaits), les departs (avoir "
            "sur les mois suivant la sortie), l'APEL, la remise personnel absente, les lignes "
            "manuelles deja saisies dans Charlemagne et non validees (avec un controle), et les "
            "justificatifs recus dont l'information complementaire n'est pas encore saisie (a faire "
            "avant de facturer). id_eleve : un seul eleve. Lecture seule, aucune donnee bancaire."
        )
    )
    def regularisations_a_preparer(date_effet: str | None = None, id_eleve: str | None = None) -> dict:
        """Regularisations a preparer (facture complementaire / avoir) d'apres les donnees sources."""
        conn = get_connection()
        try:
            return suivi_facturation.regularisations_a_preparer(
                conn, audit_facturation.charger_regles(), date_effet=date_effet, id_eleve=id_eleve)
        except ValueError as exc:
            return {"error": str(exc)}
        finally:
            conn.close()

    @server.tool(
        description=(
            "Suivi des echeanciers famille par famille apres la facturation : factures de l'annee "
            "(initiale, complementaires, avoirs : numero, date, montant, solde repris), echeances "
            "passees et a venir, reste a prelever, et alertes : echeancier incoherent (somme des "
            "echeances differente de facture + solde), mode de reglement modifie sur la fiche depuis "
            "la facture (echeancier a reactualiser), prelevement sans IBAN, echeances irregulieres, "
            "payeur ou repartition modifies depuis la facturation, enfant du payeur non facture. "
            "Sans id_responsable, ne detaille que les familles avec alerte ou plusieurs factures. "
            "Ne connait PAS le statut paye/impaye (aucun encaissement exporte). Aucune donnee bancaire."
        )
    )
    def suivi_echeanciers(id_responsable: str | None = None) -> dict:
        """Echeanciers, factures de l'annee et alertes de reglement par famille."""
        conn = get_connection()
        try:
            return suivi_facturation.suivi_echeanciers(conn, audit_facturation.charger_regles(),
                                                       id_responsable=id_responsable)
        except ValueError as exc:
            return {"error": str(exc)}
        finally:
            conn.close()

    @server.tool(
        description=(
            "Fiche famille complete en un appel, a partir d'un eleve (id_eleve = IDELEVE) ou d'un "
            "foyer (id_foyer = IDFOYER) : foyer (cotisation APEL Oui/Ext/Non), responsables (lien, "
            "responsable principal, payeur et pourcentage, mode de reglement, IBAN renseigne ou "
            "non, enfants a charge, quotients, informations complementaires - ex. Ext. scolarisee, "
            "Justificatif Fraterie), enfants (classe, regime, jours de cantine, activites, "
            "informations complementaires, remises), lignes facturees non nulles (preparation en "
            "cours, sinon cumul de toutes les factures validees de l'annee avec le detail par "
            "facture et les echeances ; validee=True/False pour forcer) avec le total par "
            "responsable, les lignes manuelles en attente de validation, et pieces a verser recues ou non. A utiliser pour verifier une "
            "famille apres une fiche forfaits, un certificat ou une facture APEL. Si un FEC est "
            "charge, chaque responsable porte aussi sa situation comptable (compte 411, solde, retard ou "
            "avance, echeances non couvertes, dernier reglement, impayes) ; detail : encaissements_famille. "
            "Lecture seule, aucune coordonnee bancaire (seulement renseigne/vide)."
        )
    )
    def fiche_famille(id_eleve: str | None = None, id_foyer: str | None = None,
                      validee: bool | None = None) -> dict:
        """Tout sur une famille : responsables, enfants, facturation, pieces recues."""
        conn = get_connection()
        try:
            res = famille.fiche_famille(conn, id_eleve=id_eleve, id_foyer=id_foyer, validee=validee)
        except ValueError as exc:
            return {"error": str(exc)}
        finally:
            conn.close()
        return _avec_comptabilite(res)

    @server.tool(
        description=(
            "Historique des mails envoyes depuis Charlemagne (messagerie Charlemagne, pas "
            "EcoleDirecte), du plus recent au plus ancien : date et heure, objet, module, "
            "utilisateur, nombre et type de destinataires, extrait du texte. Filtres : recherche "
            "(texte dans l'objet ou le corps, ex. '#LOGIN' pour les envois d'identifiants), "
            "destinataire (nom ou adresse partiels : a qui ce parent a-t-il ete ecrit ?), "
            "depuis/jusqu_a (AAAA-MM-JJ). id_histo : detail d'un envoi (corps complet en texte, "
            "tous les destinataires avec nom, adresse et type). Ne dit PAS si un mail a ete "
            "delivre, rejete ou bloque par la liste noire : ce statut n'est pas exporte."
        )
    )
    def historique_mails_charlemagne(recherche: str | None = None, destinataire: str | None = None,
                                     depuis: str | None = None, jusqu_a: str | None = None,
                                     id_histo: str | None = None, limite: int = 50) -> dict:
        """Mails envoyes depuis Charlemagne, filtrables, ou detail d'un envoi."""
        conn = get_connection()
        try:
            return historique_mails.historique_mails(conn, recherche=recherche, destinataire=destinataire,
                                                     depuis=depuis, jusqu_a=jusqu_a, id_histo=id_histo,
                                                     limite=limite)
        except ValueError as exc:
            return {"error": str(exc)}
        finally:
            conn.close()

    @server.tool(
        description=(
            "Journal des transferts Charlemagne -> EcoleDirecte (fichier 'EcoleDirecte Journal' du "
            "serveur, copie locale CHARLEMAGNE_JOURNAL_ED ; pas dans l'export CSV) : pour chaque "
            "transfert, date et heure, mode (automatique de nuit ou manuel), poste, etat des "
            "replications par module, erreurs, et nombre de documents PDF envoyes. "
            "publications_documents = transferts ayant publie des PDF dans l'espace Documents "
            "d'EcoleDirecte (circulaires, factures, documents a signer), ce qui ne notifie PAS les "
            "familles. Ni intitule ni destinataires : les lire avec ed_admin_documents_ecole "
            "(connecteur EcoleDirecte). Filtres depuis/jusqu_a (AAAA-MM-JJ), "
            "avec_documents_seulement."
        )
    )
    def journal_transferts_ecoledirecte(depuis: str | None = None, jusqu_a: str | None = None,
                                        avec_documents_seulement: bool = False,
                                        limite: int = 50) -> dict:
        """Transferts vers EcoleDirecte et documents PDF publies."""
        try:
            return journal_ecoledirecte.journal_transferts(depuis=depuis, jusqu_a=jusqu_a,
                                                           avec_documents_seulement=avec_documents_seulement,
                                                           limite=limite)
        except ValueError as exc:
            return {"error": str(exc)}

    @server.tool(
        description=(
            "Compare la base actuelle a un export precedent archive (par defaut le plus recent "
            "du dossier CHARLEMAGNE_ARCHIVES_DIR ; sinon indiquer le nom de fichier) : tables "
            "dont le volume change, parametrage de la facturation (formules, lignes, grilles de "
            "prix et de comptes, remises, regimes, quotients), fiches eleves/responsables/foyers "
            "modifiees, liens eleve-responsable (payeur, pourcentage, responsable principal), "
            "informations complementaires, et si la facturation a ete recalculee ou validee. "
            "A utiliser en premier a chaque nouvel export pour savoir ce qui a change. Les "
            "donnees bancaires ne sont jamais renvoyees (seulement renseigne/vide)."
        )
    )
    def comparer_exports(archive: str | None = None) -> dict:
        """Changements entre la base actuelle et une archive (la plus recente par defaut)."""
        archives = comparaison.lister_archives()
        if archive:
            choix = [a for a in archives if a.endswith(archive)]
            if not choix:
                return {"error": f"Archive {archive!r} introuvable.", "archives_disponibles": [a.rsplit('/', 1)[-1] for a in archives[-10:]]}
            chemin = choix[-1]
        elif archives:
            chemin = archives[-1]
        else:
            return {"error": "Aucune archive : definir CHARLEMAGNE_ARCHIVES_DIR."}
        conn = get_connection()
        try:
            prec = comparaison.ouvrir_archive(chemin)
        except ValueError as exc:
            conn.close()
            return {"error": str(exc)}
        try:
            res = comparaison.comparer_exports(conn, prec)
            res["archive_comparee"] = chemin.rsplit("/", 1)[-1]
            return res
        finally:
            conn.close(); prec.close()

    @server.tool(
        description=(
            "Fiches (eleve ou responsable) modifiees dans Charlemagne et pas encore envoyees vers "
            "EcoleDirecte (file de sortie COM_JOURNAL_MODIF, videe par la synchronisation) : fiche "
            "concernee, classe, utilisateur Charlemagne qui a modifie, date de modification, date "
            "d'envoi (vide = jamais envoye), statut, et motif probable quand la ligne est bloquee "
            "(eleve sorti, responsable sans eleve actif : hors perimetre de la synchro). Par defaut "
            "uniquement le statut 'En attente' ; statut=None pour tout le journal. Ce n'est PAS la "
            "liste des demandes des familles en attente de validation (console EcoleDirecte). "
            "Lecture seule, a la date du dernier export."
        )
    )
    def modifications_ecoledirecte_en_attente(statut: str | None = "En attente") -> dict:
        """Fiches modifiees dans Charlemagne en attente d'envoi vers EcoleDirecte."""
        conn = get_connection()
        try:
            resultats = modifications.modifications_ecoledirecte_en_attente(conn, statut=statut)
            bloquees = sum(1 for m in resultats if m["motif_probable"])
            return {
                "nb_modifications": len(resultats),
                "nb_bloquees_hors_perimetre": bloquees,
                "modifications": resultats,
                "note": (
                    "Base a jour a la date du dernier export Charlemagne charge, pas en temps reel. "
                    "File de sortie Charlemagne -> EcoleDirecte : une ligne sans motif et recente partira "
                    "a la prochaine synchro ; une ligne avec motif (eleve sorti...) ne partira jamais et "
                    "peut etre ignoree."
                ),
            }
        finally:
            conn.close()

    @server.tool(
        description=(
            "Calendrier scolaire : nombre de jours de classe par mois sur l'annee couverte par "
            "les periodes Charlemagne (VS_TAB_PERIODES, du debut de T1 a la fin de T3), d'apres "
            "les jours sans classe (VS_CONGE : week-ends, mercredis, vacances, feries). Base des "
            "prorata au mois pour la cantine, la garderie et l'etude (voir FAC_GRILLE_PERIODE "
            "pour les mois factures par ligne). id_classe optionnel pour ajouter les conges "
            "propres a une classe. Lecture seule, a la date du dernier export."
        )
    )
    def jours_de_classe(id_classe: str | None = None) -> dict:
        """Jours de classe par mois (calendrier Charlemagne)."""
        conn = get_connection()
        try:
            res = calendrier.jours_de_classe(conn, id_classe=id_classe)
            if not res:
                return {"error": "VS_CONGE ou VS_TAB_PERIODES absentes de la base."}
            res["note"] = "Base a jour a la date du dernier export Charlemagne charge, pas en temps reel."
            return res
        finally:
            conn.close()


    @server.tool(
        description=(
            "Emploi du temps d'une classe dans Charlemagne Vie Scolaire : horaires applicables "
            "(horaires de la classe s'ils sont parametres, sinon ceux de l'etablissement), semaine "
            "type la plus recente (cours par jour avec matiere, enseignants, salles, semaine A/B) et, "
            "si date_debut est donnee, les cours generes sur la periode (7 jours par defaut) avec le "
            "calendrier des semaines A/B. classe = identifiant, code (CM2A) ou libelle (CM2 A). "
            "Sert a verifier un import d'emploi du temps avant/apres transfert vers EcoleDirecte. "
            "Lecture seule, a la date du dernier export."
        )
    )
    def emploi_du_temps_classe(
        classe: str, date_debut: str | None = None, date_fin: str | None = None
    ) -> dict:
        """Emploi du temps d'une classe (semaine type + cours generes)."""
        conn = get_connection()
        try:
            res = vie_scolaire.emploi_du_temps_classe(conn, classe, date_debut, date_fin)
            if not res:
                return {"error": "Tables d'emploi du temps (VS_EDT_*) absentes de la base."}
            res["note"] = "Base a jour a la date du dernier export Charlemagne charge, pas en temps reel."
            return res
        finally:
            conn.close()

    @server.tool(
        description=(
            "Appels saisis dans EcoleDirecte et integres dans Charlemagne (Vie scolaire > Traitement "
            "> Suivi des appels enseignants) : un appel par classe et par demi-journee, avec effectif, "
            "nombre d'absents, date de saisie et d'integration, et un recapitulatif par classe. "
            "Filtres optionnels : date_debut, date_fin (AAAA-MM-JJ), classe. detail_absences=true "
            "ajoute les eleves absents de chaque demi-journee (controle cible uniquement). "
            "Lecture seule, a la date du dernier export."
        )
    )
    def appels_enseignants(
        date_debut: str | None = None,
        date_fin: str | None = None,
        classe: str | None = None,
        detail_absences: bool = False,
    ) -> dict:
        """Appels integres depuis EcoleDirecte."""
        conn = get_connection()
        try:
            res = vie_scolaire.appels_enseignants(conn, date_debut, date_fin, classe, detail_absences)
            if not res:
                return {"error": "VS_APPEL_PROF absente de la base."}
            res["note"] = "Base a jour a la date du dernier export Charlemagne charge, pas en temps reel."
            return res
        finally:
            conn.close()

    @server.tool(
        description=(
            "Compte d'une famille dans Charlemagne Comptabilite (FEC charge, CHARLEMAGNE_COMPTA_DB), "
            "a partir de id_responsable (IDRESPONSABLE), id_eleve (tous ses responsables) ou compte "
            "(4111...) : solde du compte 411, factures et avoirs, reglements (date, montant, mode "
            "presume : prelevement, virement, cheque, carte), impayes et frais d'impaye saisis, "
            "echeancier de la derniere facture avec le statut de chaque echeance (couverte, non "
            "couverte, a venir), retard et dernier reglement. date_reference (AAAA-MM-JJ) : defaut "
            "= derniere ecriture du FEC. Aucune donnee bancaire."
        )
    )
    def encaissements_famille(id_responsable: str | None = None, id_eleve: str | None = None,
                              compte: str | None = None, date_reference: str | None = None,
                              delai_jours: int = 5) -> dict:
        """Solde, reglements, impayes et echeances d'une famille."""
        try:
            conn = get_compta_connection()
        except FileNotFoundError as exc:
            return {"error": str(exc)}
        try:
            return comptabilite.encaissements_famille(conn, id_responsable=id_responsable, id_eleve=id_eleve,
                                                      compte=compte, date_reference=date_reference,
                                                      delai_jours=delai_jours)
        except ValueError as exc:
            return {"error": str(exc)}
        finally:
            conn.close()

    @server.tool(
        description=(
            "Familles en retard de paiement a une date (defaut : derniere ecriture du FEC charge) : "
            "retard = solde du compte famille - echeances encore a venir (echeancier de la derniere "
            "facture validee) ; echeances non couvertes, anciennete, impayes saisis (libelle impaye "
            "ou rejet) et frais, dernier reglement, enfants et classes. Resume par mode de reglement "
            "et par anciennete, familles dont l'impaye est deja regularise, familles en avance. "
            "Filtres : classe, mode_reglement (Prelevement, Cheque...), seuil en euros. Un cheque "
            "recu mais pas encore saisi en comptabilite apparait comme un retard : a verifier "
            "avant toute relance."
        )
    )
    def impayes_et_retards(date_reference: str | None = None, seuil: float = 1.0, classe: str | None = None,
                           mode_reglement: str | None = None, delai_jours: int = 5) -> dict:
        """Retards et impayes des familles."""
        try:
            conn = get_compta_connection()
        except FileNotFoundError as exc:
            return {"error": str(exc)}
        try:
            return comptabilite.impayes_et_retards(conn, date_reference=date_reference, seuil=seuil, classe=classe,
                                                   mode_reglement=mode_reglement, delai_jours=delai_jours)
        except ValueError as exc:
            return {"error": str(exc)}
        finally:
            conn.close()

    @server.tool(
        description=(
            "Controle d'une echeance de prelevement (defaut : la derniere echeance passee a la date du FEC "
            "charge) : familles et montant attendus (echeancier de la facture en vigueur a cette date, familles "
            "en Prelevement), prelevements effectivement comptabilises sur les comptes familles dans les "
            "fenetre_jours suivants, familles attendues non prelevees, ecarts de montant, prelevements sans "
            "echeance attendue, rejets (impayes) saisis avant l'echeance suivante, encaisse net, et prochaine "
            "echeance (familles, montant). date_echeance au format AAAA-MM-JJ. Ne lit pas le fichier SEPA."
        )
    )
    def controle_prelevements(date_echeance: str | None = None, fenetre_jours: int = 15) -> dict:
        """Echeance de prelevement : attendu, preleve, ecarts et rejets."""
        try:
            conn = get_compta_connection()
        except FileNotFoundError as exc:
            return {"error": str(exc)}
        try:
            return comptabilite.controle_prelevements(conn, date_echeance=date_echeance,
                                                      fenetre_jours=fenetre_jours)
        except ValueError as exc:
            return {"error": str(exc)}
        finally:
            conn.close()

    @server.tool(
        description=(
            "Pont facturation -> comptabilite : pour chaque validation de facturation (ou une seule, validation = "
            "IDVALIDATION), statut (passee en comptabilite, avec ecarts, non passee), factures retrouvees dans le "
            "journal de facturation du FEC par numero et compte 411 de la famille, factures absentes, ecarts de "
            "montant ; produits compares par compte et par date de facture (FAC_COMPTA_GENERAL) ; ecritures de "
            "facturation sur des comptes familles sans facture correspondante. A lancer apres chaque validation "
            "(initiale, complementaire, avoir) et import en comptabilite."
        )
    )
    def pont_facturation_comptabilite(validation: str | None = None) -> dict:
        """Les factures validees sont-elles en comptabilite, au bon montant ?"""
        try:
            conn = get_compta_connection()
        except FileNotFoundError as exc:
            return {"error": str(exc)}
        try:
            return comptabilite.pont_facturation_comptabilite(conn, validation=validation)
        except ValueError as exc:
            return {"error": str(exc)}
        finally:
            conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serveur MCP Charlemagne")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="stdio (defaut, Claude Desktop) ou streamable-http (distant, Copilot 365)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="streamable-http seulement")
    parser.add_argument("--port", type=int, default=8000, help="streamable-http seulement")
    args = parser.parse_args()

    server = build_server(args.transport)
    register_tools(server)

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
