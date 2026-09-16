import os
import sqlite3
import pandas as pd
from pathlib import Path

def build_consolidation_db(csv_directory, output_db_name="administration_consolidee.db"):
    source_dir = Path(csv_directory)
    db_path = source_dir / output_db_name
    
    # Remove existing database if restarting
    if db_path.exists():
        print(f"Removing old database at {db_path}...")
        db_path.unlink()
        
    print(f"Creating structured SQLite database: {db_path}")
    conn = sqlite3.connect(str(db_path))
    
    # Grab all CSV files in the directory
    csv_files = sorted(list(source_dir.glob("*.csv")))
    total_files = len(csv_files)
    print(f"Found {total_files} files for consolidation.\n" + "-"*50)
    
    success_count = 0
    skipped_count = 0

    for index, file_path in enumerate(csv_files, 1):
        table_name = file_path.stem 
        
        # Skip the output database if it accidentally triggers the loop
        if table_name == db_path.stem:
            continue
            
        try:
            # Load the CSV utilizing the 16-bit encoding required for this ERP
            df = pd.read_csv(
                file_path, 
                sep=',', 
                encoding='utf-16-le', 
                dtype=str, 
                on_bad_lines='skip'
            )
            
            # Check if the file only contains headers (0 data rows)
            if df.empty:
                print(f"[{index}/{total_files}] ⏭️ Skipping {table_name} (Empty / No entries)")
                skipped_count += 1
                continue
                
            print(f"[{index}/{total_files}] ✅ Loading {table_name} ({len(df)} rows)...")
            
            # Sanitize headers to remove any lingering quote artifacts
            df.columns = [col.strip().replace('"', '') for col in df.columns]
            
            # Push the clean dataframe into SQLite
            df.to_sql(table_name, con=conn, if_exists='replace', index=False)
            success_count += 1
            
        except pd.errors.EmptyDataError:
            # Handles files that are completely blank (0 bytes, not even headers)
            print(f"[{index}/{total_files}] ⏭️ Skipping {table_name} (0 byte file)")
            skipped_count += 1
        except Exception as e:
            print(f"[{index}/{total_files}] ❌ Error with {table_name}: {str(e)}")

    # Optimize the SQLite storage footprint
    print("-" * 50)
    print("Optimizing database structure...")
    conn.execute("VACUUM;") 
    conn.close()
    
    print("\n" + "="*50)
    print("CONSOLIDATION COMPLETE")
    print("="*50)
    print(f"✅ {success_count} populated tables successfully loaded.")
    print(f"⏭️ {skipped_count} empty tables skipped.")

if __name__ == "__main__":
    # '.' points to the current directory where the script is executed
    build_consolidation_db(".")
