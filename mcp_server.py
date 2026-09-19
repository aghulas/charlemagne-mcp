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
from tools import eleves, facturation, personnels

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
            "Liste des eleves (IDELEVE, nom, prenom, classe), filtrable par classe et par "
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
