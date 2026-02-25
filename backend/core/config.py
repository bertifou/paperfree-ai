"""
core/config.py — Constantes et configuration globale de l'application.
"""
import os
from dotenv import load_dotenv

load_dotenv()

APP_VERSION = "0.4.0"

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./storage/uploads")
WATCH_DIR  = os.getenv("WATCH_DIR",  "./storage/watch")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WATCH_DIR,  exist_ok=True)
