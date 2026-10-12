"""Outils MCP - pieces a verser recues ou retirees entre deux exports Charlemagne.

Les familles deposent leurs pieces (justificatifs, attestations, fiches) dans
EcoleDirecte ; Charlemagne les recupere a la synchronisation et les marque « Recue »
(COM_PIECE_RECU). Une piece supprimee dans Charlemagne repasse « Non Recue ».
Comparer l'etat des pieces de la base actuelle a celui d'une archive donne, en
quelques secondes, la liste des nouveaux depots a verifier et des suppressions
faites par le secretariat, sans relire tous les comptes EcoleDirecte.

Lecture seule : seuls les intitules et etats sont lus, jamais le contenu des pieces.
"""

import sqlite3


def _etat_pieces(conn) -> dict[tuple[str, str, str], str]:
    """(liste, piece, id personne) -> etat. Tables absentes -> vide."""
    try:
        listes = {str(r[0]): (r[1], r[2]) for r in conn.execute(
            "SELECT ID_LISTE_PIECE, LIBELLE, TYPE FROM COM_LISTE_PIECE")}
        pieces = {str(r[0]): r[1] for r in conn.execute("SELECT IDPIECE_DOSSIER, LIBELLE FROM INS_PIECES_DOSSIER")}
        liens_liste = {str(r[0]): pieces.get(str(r[1]), str(r[1])) for r in conn.execute(
            "SELECT ID_LIEN_PIECE_LISTE, IDPIECE_DOSSIER FROM COM_LIEN_PIECE_LISTE")}
        personnes = {str(r[0]): (str(r[1]), str(r[2])) for r in conn.execute(
            "SELECT ID_LIEN_PIECE_PERSONNE, ID_PERSONNE, ID_LISTE_PIECE FROM COM_LIEN_PIECE_PERSONNE")}
        out = {}
        for lp, ll, etat in conn.execute("SELECT ID_LIEN_PIECE_PERSONNE, ID_LIEN_PIECE_LISTE, ETAT FROM COM_PIECE_RECU"):
            pid, lid = personnes.get(str(lp), ("", ""))
            out[(lid, liens_liste.get(str(ll), str(ll)), pid)] = etat or ""
        out["__listes__"] = listes  # type: ignore[assignment]
        return out
    except sqlite3.Error:
        return {}


def _recue(etat: str | None) -> bool:
    return bool(etat) and str(etat).strip().lower().startswith("re")


def _noms(conn) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    eleves, classes, resp = {}, {}, {}
    for i, n, p, c in conn.execute("""SELECT e.IDELEVE, e.EL_NOM1, e.EL_PRENOM1, COALESCE(c.CL_LIBELLE, '')
                                      FROM COM_ELEVES e LEFT JOIN COM_CLASSES c ON c.IDCLASSE = e.EL_IDCLASSE"""):
        eleves[str(i)] = f"{n} {p}"
        classes[str(i)] = c
    for i, n, p in conn.execute("SELECT IDRESPONSABLE, RE_NOM1, RE_PRENOM1 FROM COM_RESPONSABLES"):
        resp[str(i)] = f"{n} {p}"
    return eleves, classes, resp


def pieces_changees(actuel: sqlite3.Connection, precedent: sqlite3.Connection) -> dict:
    """Pieces passees a « Recue » (nouveaux depots recuperes par Charlemagne) ou
    retirees (« Recue » -> « Non Recue » ou disparues) entre deux exports."""
    a, p = _etat_pieces(actuel), _etat_pieces(precedent)
    if not a:
        raise ValueError("Tables des pieces a verser absentes de l'export actuel (COM_PIECE_RECU...).")
    listes = a.pop("__listes__", {})
    p.pop("__listes__", None)
    try:
        eleves, classes, resp = _noms(actuel)
    except sqlite3.Error:
        eleves, classes, resp = {}, {}, {}

    def decrire(cle, avant, apres):
        lid, piece, pid = cle
        libelle, typ = listes.get(lid, (lid, ""))
        famille = str(typ).upper() == "F"
        nom = (resp if famille else eleves).get(pid) or eleves.get(pid) or resp.get(pid) or pid
        d = {"liste": libelle, "piece": piece, "personne": nom, "id_personne": pid,
             "type_personne": "responsable" if famille else "eleve", "avant": avant or "(absente)", "apres": apres or "(absente)"}
        if not famille and classes.get(pid):
            d["classe"] = classes[pid]
        return d

    recues, retirees = [], []
    for cle in sorted(set(a) | set(p)):
        av, ap = p.get(cle), a.get(cle)
        if _recue(ap) and not _recue(av):
            recues.append(decrire(cle, av, ap))
        elif _recue(av) and not _recue(ap):
            retirees.append(decrire(cle, av, ap))
    return {"nouvelles_pieces_recues": recues, "pieces_retirees": retirees,
            "resume": {"recues": len(recues), "retirees": len(retirees)},
            "note": ("« Recue » = piece deposee dans EcoleDirecte et recuperee par Charlemagne a la synchronisation. "
                     "Une piece retiree a ete supprimee dans Charlemagne (la suppression part vers EcoleDirecte a la "
                     "synchronisation suivante). Le contenu des pieces n'est pas lu : le telecharger depuis "
                     "EcoleDirecte (connecteur EcoleDirecte, ed_admin_piece_telecharger) pour le verifier.")}
