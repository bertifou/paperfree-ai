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
    pdf_filename = Column(String, nullable=True) # PDF généré si entrée = image
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


class EmailLog(Base):
    """Historique des actions automatiques du module email."""
    __tablename__ = "email_logs"
    id         = Column(Integer, primary_key=True, index=True)
    action     = Column(String, nullable=False)   # download_attachment | delete_promo | manual_delete | move
    uid        = Column(String, nullable=True)    # UID IMAP du message
    subject    = Column(String, nullable=True)
    sender     = Column(String, nullable=True)
    folder     = Column(String, nullable=True)
    detail     = Column(Text,   nullable=True)    # JSON supplémentaire
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


Base.metadata.create_all(bind=engine)

# Migration légère : ajouter les colonnes manquantes si la DB existait déjà
def _run_migrations():
    import sqlite3
    conn = sqlite3.connect(SQLALCHEMY_DATABASE_URL.replace("sqlite:///", ""))
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(documents)")
    existing_cols = {row[1] for row in cur.fetchall()}
    if "pdf_filename" not in existing_cols:
        cur.execute("ALTER TABLE documents ADD COLUMN pdf_filename TEXT")
        conn.commit()
    conn.close()

_run_migrations()


# ---------------------------------------------------------------------------
# Valeurs par défaut des settings email (insérées si absentes)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Valeurs par défaut des settings OCR / Vision
# ---------------------------------------------------------------------------
OCR_VISION_DEFAULTS = {
    # Correction OCR par LLM
    "ocr_llm_correction":         "true",   # Activer la correction LLM du texte OCR
    "ocr_correction_threshold":   "80",     # Score confiance (%) sous lequel on corrige toujours
    # Vision
    "llm_vision_enabled":         "false",  # Activer l'analyse par vision (image → LLM multimodal)
    "llm_vision_provider":        "local",  # local | openai | anthropic
    "llm_vision_model":           "",       # Vide = utiliser le modèle principal
    "llm_vision_api_key":         "",       # Clé API si provider externe
    "llm_vision_base_url":        "",       # URL si provider local différent du LLM principal
}

EMAIL_DEFAULTS = {
    "email_host":                  "",
    "email_user":                  "",
    "email_password":              "",
    "email_folder":                "INBOX",
    "email_treated_folder":        "PaperFree-Traité",
    "email_attach_interval_min":   "15",
    "email_purge_interval_hours":  "24",
    "email_promo_days":            "7",
    "email_enabled":               "false",
    # OAuth2 Microsoft
    "oauth_client_id":             "",
    "oauth_client_secret":         "",
    "oauth_redirect_uri":          "http://localhost:8000/email/oauth/callback",
    "oauth_access_token":          "",
    "oauth_refresh_token":         "",
    "oauth_expires_at":            "0",
    "oauth_token_type":            "",
    "oauth_scope":                 "",
    # OAuth2 Google
    "google_client_id":            "",
    "google_client_secret":        "",
    "google_redirect_uri":         "http://localhost:8000/email/oauth/google/callback",
    "google_access_token":         "",
    "google_refresh_token":        "",
    "google_expires_at":           "0",
    "google_token_type":           "",
    "google_scope":                "",
    "google_email_user":           "",
}

def init_email_defaults():
    db = SessionLocal()
    try:
        for key, value in {**OCR_VISION_DEFAULTS, **EMAIL_DEFAULTS}.items():
            if not db.query(Setting).filter(Setting.key == key).first():
                db.add(Setting(key=key, value=value))
        db.commit()
    finally:
        db.close()

init_email_defaults()
