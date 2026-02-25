"""
main.py — Point d'entrée de l'application PaperFree-AI.

Ce fichier est volontairement minimal : il initialise l'app FastAPI,
enregistre les routers et démarre les services de fond (watcher, email scheduler).
Toute la logique métier est dans api/ et services/.
"""
import threading
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import APP_VERSION
from core.logging_filter import apply_sensitive_filter
from api.auth      import router as auth_router
from api.documents import router as documents_router
from api.settings  import router as settings_router
from api.email     import router as email_router
from api.oauth     import router as oauth_router

import email_monitor

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
apply_sensitive_filter()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(title="PaperFree-AI API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(settings_router)
app.include_router(email_router)
app.include_router(oauth_router)

# ---------------------------------------------------------------------------
# Démarrage des services de fond
# ---------------------------------------------------------------------------
def _start_background_services():
    from services.watcher import start_folder_watcher
    threading.Thread(target=start_folder_watcher, daemon=True).start()
    email_monitor.scheduler.start()
    logger.info(f"[app] PaperFree-AI v{APP_VERSION} démarré")

_start_background_services()

# ---------------------------------------------------------------------------
# Entrée directe
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
