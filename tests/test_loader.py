"""Tests du loader CSV -> SQLite (donnees synthetiques, jamais de vraies donnees).

Couvre : upsert par cle (lignes absentes conservees), cle de secours _rowkey
pour une table a cle non unique (doublons exacts conserves, lignes absentes
supprimees), CSV vide (table creee, puis videe si elle avait des lignes),
tables de preparation remplacees, reconstruction quand la cle change.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loader import load_charlemagne as L


def ecrire_csv(dossier: Path, table: str, lignes: list[str]) -> None:
    (dossier / f"{table}.csv").write_text("\n".join(lignes) + "\n", encoding="utf-16-le")


def charger(dossier: Path, db: Path, monkeypatch, capsys) -> str:
    monkeypatch.setattr(sys, "argv", ["load", str(dossier), "--db", str(db)])
    assert L.main() == 0
    return capsys.readouterr().out


def lignes(db: Path, sql: str) -> list:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_upsert_par_cle_conserve_les_lignes_absentes(tmp_path, monkeypatch, capsys):
    csv, db = tmp_path / "csv", tmp_path / "b.db"
    csv.mkdir()
    ecrire_csv(csv, "COM_TEST", ["IDTEST,LIB", "1,a", "2,b"])
    charger(csv, db, monkeypatch, capsys)
    ecrire_csv(csv, "COM_TEST", ["IDTEST,LIB", "1,a2", "3,c"])
    out = charger(csv, db, monkeypatch, capsys)
    assert sorted(lignes(db, "SELECT IDTEST, LIB FROM COM_TEST")) == [("1", "a2"), ("2", "b"), ("3", "c")]
    assert "+ 1 lignes ajoutees" in out and "~ 1 lignes modifiees" in out
    assert "1 conservees" in out


def test_cle_de_secours_pour_table_a_doublons(tmp_path, monkeypatch, capsys):
    csv, db = tmp_path / "csv", tmp_path / "b.db"
    csv.mkdir()
    # FAC_COMPTA_GENERAL : 1ere colonne non unique et doublons exacts legitimes
    ecrire_csv(csv, "FAC_COMPTA_GENERAL", ["CG_COMPTE,CG_DEBIT", "706,10", "706,10", "706,20", "709,5"])
    out = charger(csv, db, monkeypatch, capsys)
    assert "cle de secours _rowkey" in out and "FAC_COMPTA_GENERAL" in out
    assert lignes(db, "SELECT COUNT(*), SUM(CAST(CG_DEBIT AS REAL)) FROM FAC_COMPTA_GENERAL") == [(4, 45.0)]
    # Rechargement identique : rien ne bouge (cle stable)
    out = charger(csv, db, monkeypatch, capsys)
    assert "+ 0 lignes ajoutees" in out and "= 4 lignes inchangees" in out
    # Une ligne change, une disparait : remplacement, jamais de cumul
    ecrire_csv(csv, "FAC_COMPTA_GENERAL", ["CG_COMPTE,CG_DEBIT", "706,10", "706,10", "706,25"])
    out = charger(csv, db, monkeypatch, capsys)
    assert lignes(db, "SELECT COUNT(*), SUM(CAST(CG_DEBIT AS REAL)) FROM FAC_COMPTA_GENERAL") == [(3, 45.0)]
    assert "2 supprimees" in out


def test_csv_vide_cree_puis_vide_la_table(tmp_path, monkeypatch, capsys):
    csv, db = tmp_path / "csv", tmp_path / "b.db"
    csv.mkdir()
    ecrire_csv(csv, "FAC_GESTION_LIGNE", ["IDGESTIONLIGNE,GL_CODE_LIGNE"])
    out = charger(csv, db, monkeypatch, capsys)
    assert "dont 1 vides" in out
    assert lignes(db, "SELECT COUNT(*) FROM FAC_GESTION_LIGNE") == [(0,)]
    # une preparation apparait, puis est validee (CSV de nouveau vide)
    ecrire_csv(csv, "FAC_GESTION_LIGNE", ["IDGESTIONLIGNE,GL_CODE_LIGNE", "1,CONTRIB", "2,APEL"])
    charger(csv, db, monkeypatch, capsys)
    assert lignes(db, "SELECT COUNT(*) FROM FAC_GESTION_LIGNE") == [(2,)]
    ecrire_csv(csv, "FAC_GESTION_LIGNE", ["IDGESTIONLIGNE,GL_CODE_LIGNE"])
    out = charger(csv, db, monkeypatch, capsys)
    assert lignes(db, "SELECT COUNT(*) FROM FAC_GESTION_LIGNE") == [(0,)]
    assert "2 supprimees" in out


def test_table_de_preparation_remplacee(tmp_path, monkeypatch, capsys):
    csv, db = tmp_path / "csv", tmp_path / "b.db"
    csv.mkdir()
    ecrire_csv(csv, "FAC_GESTION_LIGNE", ["IDGESTIONLIGNE,GL_CODE_LIGNE", "1,CONTRIB", "2,APEL"])
    charger(csv, db, monkeypatch, capsys)
    # nouvelle preparation : nouveaux identifiants, l'ancienne ne doit pas rester
    ecrire_csv(csv, "FAC_GESTION_LIGNE", ["IDGESTIONLIGNE,GL_CODE_LIGNE", "7,CONTRIB", "8,CANTINE4J"])
    charger(csv, db, monkeypatch, capsys)
    assert sorted(lignes(db, "SELECT IDGESTIONLIGNE FROM FAC_GESTION_LIGNE")) == [("7",), ("8",)]


def test_reconstruction_si_la_cle_change(tmp_path, monkeypatch, capsys):
    csv, db = tmp_path / "csv", tmp_path / "b.db"
    csv.mkdir()
    # chargee une premiere fois avec une cle par 1ere colonne (table anciennement non declaree)
    ecrire_csv(csv, "COM_PIECE_RECU", ["ID_LIEN_PIECE_PERSONNE,ETAT,ID_LIEN_PIECE_LISTE", "1,R,10", "2,R,10"])
    monkeypatch.setitem(L.COMPOSITE_KEYS, "COM_PIECE_RECU", ["ID_LIEN_PIECE_PERSONNE"])
    charger(csv, db, monkeypatch, capsys)
    # puis avec sa vraie cle composite : la table est reconstruite sans erreur
    monkeypatch.setitem(L.COMPOSITE_KEYS, "COM_PIECE_RECU", ["ID_LIEN_PIECE_PERSONNE", "ID_LIEN_PIECE_LISTE"])
    ecrire_csv(csv, "COM_PIECE_RECU", ["ID_LIEN_PIECE_PERSONNE,ETAT,ID_LIEN_PIECE_LISTE", "1,R,10", "1,R,11", "2,R,10"])
    out = charger(csv, db, monkeypatch, capsys)
    assert "reconstruite" in out
    assert lignes(db, "SELECT COUNT(*) FROM COM_PIECE_RECU") == [(3,)]
    assert L.existing_key_cols(sqlite3.connect(db), "COM_PIECE_RECU") == ["ID_LIEN_PIECE_PERSONNE", "ID_LIEN_PIECE_LISTE"]


def test_fichier_sans_en_tete_ignore(tmp_path, monkeypatch, capsys):
    csv, db = tmp_path / "csv", tmp_path / "b.db"
    csv.mkdir()
    (csv / "VIDE.csv").write_text("", encoding="utf-16-le")
    out = charger(csv, db, monkeypatch, capsys)
    assert "1 fichier(s) sans en-tete ignore(s)" in out
