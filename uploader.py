# uploader.py
"""
Run locally (or in a one-off CI job). Uploads every Excel file in /forecasts
to PostgreSQL as separate tables. Table naming: <filename>_<sheetname>
"""

import os
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

DATABASE_URL = os.getenv("DATABASE_URL")  # or replace temporarily for local run
if not DATABASE_URL:
    raise RuntimeError("Set DATABASE_URL in your local env before running uploader.py")

FORECAST_FOLDER = "forecasts"

def sanitize_colnames(df):
    df.columns = [str(c).strip().replace(" ", "_").replace("-", "_").lower() for c in df.columns]
    return df

def upload_excel_to_postgres(file_path, engine):
    file_name = os.path.splitext(os.path.basename(file_path))[0].lower().replace(" ", "_")
    print(f"Processing {file_name}")
    excel_data = pd.read_excel(file_path, sheet_name=None)
    for sheet_name, df in excel_data.items():
        if df.empty:
            print(f" - skipping empty sheet {sheet_name}")
            continue
        df = sanitize_colnames(df)
        table_name = f"{file_name}_{sheet_name}".lower().replace(" ", "_")
        try:
            df.to_sql(table_name, engine, if_exists="replace", index=False)
            print(f" - uploaded {table_name} ({len(df)} rows)")
        except SQLAlchemyError as e:
            print(f" - DB error for {table_name}: {e}")

def main():
    if not os.path.exists(FORECAST_FOLDER):
        print("Create 'forecasts/' folder and place Excel files there")
        return
    engine = create_engine(DATABASE_URL)
    files = [f for f in os.listdir(FORECAST_FOLDER) if f.lower().endswith((".xlsx", ".xls"))]
    if not files:
        print("No excel files found in forecasts/")
        return
    for f in files:
        upload_excel_to_postgres(os.path.join(FORECAST_FOLDER, f), engine)
    print("Done uploading.")

if __name__ == "__main__":
    main()
