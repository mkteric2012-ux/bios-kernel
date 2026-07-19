import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./kernel.db")

# Algunos hosts (Render incluido) dan la URL de Postgres con el prefijo antiguo "postgres://".
# SQLAlchemy 1.4+ solo acepta "postgresql://". Se normaliza aqui para que copiar/pegar la URL
# del host funcione sin que un no-programador tenga que editarla a mano.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass
