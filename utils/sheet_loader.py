# utils/sheet_loader.py
import pandas as pd
from sqlalchemy import text
from utils.db import get_engine
from utils.cache import cache_get, cache_set

sheet_names = [
    "youth_women_empowerment_forecast",
    "Tractor_Registry_forecast",
    "National_Agro_Farmer_Mapping_Forecast",
    "Stakeholders_Partners_Forecast",
    "Knowledge_Innocvation_Tracker_Forecast",
    "Project_Overview_Forecast",
    "E_Voucher_Forecast",
    "Farmers_Registry_Forecast",
    "Investment_KPIs_Forecast",
    "Policy_Simulator_Forecast",
    "Rainified_Crops_Forecast",
    "Climate_Carbon_Credits_Forecast",
    "Yield_Food_Security_Forecast",
    "Input_Pest_Disease_Alert_Forecast"
]

def load_all_sheets():
    cache_key = "agrovista:all_sheets_v2"
    cached = cache_get(cache_key)
    if cached:
        try:
            df = pd.read_json(cached, orient="split")
            return df
        except Exception:
            pass

    engine = get_engine()
    if not engine:
        return pd.DataFrame()

    dfs = []

    def safe_select(conn, candidate):
        try_variants = [
            f'SELECT * FROM "{candidate}" LIMIT 10000',
            f'SELECT * FROM "{candidate.lower()}" LIMIT 10000',
            f'SELECT * FROM {candidate.lower()} LIMIT 10000'
        ]
        for q in try_variants:
            try:
                return pd.read_sql(text(q), conn)
            except Exception:
                continue
        return None

    with engine.connect() as conn:
        for s in sheet_names:
            cand_list = list(dict.fromkeys(filter(None, [
                s,
                s.lower(),
                s.lower().replace("_forecast", "") if s.lower().endswith("_forecast") else None,
                s.replace("_forecast", "") if s.endswith("_forecast") else None,
                s.replace(" ", "_").lower()
            ])))
            found = False
            for cand in cand_list:
                df = safe_select(conn, cand)
                if isinstance(df, pd.DataFrame):
                    df["Source_Sheet"] = s
                    dfs.append(df)
                    found = True
                    break
    df_all = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    try:
        cache_set(cache_key, df_all.to_json(orient="split"), expire=300)
    except Exception:
        pass
    return df_all
