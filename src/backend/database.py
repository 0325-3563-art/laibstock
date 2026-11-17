import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Load the .env that sits next to this file, wherever uvicorn is started from
load_dotenv(Path(__file__).parent / ".env")

DATABASE_URL = os.getenv("ASF_DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("ASF_DATABASE_URL is not set. Check your .env file.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()