"""Serveur MCP Charlemagne - transport stdio local.

Chaque tool expose une fonction parametree sur la base SQLite consolidee
(jamais d'acces SQL libre depuis le modele). Lecture seule.
"""

from mcp.server.mcpserver import MCPServer

from db.connection import get_connection
from tools import eleves, facturation, personnels

server = MCPServer(
    name="charlemagne",
    instructions=(
        "Acces en lecture seule aux donnees de gestion Charlemagne (l'établissement), "
        "a partir d'une base SQLite consolidee depuis les exports natifs Charlemagne. "
        "Les donnees ne sont pas temps reel : elles datent du dernier export charge."
    ),
)


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


if __name__ == "__main__":
    server.run()
