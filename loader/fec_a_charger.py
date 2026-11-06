"""Selection des FEC a charger dans le dossier d'echange (appele par le script de chargement automatique).

Le dossier d'echange recoit les exports FEC faits a la main en session RDP : le FEC de la periode
courante (``<SIREN>FEC<date de cloture>.txt``, ecrase a chaque export) et, au fil du temps, ceux des
exercices clos. Pour chaque fichier ``*fec*.txt`` de la RACINE du dossier (les sous-dossiers sont
ignores), ce module :

- attend la fin de la copie (taille et date stables) ;
- ignore un fichier deja charge (empreinte presente dans CPT_EXPORT ou CPT_EXPORT_CLOS) ou deja
  refuse (``<stage>/refus/<empreinte>``, ou l'ancien ``<stage>/dernier_refus.sha``) ;
- copie les autres hors du dossier d'echange (acces au dossier Telechargements : voir le script) ;
- les range du plus recent au plus ancien d'apres la date de cloture du nom, pour que le FEC de
  la periode courante soit charge d'abord (le chargeur classe ensuite un FEC plus ancien comme
  exercice clos).

Sortie (une ligne par fichier, champs separes par une tabulation) :
  NOUVEAU <copie> <description> <empreinte>   |   AUCUN   |   DEJA   |   ERREUR <message>
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import sys
import time


def _charges(db: str) -> set[str]:
    empreintes: set[str] = set()
    if not os.path.exists(db):
        return empreintes
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return empreintes
    try:
        for table in ("CPT_EXPORT", "CPT_EXPORT_CLOS"):
            try:
                empreintes |= {r[0] for r in conn.execute(f"SELECT sha256 FROM {table}")}
            except sqlite3.Error:
                pass
    finally:
        conn.close()
    return empreintes


def _refuse(stage: str, sha: str) -> bool:
    if os.path.exists(os.path.join(stage, "refus", sha)):
        return True
    ancien = os.path.join(stage, "dernier_refus.sha")
    return os.path.exists(ancien) and open(ancien).read().strip() == sha


def _cloture(nom: str) -> str:
    m = re.search(r"FEC(\d{8})", nom, re.I)
    return m.group(1) if m else "00000000"


def _stable(chemin: str, attente: float, essais: int) -> None:
    prec = None
    for _ in range(essais):
        st = os.stat(chemin)
        cur = (st.st_size, st.st_mtime)
        if cur == prec:
            return
        prec = cur
        time.sleep(attente)


def selectionner(inbox: str, stage: str, db: str, attente: float = 5, essais: int = 36) -> list[dict]:
    """FEC nouveaux (copies dans ``stage``), le plus recent d'abord. Leve OSError si le dossier est illisible."""
    candidats = [os.path.join(inbox, n) for n in os.listdir(inbox)
                 if "fec" in n.lower() and n.lower().endswith(".txt") and os.path.isfile(os.path.join(inbox, n))]
    if not candidats:
        return []
    deja = _charges(db)
    candidats.sort(key=lambda p: (_cloture(os.path.basename(p)), os.path.getmtime(p)), reverse=True)
    nouveaux = []
    for fec in candidats:
        _stable(fec, attente, essais)
        sha = hashlib.sha256(open(fec, "rb").read()).hexdigest()
        if sha in deja or _refuse(stage, sha):
            continue
        copie = os.path.join(stage, os.path.basename(fec))
        shutil.copy2(fec, copie)
        quand = time.strftime("%d/%m/%Y %H:%M", time.localtime(os.path.getmtime(fec)))
        nouveaux.append({"copie": copie, "sha": sha,
                         "description": f"{os.path.getsize(fec)} octets, modifie le {quand}"})
    return nouveaux if nouveaux else [{"deja": True}]


def main(argv: list[str]) -> int:
    inbox, stage, db = argv[1:4]
    try:
        res = selectionner(inbox, stage, db)
    except OSError as exc:
        print(f"ERREUR\tlecture impossible de {inbox} : {exc}")
        return 0
    if not res:
        print("AUCUN")
    elif res[0].get("deja"):
        print("DEJA")
    else:
        for r in res:
            print(f"NOUVEAU\t{r['copie']}\t{r['description']}\t{r['sha']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
