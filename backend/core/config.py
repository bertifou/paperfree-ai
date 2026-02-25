"""
core/config.py — Constantes et configuration globale de l'application.
"""
import os
import secrets
from dotenv import load_dotenv

load_dotenv()

APP_VERSION = "0.5.0"

# Stockage
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./storage/uploads")
WATCH_DIR  = os.getenv("WATCH_DIR",  "./storage/watch")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WATCH_DIR,  exist_ok=True)

# Sécurité JWT
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY == "changeme-please-generate-a-random-string":
    print("⚠️  WARNING: SECRET_KEY not set or using default value!")
    print("   Generate a secure key with: python -c 'import secrets; print(secrets.token_urlsafe(32))'")
    SECRET_KEY = secrets.token_urlsafe(32)  # Fallback temporaire

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30

# Sécurité uploads
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png", 
    "image/gif",
    "image/bmp",
    "image/tiff"
}

# Rate limiting
RATE_LIMIT_LOGIN = "5/minute"
RATE_LIMIT_UPLOAD = "20/minute"
RATE_LIMIT_API = "100/minute"

# CORS
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(",")
