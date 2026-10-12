"""Pieces recues ou retirees entre deux exports (tools.pieces) - sans base reelle."""
import sqlite3

import pytest

from tools.pieces import pieces_changees


def base(etats):
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE COM_LISTE_PIECE (ID_LISTE_PIECE TEXT, LIBELLE TEXT, TYPE TEXT);
        CREATE TABLE INS_PIECES_DOSSIER (IDPIECE_DOSSIER TEXT, LIBELLE TEXT);
        CREATE TABLE COM_LIEN_PIECE_LISTE (ID_LIEN_PIECE_LISTE TEXT, IDPIECE_DOSSIER TEXT, ID_LISTE_PIECE TEXT);
        CREATE TABLE COM_LIEN_PIECE_PERSONNE (ID_LIEN_PIECE_PERSONNE TEXT, ID_LISTE_PIECE TEXT, ID_PERSONNE TEXT);
        CREATE TABLE COM_PIECE_RECU (ID_LIEN_PIECE_PERSONNE TEXT, ID_LIEN_PIECE_LISTE TEXT, ETAT TEXT);
        CREATE TABLE COM_CLASSES (IDCLASSE TEXT, CL_LIBELLE TEXT);
        CREATE TABLE COM_ELEVES (IDELEVE TEXT, EL_NOM1 TEXT, EL_PRENOM1 TEXT, EL_IDCLASSE TEXT);
        CREATE TABLE COM_RESPONSABLES (IDRESPONSABLE TEXT, RE_NOM1 TEXT, RE_PRENOM1 TEXT);
        INSERT INTO COM_LISTE_PIECE VALUES ('2', 'Justificatifs', 'F'), ('7', 'Assurance', 'E');
        INSERT INTO INS_PIECES_DOSSIER VALUES ('2', 'Justif APEL'), ('11', 'Attestation');
        INSERT INTO COM_LIEN_PIECE_LISTE VALUES ('L2', '2', '2'), ('L11', '11', '7');
        INSERT INTO COM_LIEN_PIECE_PERSONNE VALUES ('P1', '2', '864'), ('P2', '7', '895'), ('P3', '7', '896');
        INSERT INTO COM_CLASSES VALUES ('C', 'CM1 A');
        INSERT INTO COM_ELEVES VALUES ('895', 'TEST', 'Eleve', 'C'), ('896', 'TEST', 'Autre', 'C');
        INSERT INTO COM_RESPONSABLES VALUES ('864', 'TEST', 'Parent');
    """)
    for lp, ll, e in etats:
        c.execute("INSERT INTO COM_PIECE_RECU VALUES (?, ?, ?)", (lp, ll, e))
    return c


def test_recues_et_retirees():
    prec = base([("P2", "L11", "Reçue"), ("P3", "L11", "Reçue")])
    act = base([("P1", "L2", "Reçue"), ("P2", "L11", "Non Reçue"), ("P3", "L11", "Reçue")])
    r = pieces_changees(act, prec)
    assert r["resume"] == {"recues": 1, "retirees": 1}
    n = r["nouvelles_pieces_recues"][0]
    assert (n["piece"], n["personne"], n["type_personne"], n["avant"]) == ("Justif APEL", "TEST Parent", "responsable", "(absente)")
    t = r["pieces_retirees"][0]
    assert (t["piece"], t["personne"], t["classe"], t["apres"]) == ("Attestation", "TEST Eleve", "CM1 A", "Non Reçue")


def test_non_recue_n_est_pas_un_depot():
    r = pieces_changees(base([("P1", "L2", "Non Reçue")]), base([]))
    assert r["resume"] == {"recues": 0, "retirees": 0}


def test_tables_absentes():
    with pytest.raises(ValueError):
        pieces_changees(sqlite3.connect(":memory:"), base([]))
