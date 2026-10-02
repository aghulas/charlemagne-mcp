"""Test de bout en bout des outils regularisations_a_preparer, suivi_echeanciers et fiche_famille
(cumul des validations) via MCPServer.call_tool, contre la vraie base (CHARLEMAGNE_DB) et les
regles (CHARLEMAGNE_REGLES_FACTURATION). N'affiche que des compteurs et des montants, jamais de nom.
Ne rien commiter de ce que ce script affiche."""

import asyncio
import json
import sys

sys.path.insert(0, ".")

from mcp_server import build_server, register_tools


def _texte(result):
    contenu = result[0] if isinstance(result, tuple) else result
    items = getattr(contenu, "content", contenu)
    return json.loads(items[0].text)


async def main() -> None:
    server = build_server("stdio")
    register_tools(server)
    args = {"date_effet": sys.argv[1]} if len(sys.argv) > 1 else {}
    r = _texte(await server.call_tool("regularisations_a_preparer", args))
    print("regularisations ->", r.get("error") or {
        "periode": r["periode_regularisee"], "resume": r["resume"],
        "lignes": [(x["id_eleve"], l["code"], l["sens"], l["montant_prorata"], l["montant_plein"])
                   for x in r["regularisations"][:5] for l in x["lignes"]],
        "apel": [(a["foyer"], a["montant"]) for a in r["apel"][:5]],
        "en_attente": [(a["id_eleve"], a["code"], a["montant"], a["controle"][:40]) for a in r["lignes_manuelles_en_attente"]],
        "a_saisir": [(a["piece"], a["a_saisir"]) for a in r["a_saisir_avant_de_facturer"][:5]]})
    r = _texte(await server.call_tool("regularisations_a_preparer", {"date_effet": "2026-08-01"}))
    print("date hors annee ->", r.get("error"))
    r = _texte(await server.call_tool("suivi_echeanciers", {}))
    print("echeanciers ->", r.get("error") or {"resume": r["resume"], "nb_alertes": r["nb_alertes"],
                                              "familles_detaillees": len(r["familles"])})
    if not r.get("error") and r["familles"]:
        rid = r["familles"][0]["id_responsable"]
        f = _texte(await server.call_tool("suivi_echeanciers", {"id_responsable": str(rid)}))["familles"][0]
        print("une famille ->", {"factures": [(x["numero"], x["type"], x["montant"]) for x in f["factures"]],
                                 "reste": f["reste_a_prelever"], "a_venir": len(f["echeances_a_venir"])})
        lignes = _texte(await server.call_tool("fiche_famille", {"id_foyer": None, "id_eleve": None}))
        print("fiche sans parametre ->", lignes.get("error"))
    r = _texte(await server.call_tool("audit_de_facturation", {"validee": True}))
    print("audit validee ->", r.get("error") or {"validations": r["resume"].get("validations"), "nb_anomalies": r["nb_anomalies"]})


if __name__ == "__main__":
    asyncio.run(main())
