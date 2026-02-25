"""
main.py — Point d'entrée de l'application PaperFree-AI.

Ce fichier initialise l'app FastAPI avec tous les middlewares de sécurité,
enregistre les routers et démarre les services de fond (watcher, email scheduler).
"""
import threading
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import APP_VERSION, ALLOWED_ORIGINS
from core.logging_filter import apply_sensitive_filter
from core.middleware import SecurityHeadersMiddleware, setup_rate_limiting
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
app = FastAPI(
    title="PaperFree-AI API", 
    version=APP_VERSION,
    docs_url="/docs",  # Swagger UI
    redoc_url="/redoc"  # ReDoc
)

# ---------------------------------------------------------------------------
# Middlewares de sécurité
# ---------------------------------------------------------------------------

# 1. CORS restreint aux origines autorisées
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# 2. Headers de sécurité HTTP
app.add_middleware(SecurityHeadersMiddleware)

# 3. Rate limiting
limiter = setup_rate_limiting(app)

logger.info(f"✅ Security middlewares enabled:")
logger.info(f"   - CORS: {ALLOWED_ORIGINS}")
logger.info(f"   - Security Headers: Active")
logger.info(f"   - Rate Limiting: Active")

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
    logger.info(f"[app] 🚀 PaperFree-AI v{APP_VERSION} démarré")

_start_background_services()

# ---------------------------------------------------------------------------
# Entrée directe
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
