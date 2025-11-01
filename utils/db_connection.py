import pandas as pd
from .db_connection import get_engine

def load_forecasts():
    engine = get_engine()
    tables = pd.read_sql(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'", 
        engine
    )
    
    all_forecasts = {}
    for _, row in tables.iterrows():
        table_name = row['table_name']
        df = pd.read_sql(f"SELECT * FROM {table_name}", engine)
        all_forecasts[table_name] = df

    return all_forecasts
