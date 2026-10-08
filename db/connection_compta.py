"""Connexion lecture seule a la base Administratif avec la base comptable attachee.

La base comptable (FEC charge par loader/load_fec.py) vit dans un fichier a part,
designe par CHARLEMAGNE_COMPTA_DB (a defaut : ``comptabilite_consolidee.db`` dans le
dossier de la base Administratif CHARLEMAGNE_DB, sinon data/) : le loader Administratif peut reconstruire sa
base sans jamais toucher a la comptabilite, et inversement. Les deux sont ouvertes
en lecture seule ; les tables comptables sont sous le schema ``compta``.
"""

import os
from pathlib import Path

from db.connection import get_connection

DEFAULT_COMPTA_DB_PATH = "data/comptabilite_consolidee.db"


def chemin_compta(compta_path: str | None = None) -> Path:
    if compta_path or os.environ.get("CHARLEMAGNE_COMPTA_DB"):
        return Path(compta_path or os.environ["CHARLEMAGNE_COMPTA_DB"]).expanduser()
    if os.environ.get("CHARLEMAGNE_DB"):
        return Path(os.environ["CHARLEMAGNE_DB"]).expanduser().parent / "comptabilite_consolidee.db"
    return Path(DEFAULT_COMPTA_DB_PATH)


def get_compta_connection(db_path: str | None = None, compta_path: str | None = None):
    path = chemin_compta(compta_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Base comptable introuvable : {path}. Charger d'abord un FEC avec loader/load_fec.py "
            f"(variable CHARLEMAGNE_COMPTA_DB).")
    conn = get_connection(db_path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn.execute("ATTACH DATABASE ? AS compta", (uri,))
    return conn
