"""Connexion a la base SQLite consolidee servie au MCP (lecture seule)."""

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = "data/administration_consolidee.db"


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Ouvre une connexion en lecture seule a la base consolidee.

    Le chemin est resolu, dans l'ordre : argument explicite, variable
    d'environnement CHARLEMAGNE_DB, chemin par defaut.
    """
    path = Path(db_path or os.environ.get("CHARLEMAGNE_DB", DEFAULT_DB_PATH))
    if not path.exists():
        raise FileNotFoundError(
            f"Base SQLite introuvable : {path}. Lancer d'abord "
            f"loader/load_charlemagne.py pour la generer."
        )
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn
