"""Outils MCP - historique des mails envoyes depuis Charlemagne (COM_HISTORIQUE_MAILS).

Une ligne par envoi : objet (SUJET), corps HTML (CORPS), date (DATE_ENVOI, AAAAMMJJ),
module (NOM_MODULE), campagne (NOM_CAMPAGNE, de la forme <etab>_<AAAAMMJJHHMMSSmmm>_<n>,
d'ou l'on tire l'heure d'envoi), utilisateur Charlemagne (IDPERSONNEL, 0 si inconnu) et
trois listes paralleles separees par « ; » : LISTE_CLIENTS (« NOM Prenom(Perso) »),
LISTE_MAILS (adresses) et LISTE_TYPES (famille, prof...).

Lecture seule. L'export ne contient AUCUN statut de remise (delivre, rejete, adresse
blacklistee) : la liste noire de Charlemagne n'est pas exportee.
"""

import html
import re
import sqlite3

_TAG = re.compile(r"<[^>]+>")
_BLOCS = re.compile(r"</?(p|div|br|li|tr|h\d)[^>]*>", re.I)
_CLIENT = re.compile(r"^(?P<nom>.*?)\s*\((?P<type>[^()]*)\)\s*$")
_CAMPAGNE = re.compile(r"^\d+_(\d{8})(\d{2})(\d{2})(\d{2})")

NOTE = ("Base a jour a la date du dernier export Charlemagne charge. Mails envoyes depuis "
        "Charlemagne uniquement (pas la messagerie EcoleDirecte). Aucun statut de remise : "
        "l'export ne dit pas si un mail a ete delivre, rejete ou bloque par la liste noire.")


def _q(conn, sql: str, params: tuple = ()) -> list[dict]:
    try:
        cur = conn.execute(sql, params)
    except sqlite3.OperationalError:
        return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def texte_brut(corps: str | None) -> str:
    """HTML du corps -> texte lisible (paragraphes conserves, espaces normalises)."""
    t = _BLOCS.sub("\n", corps or "")
    t = html.unescape(_TAG.sub("", t)).replace("\xa0", " ")
    lignes = [re.sub(r"[ \t]+", " ", l).strip() for l in t.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lignes)).strip()


def _liste(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(";")]


def destinataires(row: dict) -> list[dict]:
    """Zippe les trois listes paralleles ; ignore les entrees entierement vides."""
    clients, mails, types = _liste(row.get("LISTE_CLIENTS")), _liste(row.get("LISTE_MAILS")), _liste(row.get("LISTE_TYPES"))
    out = []
    for i in range(max(len(clients), len(mails), len(types))):
        c = clients[i] if i < len(clients) else ""
        m = mails[i] if i < len(mails) else ""
        t = types[i] if i < len(types) else ""
        if not (c or m):
            continue
        g = _CLIENT.match(c)
        out.append({"nom": (g["nom"] if g else c).strip(), "adresse": (g["type"] if g else None) or None,
                    "mail": m or None, "type": t or None})
    return out


def _date_iso(v) -> str | None:
    s = str(v or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if re.fullmatch(r"\d{8}", s) else (s or None)


def _heure(campagne) -> str | None:
    g = _CAMPAGNE.match(str(campagne or ""))
    return f"{g[2]}:{g[3]}:{g[4]}" if g else None


def _date_param(v: str | None, nom: str) -> str | None:
    if v in (None, ""):
        return None
    s = str(v).replace("-", "").replace("/", "")
    if not re.fullmatch(r"\d{8}", s):
        raise ValueError(f"{nom} : date attendue au format AAAA-MM-JJ, recu {v!r}")
    return s


def historique_mails(conn, recherche: str | None = None, destinataire: str | None = None,
                     depuis: str | None = None, jusqu_a: str | None = None,
                     id_histo: str | None = None, limite: int = 50) -> dict:
    """Mails envoyes depuis Charlemagne, du plus recent au plus ancien.

    recherche : texte cherche dans l'objet et le corps (insensible a la casse).
    destinataire : nom ou adresse (partiel) ; ne garde que les envois qui le concernent et
        indique les destinataires correspondants.
    depuis / jusqu_a : bornes de date incluses (AAAA-MM-JJ).
    id_histo : un envoi precis, renvoye en detail (corps en texte, tous les destinataires).
    """
    personnels = {str(p["IDPERSONNEL"]): f"{p.get('PE_PRENOM') or ''} {p.get('PE_NOM') or ''}".strip()
                  for p in _q(conn, "SELECT IDPERSONNEL, PE_NOM, PE_PRENOM FROM COM_PERSONNELS")}

    def entete(r: dict, dest: list[dict]) -> dict:
        types: dict[str, int] = {}
        for d in dest:
            types[d["type"] or "?"] = types.get(d["type"] or "?", 0) + 1
        uid = str(r.get("IDPERSONNEL") or "0")
        return {"id_histo": str(r["IDHISTO"]), "date": _date_iso(r.get("DATE_ENVOI")),
                "heure": _heure(r.get("NOM_CAMPAGNE")), "objet": (r.get("SUJET") or "").strip(),
                "module": r.get("NOM_MODULE") or None,
                "utilisateur": personnels.get(uid, uid) if uid != "0" else None,
                "nb_destinataires": len(dest), "types_destinataires": types}

    if id_histo not in (None, ""):
        rows = _q(conn, "SELECT * FROM COM_HISTORIQUE_MAILS WHERE IDHISTO = ?", (str(id_histo),))
        if not rows:
            raise ValueError(f"Aucun envoi avec IDHISTO={id_histo!r}")
        r = rows[0]
        dest = destinataires(r)
        return {**entete(r, dest), "campagne": r.get("NOM_CAMPAGNE") or None,
                "corps": texte_brut(r.get("CORPS")), "destinataires": dest, "note": NOTE}

    d1, d2 = _date_param(depuis, "depuis"), _date_param(jusqu_a, "jusqu_a")
    sql, params = "SELECT * FROM COM_HISTORIQUE_MAILS WHERE 1=1", []
    if d1:
        sql += " AND DATE_ENVOI >= ?"; params.append(d1)
    if d2:
        sql += " AND DATE_ENVOI <= ?"; params.append(d2)
    if recherche:
        sql += " AND (lower(SUJET) LIKE ? OR lower(CORPS) LIKE ?)"
        params += [f"%{recherche.lower()}%"] * 2
    if destinataire:
        sql += " AND (lower(LISTE_MAILS) LIKE ? OR lower(LISTE_CLIENTS) LIKE ?)"
        params += [f"%{destinataire.lower()}%"] * 2
    sql += " ORDER BY CAST(IDHISTO AS INTEGER) DESC"
    rows = _q(conn, sql, tuple(params))

    envois = []
    for r in rows:
        dest = destinataires(r)
        e = entete(r, dest)
        if destinataire:
            cle = destinataire.lower()
            trouves = [d for d in dest if cle in (d["mail"] or "").lower() or cle in d["nom"].lower()]
            if not trouves:
                continue  # correspondance a cheval sur deux entrees de la liste : faux positif
            e["destinataires_correspondants"] = trouves
        e["extrait"] = texte_brut(r.get("CORPS"))[:200]
        envois.append(e)
    limite = max(1, min(int(limite or 50), 500))
    return {"nb_envois": len(envois), "envois": envois[:limite], "tronque": len(envois) > limite,
            "note": NOTE + " Detail complet d'un envoi : id_histo."}
