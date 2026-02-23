from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
import os

import os
_db_dir = os.getenv("DB_DIR", "./storage")
os.makedirs(_db_dir, exist_ok=True)
SQLALCHEMY_DATABASE_URL = f"sqlite:///{_db_dir}/paperfree.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    content = Column(Text, nullable=True)        # Texte brut OCR/PDF
    category = Column(String, nullable=True)     # Ex: Facture, Contrat...
    summary = Column(String, nullable=True)      # Résumé court LLM
    doc_date = Column(String, nullable=True)     # Date principale YYYY-MM-DD
    amount = Column(String, nullable=True)       # Montant avec devise
    issuer = Column(String, nullable=True)       # Organisme émetteur
    form_data = Column(Text, nullable=True)      # JSON: champs formulaire édités
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)


class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    value = Column(String)


Base.metadata.create_all(bind=engine)
