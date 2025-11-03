# uploader.py
"""
Upload all Excel / CSV forecast files in ./forecasts to PostgreSQL.
Run locally, or in Colab (install dependencies there).
"""
import os
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@host:5432/dbname")
FORECAST_FOLDER = "forecasts"

def upload_file_to_db(filepath, engine):
    filename = os.path.basename(filepath)
    name_noext = os.path.splitext(filename)[0].lower().replace(" ", "_")
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(filepath)
        df.columns = [c.strip().replace(" ", "_").lower() for c in df.columns]
        table_name = name_noext
        df.to_sql(table_name, engine, if_exists="replace", index=False)
        print(f"Uploaded CSV {filename} -> {table_name} ({len(df)} rows)")
    else:
        # Excel: upload each sheet as a table
        xls = pd.read_excel(filepath, sheet_name=None)
        for sheet_name, df in xls.items():
            if df.empty:
                print(f"Skipping empty sheet {sheet_name} in {filename}")
                continue
            df.columns = [c.strip().replace(" ", "_").lower() for c in df.columns]
            table_name = f"{name_noext}_{sheet_name.strip().lower().replace(' ','_')}"
            df.to_sql(table_name, engine, if_exists="replace", index=False)
            print(f"Uploaded sheet {sheet_name} -> {table_name} ({len(df)} rows)")

def main():
    if not os.path.exists(FORECAST_FOLDER):
        print(f"Folder '{FORECAST_FOLDER}' not found. Create it and add files.")
        return
    engine = create_engine(DATABASE_URL)
    files = [f for f in os.listdir(FORECAST_FOLDER) if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    if not files:
        print("No forecast files found.")
        return
    for f in files:
        path = os.path.join(FORECAST_FOLDER, f)
        try:
            upload_file_to_db(path, engine)
        except Exception as e:
            print(f"Error uploading {f}: {e}")

if __name__ == "__main__":
    main()
