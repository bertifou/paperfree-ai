"""
core/middleware.py — Middleware de sécurité HTTP headers et rate limiting.
"""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
import logging

logger = logging.getLogger(__name__)

# Rate limiter global
limiter = Limiter(key_func=get_remote_address)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Ajoute les headers de sécurité HTTP à toutes les réponses.
    
    Les fichiers servis via /files/ autorisent l'intégration en iframe
    depuis la même origine (pour l'aperçu PDF intégré dans l'UI).
    """

    # Préfixes/suffixes de routes où les fichiers sont servis dans une iframe
    # /files/, /static/ : fichiers statiques
    # /documents/{id}/file et /documents/{id}/pdf : aperçus inline
    _EMBEDDABLE_PREFIXES = ("/files/", "/static/")
    _EMBEDDABLE_SUFFIXES = ("/file", "/pdf")

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        path = request.url.path
        is_embeddable = (
            any(path.startswith(p) for p in self._EMBEDDABLE_PREFIXES)
            or any(path.endswith(s) for s in self._EMBEDDABLE_SUFFIXES)
        )

        # Headers communs à toutes les réponses
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        if is_embeddable:
            # Autorise l'intégration en iframe depuis la même origine uniquement
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; "
                "font-src 'self'; "
                "connect-src 'self'; "
                "frame-ancestors 'self';"
            )
        else:
            # Bloque toute intégration en iframe pour les autres routes
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; "
                "font-src 'self'; "
                "connect-src 'self'; "
                "frame-ancestors 'none';"
            )

        return response


def setup_rate_limiting(app):
    """Configure le rate limiting sur l'application."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    return limiter
