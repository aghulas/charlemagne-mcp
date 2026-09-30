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

from mcp.server.mcpserver import MCPServer

from db.connection import get_connection
from tools import audit_facturation, comparaison, eleves, facturation, famille, personnels, responsables

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
        """Liste les eleves, avec filtre optionnel par classe et par statut actif."""
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
            "par leur categorie. Lecture seule, a la date du dernier export."
        )
    )
    def droits_ecoledirecte_personnels(id_personnel: str | None = None,
                                       actifs_seulement: bool = True) -> dict:
        """Droits, fonctions et notifications EcoleDirecte des adultes."""
        conn = get_connection()
        try:
            res = personnels.droits_ecoledirecte(conn, id_personnel=id_personnel,
                                                 actifs_seulement=actifs_seulement)
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
            "numerotation et equilibre comptable. A lancer apres chaque nouvelle preparation, "
            "avant de valider. N'expose aucune donnee bancaire."
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
            "Fiche famille complete en un appel, a partir d'un eleve (id_eleve = IDELEVE) ou d'un "
            "foyer (id_foyer = IDFOYER) : foyer (cotisation APEL Oui/Ext/Non), responsables (lien, "
            "responsable principal, payeur et pourcentage, mode de reglement, IBAN renseigne ou "
            "non, enfants a charge, quotients, informations complementaires - ex. Ext. scolarisee, "
            "Justificatif Fraterie), enfants (classe, regime, jours de cantine, activites, "
            "informations complementaires, remises), lignes facturees non nulles (preparation en "
            "cours, sinon derniere facturation validee ; validee=True/False pour forcer) avec le "
            "total par responsable, et pieces a verser recues ou non. A utiliser pour verifier une "
            "famille apres une fiche forfaits, un certificat ou une facture APEL. Lecture seule, "
            "aucune coordonnee bancaire (seulement renseigne/vide)."
        )
    )
    def fiche_famille(id_eleve: str | None = None, id_foyer: str | None = None,
                      validee: bool | None = None) -> dict:
        """Tout sur une famille : responsables, enfants, facturation, pieces recues."""
        conn = get_connection()
        try:
            return famille.fiche_famille(conn, id_eleve=id_eleve, id_foyer=id_foyer, validee=validee)
        except ValueError as exc:
            return {"error": str(exc)}
        finally:
            conn.close()

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
