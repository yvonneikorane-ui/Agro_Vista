# uploader.py
import os
import pandas as pd
from sqlalchemy import create_engine

# === DATABASE URL ===
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # fallback for local testing
    DATABASE_URL = "postgresql://user:password@host:5432/dbname"

# === FOLDER PATH ===
FORECAST_FOLDER = os.path.join(os.path.dirname(__file__), "forecasts")

def upload_csv_to_postgres(file_path, engine):
    file_name = os.path.basename(file_path).replace(".csv", "")
    print(f"📘 Uploading {file_name}...")
    try:
        df = pd.read_csv(file_path)
        df.columns = [c.strip().replace(" ", "_").lower() for c in df.columns]
        df.to_sql(file_name.lower(), engine, if_exists="replace", index=False)
        print(f"✅ Uploaded {file_name} ({len(df)} rows)")
    except Exception as e:
        print(f"❌ Failed to upload {file_name}: {e}")

def main():
    if not os.path.exists(FORECAST_FOLDER):
        print(f"❌ Folder not found: {FORECAST_FOLDER}")
        return

    files = [f for f in os.listdir(FORECAST_FOLDER) if f.endswith(".csv")]
    if not files:
        print("⚠️ No CSV files found in forecasts/")
        return

    engine = create_engine(DATABASE_URL)
    for file in files:
        upload_csv_to_postgres(os.path.join(FORECAST_FOLDER, file), engine)

    print("\n🎯 ALL FORECAST FILES UPLOADED SUCCESSFULLY")

if __name__ == "__main__":
    main()

