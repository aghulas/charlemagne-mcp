"""Test de bout en bout des outils audit_de_facturation et comparer_exports via MCPServer.call_tool,
contre la vraie base (CHARLEMAGNE_DB) et les regles (CHARLEMAGNE_REGLES_FACTURATION).
Ne rien commiter de ce que ce script affiche : il lit de vraies donnees."""

import asyncio
import json

from mcp_server import build_server, register_tools


def _texte(result):
    contenu = result[0] if isinstance(result, tuple) else result
    items = getattr(contenu, "content", contenu)
    return json.loads(items[0].text)


async def main() -> None:
    server = build_server("stdio")
    register_tools(server)
    for args in ({"validee": True}, {"validee": False}):
        r = _texte(await server.call_tool("audit_de_facturation", args))
        print("audit", args, "->", r.get("error") or {"resume": r["resume"], "nb_anomalies": r["nb_anomalies"]})
    r = _texte(await server.call_tool("comparer_exports", {}))
    print("comparaison ->", r.get("error") or {"archive": r["archive_comparee"], "tables_modifiees": len(r["tables_modifiees"]),
                                               "parametrage": list(r["parametrage_facturation"]), "fiches": list(r["fiches"])})
    r = _texte(await server.call_tool("comparer_exports", {"archive": "inexistante.db"}))
    print("archive inexistante ->", r.get("error"))


if __name__ == "__main__":
    asyncio.run(main())
