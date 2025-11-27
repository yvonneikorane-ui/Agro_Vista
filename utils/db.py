# utils/db.py
import os
from sqlalchemy import create_engine

FALLBACK_PUBLIC_URL = "postgresql://postgres:DcYufJdqrTmSmAhRqRPgIAtODXcZHTqp@maglev.proxy.rlwy.net:34809/railway"

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_PUBLIC_URL") or FALLBACK_PUBLIC_URL

def get_engine():
    from sqlalchemy.exc import SQLAlchemyError
    try:
        engine = create_engine(DATABASE_URL)
        return engine
    except SQLAlchemyError as e:
        print(f"❌ Failed to create DB engine: {e}")
        return None
