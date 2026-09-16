"""Test de bout en bout (pas un test unitaire) : appelle le serveur MCP reel
tel qu'il serait invoque par un client (Claude Desktop/Code), via
MCPServer.call_tool, contre la vraie base data/administration_consolidee.db.

Usage: venv\\Scripts\\python.exe scripts\\smoke_test_mcp_server.py <IDELEVE>
"""

import asyncio
import sys

sys.path.insert(0, ".")

from mcp_server import server


async def main():
    id_eleve = sys.argv[1] if len(sys.argv) > 1 else "920"

    tools = await server.list_tools()
    print(f"Tools exposes : {[t.name for t in tools]}\n")

    result = await server.call_tool("solde_eleve", {"id_eleve": id_eleve})
    print("--- Resultat structure ---")
    print(result.structured_content)
    print()
    print("--- Contenu texte (ce que verrait le modele) ---")
    for block in result.content:
        print(getattr(block, "text", block))


if __name__ == "__main__":
    asyncio.run(main())
