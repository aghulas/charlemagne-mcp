"""Tests des enrichissements (referentiels, enseignants, anciennete, journal des
modifications, calendrier) - donnees synthetiques uniquement, jamais de PII."""

import sqlite3

import pytest

from tools.calendrier import jours_de_classe
from tools.eleves import liste_eleves
from tools.modifications import modifications_ecoledirecte_en_attente
from tools.personnels import liste_personnels
from tools.referentiels import libelles_liens, anciennete_par_eleve
from tools.responsables import responsables_eleves


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE COM_ELEVES (IDELEVE TEXT PRIMARY KEY, EL_NOM1 TEXT, EL_PRENOM1 TEXT,
            EL_SEXE TEXT, EL_IDCLASSE TEXT, EL_DATE_SORTIE TEXT);
        CREATE TABLE COM_CLASSES (IDCLASSE TEXT PRIMARY KEY, CL_LIBELLE TEXT);
        CREATE TABLE COM_PERSONNELS (IDPERSONNEL TEXT PRIMARY KEY, PE_NOM TEXT, PE_PRENOM TEXT,
            PE_PARTICULE TEXT, PE_TYPE TEXT, PE_DATE_SORTIE TEXT);
        CREATE TABLE COM_PROFS_PRINCIPAUX (IDPROFSPRINCIPAUX TEXT, IDPERSONNEL TEXT, IDCLASSE TEXT, NUM_LIGNE TEXT);
        CREATE TABLE ADM_HISTO_CLASSE_MEF (ID_HISTO_CLASSE_MEF TEXT, IDELEVE TEXT, IDCLASSE TEXT,
            ANNEE_SCOLAIRE TEXT, DATE_ENTREE TEXT, DATE_SORTIE TEXT, CODE_MEF_INTERNE TEXT);
        CREATE TABLE TAB_LIENS (LIE_CODE TEXT, LIE_LIBELLE TEXT, LIE_TYPE TEXT, LIE_TRI TEXT);
        CREATE TABLE COM_LIENER (IDRESPONSABLE TEXT, IDELEVE TEXT, LER_LIEN TEXT, LER_TYPE_RESP TEXT, LER_ORDRE TEXT);
        CREATE TABLE COM_RESPONSABLES (IDRESPONSABLE TEXT PRIMARY KEY,
            RE_CIVILITE1 TEXT, RE_PARTICULE1 TEXT, RE_NOM1 TEXT, RE_PRENOM1 TEXT, RE_NOM_JFILLE1 TEXT,
            RE_EMAILPERSO1 TEXT, RE_EMAILPRO1 TEXT, RE_TELPORTABLE1 TEXT, RE_TELPRO1 TEXT,
            RE_CIVILITE2 TEXT, RE_PARTICULE2 TEXT, RE_NOM2 TEXT, RE_PRENOM2 TEXT, RE_NOM_JFILLE2 TEXT,
            RE_EMAILPERSO2 TEXT, RE_EMAILPRO2 TEXT, RE_TELPORTABLE2 TEXT, RE_TELPRO2 TEXT,
            RE_TELDOMICILE TEXT, RE_CODEPOSTAL TEXT, RE_VILLE TEXT);
        CREATE TABLE COM_JOURNAL_MODIF (ID_JOURNAL_MODIF TEXT, TYPE TEXT, TYPE_FICHIER TEXT,
            ID_CHARLEMAGNE TEXT, DATE_HEURE_MODIF TEXT, DATE_HEURE_ENVOI TEXT, UTILISATEUR TEXT,
            STATUT TEXT, DETAIL TEXT);
        CREATE TABLE VS_CONGE (IDVS_CONGE TEXT, IDETABLISSEMENT TEXT, IDCLASSE TEXT, CO_JOUR TEXT);
        CREATE TABLE VS_TAB_PERIODES (IDPERIODE TEXT, CODE_PERIODE TEXT, DATE_DEBUT TEXT, DATE_FIN TEXT,
            IDETABLISSEMENT TEXT);

        INSERT INTO COM_CLASSES VALUES ('C1', 'CE1 A'), ('C2', 'CE1 B');
        INSERT INTO COM_ELEVES VALUES ('1', 'DURAND', 'Alice', 'F', 'C1', NULL);
        INSERT INTO COM_ELEVES VALUES ('2', 'MARTIN', 'Bob', 'M', 'C2', NULL);
        INSERT INTO COM_PERSONNELS VALUES ('P1', 'LEROY', 'Anne', NULL, 'ENS', NULL);
        INSERT INTO COM_PERSONNELS VALUES ('P2', 'MOREAU', 'Luc', NULL, 'ENS', NULL);
        INSERT INTO COM_PERSONNELS VALUES ('P3', 'ROUX', 'Eva', NULL, 'ADM', NULL);
        -- CE1 A en co-enseignement, CE1 B sans enseignant principal renseigne
        INSERT INTO COM_PROFS_PRINCIPAUX VALUES ('x', 'P1', 'C1', '1'), ('y', 'P2', 'C1', '2');
        -- Alice : deux annees passees ; Bob : arrive cette annee
        INSERT INTO ADM_HISTO_CLASSE_MEF VALUES ('h1', '1', 'C0', '2024-2025', '20240902', '20250704', 'GS');
        INSERT INTO ADM_HISTO_CLASSE_MEF VALUES ('h2', '1', 'C9', '2025-2026', '20250901', '20260703', 'CP');
        INSERT INTO TAB_LIENS VALUES ('PS', 'Père', '1', '1'), ('GM', 'Grand-mère', '1', '9');
        INSERT INTO COM_LIENER VALUES ('R1', '1', 'PS', '1', '1'), ('R2', '1', 'GM', '0', '2');
        INSERT INTO COM_RESPONSABLES (IDRESPONSABLE, RE_NOM1, RE_PRENOM1) VALUES ('R1', 'DURAND', 'Paul');
        INSERT INTO COM_RESPONSABLES (IDRESPONSABLE, RE_NOM1, RE_PRENOM1) VALUES ('R2', 'BLANC', 'Odile');
        INSERT INTO COM_JOURNAL_MODIF VALUES ('j1', 'Eleve_ATraiter', 'ELEVE', '2', '20260831131848651',
            '00000000000000000', 'Secretariat', 'En attente', NULL);
        INSERT INTO COM_JOURNAL_MODIF VALUES ('j2', 'Resp_ATraiter', 'RESPONSABLE', 'R2', '20260923214925442',
            '20260924191500000', 'Secretariat', 'Traite', NULL);
        -- Carl est sorti : sa fiche et celle de son unique responsable restent bloquees dans la file
        INSERT INTO COM_ELEVES VALUES ('3', 'PETIT', 'Carl', 'M', 'C2', '20260704');
        INSERT INTO COM_LIENER VALUES ('R3', '3', 'PS', '1', '1');
        INSERT INTO COM_RESPONSABLES (IDRESPONSABLE, RE_NOM1, RE_PRENOM1) VALUES ('R3', 'PETIT', 'Marc');
        INSERT INTO COM_JOURNAL_MODIF VALUES ('j3', 'Eleve_ATraiter', 'ELEVE', '3', '20260831132013848',
            '00000000000000000', 'Secretariat', 'En attente', NULL);
        INSERT INTO COM_JOURNAL_MODIF VALUES ('j4', 'Resp_ATraiter', 'RESPONSABLE', 'R3', '20260923215014259',
            '00000000000000000', 'Direction', 'En attente', NULL);
        -- annee scolaire test : T1 du 1er au 30 septembre 2026 ; sans classe : week-ends + mercredis
        INSERT INTO VS_TAB_PERIODES VALUES ('1', 'T1', '20260901', '20260930', '1');
        """
    )
    # jours sans classe de septembre 2026 : samedis, dimanches, mercredis (toute l'ecole = IDCLASSE 0)
    import datetime as dt
    j = dt.date(2026, 9, 1)
    while j <= dt.date(2026, 9, 30):
        if j.weekday() in (2, 5, 6):
            conn.execute("INSERT INTO VS_CONGE VALUES (?, '1', '0', ?)", (j.isoformat(), j.strftime("%Y%m%d")))
        j += dt.timedelta(days=1)
    # conge propre a la classe C2 : le 1er septembre
    conn.execute("INSERT INTO VS_CONGE VALUES ('c2', '1', 'C2', '20260901')")
    yield conn
    conn.close()


def test_liste_eleves_enseignants_et_anciennete(conn):
    eleves = {e["id_eleve"]: e for e in liste_eleves(conn)}
    assert eleves["1"]["enseignants"] == ["LEROY Anne", "MOREAU Luc"]
    assert eleves["2"]["enseignants"] == []
    assert eleves["1"]["premiere_annee"] == "2024-2025"
    assert eleves["1"]["nb_annees_precedentes"] == 2
    assert eleves["2"]["premiere_annee"] is None
    assert eleves["2"]["nb_annees_precedentes"] == 0


def test_anciennete_parcours_chronologique(conn):
    histo = anciennete_par_eleve(conn)["1"]
    assert [p["niveau"] for p in histo["parcours"]] == ["GS", "CP"]


def test_liste_personnels_classes(conn):
    pers = {p["id_personnel"]: p for p in liste_personnels(conn)}
    assert pers["P1"]["classes"] == ["CE1 A"]
    assert pers["P3"]["classes"] == []


def test_libelles_liens_depuis_tab_liens_avec_repli(conn):
    lib = libelles_liens(conn)
    assert lib["GM"] == "Grand-mère"      # TAB_LIENS
    assert lib["MS"] == "Mère"            # repli (code absent de la table de test)


def test_responsables_eleves_lien_libelle(conn):
    fiche = responsables_eleves(conn, id_eleve="1")[0]
    libelles = {r["lien"]: r["lien_libelle"] for r in fiche["responsables"]}
    assert libelles == {"PS": "Père", "GM": "Grand-mère"}


def test_modifications_en_attente_par_defaut(conn):
    import datetime as dt
    res = modifications_ecoledirecte_en_attente(conn, aujourd_hui=dt.date(2026, 10, 3))
    assert [m["fiche"] for m in res] == ["MARTIN Bob", "PETIT Carl", "PETIT Marc"]
    bob, carl, marc = res
    assert bob["classe"] == "CE1 B" and bob["modifie_le"] == "2026-08-31 13:18:48"
    assert bob["envoye_le"] is None and bob["motif_probable"] is None  # partira a la prochaine synchro
    assert carl["motif_probable"] == "eleve sorti le 2026-07-04 : hors perimetre de la synchro"
    assert marc["motif_probable"].startswith("aucun eleve actif rattache (sortie le 2026-07-04)")


def test_modifications_eleve_pas_encore_sorti(conn):
    import datetime as dt
    # avant la date de sortie, la fiche de Carl n'est pas bloquee
    res = modifications_ecoledirecte_en_attente(conn, aujourd_hui=dt.date(2026, 6, 1))
    assert all(m["motif_probable"] is None for m in res)


def test_modifications_tout_le_journal(conn):
    res = modifications_ecoledirecte_en_attente(conn, statut=None)
    assert [m["statut"] for m in res] == ["En attente", "En attente", "Traite", "En attente"]
    traite = next(m for m in res if m["statut"] == "Traite")
    assert traite["fiche"] == "BLANC Odile" and traite["envoye_le"] == "2026-09-24 19:15:00"


def test_jours_de_classe_septembre(conn):
    res = jours_de_classe(conn)
    # septembre 2026 : 30 jours, 4 samedis + 4 dimanches + 5 mercredis = 13 jours sans classe
    assert res["jours_par_mois"] == {"2026-09": 17}
    assert res["total"] == 17
    assert res["nb_jours_sans_classe"] == 13
    assert res["periodes"][0]["code"] == "T1"


def test_jours_de_classe_conge_propre_a_une_classe(conn):
    assert jours_de_classe(conn, id_classe="C2")["total"] == 16


def test_enrichissements_tolerent_les_tables_absentes():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE COM_ELEVES (IDELEVE TEXT, EL_NOM1 TEXT, EL_PRENOM1 TEXT, EL_SEXE TEXT,
            EL_IDCLASSE TEXT, EL_DATE_SORTIE TEXT);
        CREATE TABLE COM_CLASSES (IDCLASSE TEXT, CL_LIBELLE TEXT);
        INSERT INTO COM_ELEVES VALUES ('1', 'A', 'B', 'F', 'C1', NULL);
        """
    )
    e = liste_eleves(conn)[0]
    assert e["enseignants"] == [] and e["nb_annees_precedentes"] == 0
    assert modifications_ecoledirecte_en_attente(conn) == []
    assert jours_de_classe(conn) == {}
