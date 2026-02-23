"""
oauth_microsoft.py — Authentification OAuth2 Microsoft pour IMAP
Utilise le flux Authorization Code avec PKCE pour les comptes personnels Hotmail/Outlook.

Flux :
  1. GET  /email/oauth/start      → redirige vers Microsoft login
  2. GET  /email/oauth/callback   → reçoit le code, échange contre tokens, stocke en DB
  3. Le scheduler utilise get_valid_access_token() qui rafraîchit automatiquement si expiré

Prérequis Azure :
  - App enregistrée sur portal.azure.com
  - Type : comptes Microsoft personnels
  - URI redirection : http://<votre-host>:8000/email/oauth/callback
  - Scopes : https://outlook.office.com/IMAP.AccessAsUser.All offline_access
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config OAuth2 Microsoft
# ---------------------------------------------------------------------------
MICROSOFT_TENANT   = "consumers"   # comptes personnels Hotmail/Outlook
AUTHORITY          = f"https://login.microsoftonline.com/{MICROSOFT_TENANT}"
AUTH_ENDPOINT      = f"{AUTHORITY}/oauth2/v2.0/authorize"
TOKEN_ENDPOINT     = f"{AUTHORITY}/oauth2/v2.0/token"

SCOPES = [
    "https://outlook.office.com/IMAP.AccessAsUser.All",
    "offline_access",   # nécessaire pour obtenir le refresh_token
]

# Stockage temporaire du code_verifier PKCE entre /start et /callback
_pkce_store: dict[str, str] = {}   # state → code_verifier


# ---------------------------------------------------------------------------
# Helpers PKCE
# ---------------------------------------------------------------------------

def _generate_pkce() -> tuple[str, str]:
    """Retourne (code_verifier, code_challenge)."""
    code_verifier  = secrets.token_urlsafe(64)
    digest         = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


# ---------------------------------------------------------------------------
# Lecture config depuis DB
# ---------------------------------------------------------------------------

def get_oauth_config() -> dict:
    """Lit client_id, client_secret et redirect_uri depuis la DB."""
    try:
        from database import SessionLocal, Setting
        db = SessionLocal()
        settings = {s.key: s.value for s in db.query(Setting).all()}
        db.close()
        return {
            "client_id":     settings.get("oauth_client_id", ""),
            "client_secret": settings.get("oauth_client_secret", ""),
            "redirect_uri":  settings.get("oauth_redirect_uri",
                                          "http://localhost:8000/email/oauth/callback"),
        }
    except Exception as e:
        logger.error(f"[oauth] Erreur lecture config: {e}")
        return {}


# ---------------------------------------------------------------------------
# Étape 1 : Générer l'URL d'autorisation
# ---------------------------------------------------------------------------

def build_auth_url() -> tuple[str, str]:
    """
    Construit l'URL de redirection Microsoft.
    Retourne (auth_url, state) — state doit être mémorisé pour valider le callback.
    """
    cfg = get_oauth_config()
    if not cfg.get("client_id"):
        raise ValueError("OAuth2 non configuré : client_id manquant dans les paramètres.")

    state          = secrets.token_urlsafe(16)
    code_verifier, code_challenge = _generate_pkce()
    _pkce_store[state] = code_verifier  # mémoriser pour le callback

    params = {
        "client_id":             cfg["client_id"],
        "response_type":         "code",
        "redirect_uri":          cfg["redirect_uri"],
        "response_mode":         "query",
        "scope":                 " ".join(SCOPES),
        "state":                 state,
        "code_challenge":        code_challenge,
        "code_challenge_method": "S256",
    }
    url = AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)
    logger.info(f"[oauth] Auth URL générée (state={state})")
    return url, state


# ---------------------------------------------------------------------------
# Étape 2 : Échanger le code contre des tokens
# ---------------------------------------------------------------------------

def exchange_code_for_tokens(code: str, state: str) -> dict:
    """
    Reçoit le code de callback, échange contre access_token + refresh_token.
    Stocke les tokens dans la DB.
    Retourne le dict de tokens.
    """
    cfg = get_oauth_config()
    code_verifier = _pkce_store.pop(state, None)
    if not code_verifier:
        raise ValueError(f"State OAuth invalide ou expiré : {state}")

    data = {
        "client_id":     cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "code":          code,
        "redirect_uri":  cfg["redirect_uri"],
        "grant_type":    "authorization_code",
        "code_verifier": code_verifier,
        "scope":         " ".join(SCOPES),
    }

    resp = requests.post(TOKEN_ENDPOINT, data=data, timeout=15)
    resp.raise_for_status()
    tokens = resp.json()

    if "error" in tokens:
        raise ValueError(f"Erreur token Microsoft : {tokens.get('error_description', tokens['error'])}")

    _store_tokens(tokens)
    logger.info("[oauth] Tokens obtenus et stockés avec succès")
    return tokens


# ---------------------------------------------------------------------------
# Étape 3 : Rafraîchir le token
# ---------------------------------------------------------------------------

def refresh_access_token() -> str:
    """
    Utilise le refresh_token pour obtenir un nouvel access_token.
    Retourne le nouvel access_token.
    """
    cfg           = get_oauth_config()
    refresh_token = _load_setting("oauth_refresh_token")

    if not refresh_token:
        raise ValueError("Aucun refresh_token stocké — re-authentifiez via /email/oauth/start")

    data = {
        "client_id":     cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": refresh_token,
        "grant_type":    "refresh_token",
        "scope":         " ".join(SCOPES),
    }

    resp = requests.post(TOKEN_ENDPOINT, data=data, timeout=15)
    resp.raise_for_status()
    tokens = resp.json()

    if "error" in tokens:
        raise ValueError(f"Refresh token invalide : {tokens.get('error_description', tokens['error'])}")

    _store_tokens(tokens)
    logger.info("[oauth] Access token rafraîchi")
    return tokens["access_token"]


# ---------------------------------------------------------------------------
# Accès au token valide (avec refresh automatique)
# ---------------------------------------------------------------------------

def get_valid_access_token() -> tuple[str, str]:
    """
    Retourne (access_token, email_user) prêts à l'emploi.
    Rafraîchit automatiquement si le token est expiré ou expire dans < 5 min.
    """
    access_token = _load_setting("oauth_access_token")
    expires_at   = float(_load_setting("oauth_expires_at") or "0")
    email_user   = _load_setting("email_user") or ""

    now = time.time()
    if not access_token or now >= expires_at - 300:
        logger.info("[oauth] Token expiré ou absent → rafraîchissement")
        access_token = refresh_access_token()

    return access_token, email_user


def is_oauth_configured() -> bool:
    """Vérifie si OAuth2 est configuré et qu'un refresh_token est disponible."""
    return bool(
        _load_setting("oauth_client_id") and
        _load_setting("oauth_refresh_token")
    )


# ---------------------------------------------------------------------------
# Connexion IMAP via OAuth2 (XOAUTH2)
# ---------------------------------------------------------------------------

def connect_imap_oauth(host: str, user: str, access_token: str, port: int = 993):
    """
    Connexion IMAP en utilisant XOAUTH2 au lieu de LOGIN basique.
    Retourne une instance imaplib.IMAP4_SSL authentifiée.
    """
    import imaplib
    import base64

    auth_string = f"user={user}\x01auth=Bearer {access_token}\x01\x01"
    auth_bytes  = base64.b64encode(auth_string.encode()).decode()

    mail = imaplib.IMAP4_SSL(host, port)
    mail.authenticate("XOAUTH2", lambda x: auth_bytes)
    logger.info(f"[oauth] Connexion IMAP XOAUTH2 réussie : {user}@{host}")
    return mail


# ---------------------------------------------------------------------------
# Helpers DB
# ---------------------------------------------------------------------------

def _store_tokens(tokens: dict):
    """Persiste les tokens OAuth dans la table Setting."""
    from database import SessionLocal, Setting

    expires_at = str(time.time() + tokens.get("expires_in", 3600))
    to_save = {
        "oauth_access_token":  tokens.get("access_token", ""),
        "oauth_refresh_token": tokens.get("refresh_token", ""),
        "oauth_expires_at":    expires_at,
        "oauth_token_type":    tokens.get("token_type", "Bearer"),
        "oauth_scope":         tokens.get("scope", ""),
    }
    db = SessionLocal()
    try:
        for key, value in to_save.items():
            setting = db.query(Setting).filter(Setting.key == key).first()
            if setting:
                setting.value = value
            else:
                db.add(Setting(key=key, value=value))
        db.commit()
    finally:
        db.close()


def _load_setting(key: str) -> str:
    """Lit une valeur depuis la table Setting."""
    try:
        from database import SessionLocal, Setting
        db = SessionLocal()
        row = db.query(Setting).filter(Setting.key == key).first()
        db.close()
        return row.value if row else ""
    except Exception:
        return ""
