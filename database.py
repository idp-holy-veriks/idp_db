import time
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import os

POSTGRES_HOST=os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT=os.getenv("POSTGRES_PORT", 5432)
POSTGRES_USER=os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD=os.getenv("POSTGRES_PASSWORD", "postgres")
POSTGRES_DB=os.getenv("POSTGRES_DB", "idp")

if os.getenv("LOCAL") == "true":
    DATABASE_URL = "sqlite:///./test.db"
else:
    time.sleep(10)
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
