import sqlite3
import pandas as pd
from pathlib import Path


def build_consolidation_db(
    csv_directory,
    ddl_path="Schema_DDL.sql",
    output_db_name="administration_consolidee.db",
    rebuild=True,
):
    """
    Construit la base SQLite consolidée en DEUX temps :
      1. création de la structure (toutes les tables) à partir du fichier DDL ;
      2. import des données de chaque CSV dans la table déjà créée.

    Les données sources sont les CSV : la base de sortie est un artefact
    reconstructible. `rebuild=True` supprime UNIQUEMENT la base de sortie
    avant reconstruction (jamais les CSV).
    """
    source_dir = Path(csv_directory)
    db_path = source_dir / output_db_name
    ddl_file = Path(ddl_path)

    if rebuild and db_path.exists():
        print(f"Suppression de l'ancienne base : {db_path}")
        db_path.unlink()

    print(f"Création de la base SQLite : {db_path}")
    conn = sqlite3.connect(str(db_path))

    # --- ÉTAPE 1 : créer la structure depuis le DDL --------------------------
    if not ddl_file.exists():
        raise FileNotFoundError(
            f"DDL introuvable : {ddl_file}. "
            "Place le fichier .sql à côté du script ou passe ddl_path=..."
        )
    print(f"Application du DDL : {ddl_file}")
    conn.executescript(ddl_file.read_text(encoding="utf-8"))
    predefined = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    print(f"  -> {len(predefined)} tables créées (structure vide).")
    print("-" * 60)

    # --- ÉTAPE 2 : importer les CSV -----------------------------------------
    csv_files = sorted(source_dir.glob("*.csv"))
    total = len(csv_files)
    print(f"{total} fichiers CSV à importer.")
    print("-" * 60)

    loaded = empty = created = realigned = 0

    for i, file_path in enumerate(csv_files, 1):
        table_name = file_path.stem
        if table_name == db_path.stem:
            continue
        try:
            df = pd.read_csv(
                file_path,
                sep=",",
                encoding="utf-16-le",
                dtype=str,
                on_bad_lines="skip",
            )
            df.columns = [c.strip().replace('"', "") for c in df.columns]

            if table_name in predefined:
                # Colonnes réelles de la table (ordre du DDL)
                table_cols = [
                    r[1] for r in conn.execute(
                        f'PRAGMA table_info("{table_name}")'
                    )
                ]
                extra = [c for c in df.columns if c not in table_cols]
                missing = [c for c in table_cols if c not in df.columns]

                if extra or missing:
                    realigned += 1
                    if extra:
                        print(f"    ⚠️  {table_name} : colonnes du CSV absentes "
                              f"du DDL, ignorées : {extra}")
                    if missing:
                        print(f"    ⚠️  {table_name} : colonnes du DDL absentes "
                              f"du CSV, mises à NULL : {missing}")

                # Réaligne sur la structure de la table (ordre + colonnes)
                df = df.reindex(columns=table_cols)

                if df.empty:
                    print(f"[{i}/{total}] ◻️  {table_name} : table vide "
                          f"(structure conservée)")
                    empty += 1
                    continue

                df.to_sql(table_name, conn, if_exists="append", index=False)
                print(f"[{i}/{total}] ✅ {table_name} ({len(df)} lignes)")
                loaded += 1
            else:
                # CSV sans table prévue dans le DDL : création automatique
                if df.empty:
                    print(f"[{i}/{total}] ⏭️  {table_name} (hors DDL, vide)")
                    empty += 1
                    continue
                df.to_sql(table_name, conn, if_exists="replace", index=False)
                print(f"[{i}/{total}] ➕ {table_name} ({len(df)} lignes, "
                      f"créée hors DDL)")
                created += 1

        except pd.errors.EmptyDataError:
            print(f"[{i}/{total}] ◻️  {table_name} (fichier 0 octet)")
            empty += 1
        except Exception as e:
            print(f"[{i}/{total}] ❌ {table_name} : {e}")

    print("-" * 60)
    print("Optimisation (VACUUM)...")
    conn.execute("VACUUM;")
    conn.close()

    print("\n" + "=" * 60)
    print("CONSOLIDATION TERMINÉE")
    print("=" * 60)
    print(f"✅ {loaded} tables chargées avec données")
    print(f"◻️  {empty} tables vides (structure conservée)")
    if created:
        print(f"➕ {created} tables créées hors DDL")
    if realigned:
        print(f"⚠️  {realigned} tables réalignées (écarts CSV/DDL signalés ci-dessus)")


if __name__ == "__main__":
    build_consolidation_db(".")
