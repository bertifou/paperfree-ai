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
    pipeline_sources = Column(String, nullable=True)  # JSON: ["vision","ocr+llm"] ou null
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


class ClassificationRule(Base):
    """Règle de reclassification : une règle possède N conditions (toutes requises — AND)."""
    __tablename__ = "classification_rules"
    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String, nullable=False)   # Nom lisible
    target_category = Column(String, nullable=False)   # Catégorie cible
    priority        = Column(Integer, default=0)       # Plus grand = prioritaire
    enabled         = Column(String, default="true")   # 'true' | 'false'
    created_at      = Column(DateTime, default=datetime.datetime.utcnow)


class RuleCondition(Base):
    """Condition individuelle attachée à une ClassificationRule."""
    __tablename__ = "rule_conditions"
    id          = Column(Integer, primary_key=True, index=True)
    rule_id     = Column(Integer, nullable=False)      # FK → ClassificationRule.id
    match_field = Column(String, nullable=False)       # 'issuer'|'content'|'category'|'amount_not_null'
    match_value = Column(String, nullable=True)        # null pour les conditions sans valeur


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
    if "pipeline_sources" not in existing_cols:
        cur.execute("ALTER TABLE documents ADD COLUMN pipeline_sources TEXT")
        conn.commit()
    # Migration : tables classification_rules + rule_conditions
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='classification_rules'")
    rules_exists = cur.fetchone()
    if not rules_exists:
        cur.execute("""
            CREATE TABLE classification_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                target_category TEXT NOT NULL,
                priority INTEGER DEFAULT 0,
                enabled TEXT DEFAULT 'true',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    else:
        # Si l'ancienne structure monolithique existe (colonnes match_field/match_value), recréer proprement
        cur.execute("PRAGMA table_info(classification_rules)")
        old_cols = {row[1] for row in cur.fetchall()}
        if "match_field" in old_cols:
            # Sauvegarder les anciennes règles pour les migrer
            cur.execute("SELECT id, name, match_field, match_value, target_category, priority, enabled FROM classification_rules")
            old_rules = cur.fetchall()
            cur.execute("DROP TABLE classification_rules")
            cur.execute("""
                CREATE TABLE classification_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    target_category TEXT NOT NULL,
                    priority INTEGER DEFAULT 0,
                    enabled TEXT DEFAULT 'true',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Réinsérer les anciennes règles (sans les colonnes supprimées)
            for row in old_rules:
                cur.execute(
                    "INSERT INTO classification_rules (id, name, target_category, priority, enabled) VALUES (?,?,?,?,?)",
                    (row[0], row[1], row[4], row[5], row[6])
                )
            conn.commit()
            # Les conditions seront créées dans le bloc rule_conditions ci-dessous

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rule_conditions'")
    if not cur.fetchone():
        cur.execute("""
            CREATE TABLE rule_conditions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER NOT NULL,
                match_field TEXT NOT NULL,
                match_value TEXT
            )
        """)
        conn.commit()
        # Règle d'exemple si aucune règle n'existe encore
        cur.execute("SELECT COUNT(*) FROM classification_rules")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                INSERT INTO classification_rules (name, target_category, priority)
                VALUES ('Pharmacie → Impôts', 'Impôts', 10)
            """)
            rule_id = cur.lastrowid
            cur.execute("INSERT INTO rule_conditions (rule_id, match_field, match_value) VALUES (?, ?, ?)",
                        (rule_id, 'issuer', 'pharmacie'))
            cur.execute("INSERT INTO rule_conditions (rule_id, match_field, match_value) VALUES (?, ?, ?)",
                        (rule_id, 'amount_not_null', None))
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
    "ocr_llm_correction":         "true",
    "ocr_correction_threshold":   "80",
    # Vision
    "llm_vision_enabled":         "false",
    "llm_vision_provider":        "local",
    "llm_vision_model":           "",
    "llm_vision_api_key":         "",
    "llm_vision_base_url":        "",
    # Fusion double voie (vision activée)
    "ocr_vision_fusion":          "true",
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
