# app/utils/celery_db_helper.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

def get_celery_db_session() -> Session:
    """
    Creates a synchronous database session specifically for Celery tasks.
    This always returns an actual Session instance, not a sessionmaker.
    """
    db_user = os.getenv("TIMESCALEDB_USER", "tradmin")
    db_password = os.getenv("TIMESCALEDB_PASSWORD", "tradpass")
    db_host = os.getenv("TIMESCALEDB_HOST", "timescaledb")
    db_port = os.getenv("TIMESCALEDB_PORT", "5432")
    db_name = os.getenv("TIMESCALEDB_DB", "tradingdb")
    
    database_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Return an actual Session instance, not the sessionmaker
    return SessionLocal()