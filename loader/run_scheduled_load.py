"""
Wrapper pour l'execution planifiee (Planificateur de taches Windows) de
loader/load_charlemagne.py.

Le Planificateur de taches ne capture pas stdout par defaut : ce script
ecrit donc lui-meme tout (rapport de diff inclus) dans un fichier de log
horodate sous logs/, et ne fait jamais planter silencieusement - toute
exception est loguee avec sa trace complete et le script sort en erreur
(code != 0) pour que l'echec apparaisse dans l'historique du Planificateur.

Chemins par defaut fournis en dur car ce script est lance hors contexte
interactif (pas de cwd garanti) - surchargeables via variables
d'environnement pour les tests.

Variables d'environnement :
    CHARLEMAGNE_CSV_DIR  dossier des CSV exportes (defaut : le dossier OneDrive connu)
    CHARLEMAGNE_DB       base SQLite consolidee (defaut : data/administration_consolidee.db)
"""

import contextlib
import io
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CSV_DIR = (
    r"C:\Users\<utilisateur>\OneDrive - <Ecole>\Charlemagne\csv"  # a adapter par etablissement
)
DEFAULT_DB_PATH = REPO_ROOT / "data" / "administration_consolidee.db"
LOG_DIR = REPO_ROOT / "logs"
LOG_RETENTION = 30  # nombre de logs horodates conserves (le reste est purge)


def prune_old_logs() -> None:
    logs = sorted(LOG_DIR.glob("load_*.log"), key=lambda p: p.stat().st_mtime)
    for old in logs[:-LOG_RETENTION]:
        old.unlink(missing_ok=True)


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    prune_old_logs()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"load_{timestamp}.log"
    latest_path = LOG_DIR / "latest.log"

    csv_dir = os.environ.get("CHARLEMAGNE_CSV_DIR", DEFAULT_CSV_DIR)
    db_path = os.environ.get("CHARLEMAGNE_DB", str(DEFAULT_DB_PATH))

    sys.path.insert(0, str(REPO_ROOT))

    exit_code = 0
    with open(log_path, "w", encoding="utf-8") as log_file:
        def log(msg: str = "") -> None:
            print(msg, file=log_file)

        log(f"=== Chargement planifie - {datetime.now().isoformat()} ===")
        log(f"CSV : {csv_dir}")
        log(f"DB  : {db_path}")

        if not Path(csv_dir).is_dir():
            log(f"ERREUR : dossier CSV introuvable ({csv_dir}).")
            log("Cause probable : OneDrive pas synchronise / session pas ouverte.")
            exit_code = 1
        else:
            log("-" * 70)
            buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(buffer):
                    exit_code = _run_load(csv_dir, db_path)
            except SystemExit as exc:
                exit_code = exc.code or 0
            except Exception:
                log("ERREUR pendant le chargement :")
                log(traceback.format_exc())
                exit_code = 1
            finally:
                log(buffer.getvalue())

        log("-" * 70)
        log(f"Termine avec le code {exit_code}.")

    latest_path.write_text(log_path.read_text(encoding="utf-8"), encoding="utf-8")
    return exit_code


def _run_load(csv_dir: str, db_path: str) -> int:
    """Appelle load_charlemagne.main() avec des arguments explicites (evite de
    dependre de sys.argv, peu fiable en contexte planifie)."""
    from loader import load_charlemagne

    old_argv = sys.argv
    sys.argv = ["load_charlemagne.py", csv_dir, "--db", db_path]
    try:
        return load_charlemagne.main()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())
