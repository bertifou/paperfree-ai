"""
api/oauth.py — Routes OAuth2 Microsoft et Google.
"""
import json
import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from database import Setting, User
from core.security import get_db, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/email/oauth", tags=["OAuth"])


# ---------------------------------------------------------------------------
# Statut global OAuth
# ---------------------------------------------------------------------------

@router.get("/status")
def oauth_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import oauth_microsoft, oauth_google

    def _setting(key):
        row = db.query(Setting).filter(Setting.key == key).first()
        return row.value if row else ""

    return {
        "microsoft": {
            "configured": bool(_setting("oauth_client_id")),
            "connected":  oauth_microsoft.is_oauth_configured(),
            "expires_at": float(_setting("oauth_expires_at") or 0),
            "email_user": _setting("email_user"),
        },
        "google": {
            "configured": bool(_setting("google_client_id")),
            "connected":  oauth_google.is_oauth_configured(),
            "expires_at": float(_setting("google_expires_at") or 0),
            "email_user": _setting("google_email_user"),
        },
    }


# ---------------------------------------------------------------------------
# Microsoft
# ---------------------------------------------------------------------------

@router.get("/start")
def oauth_start(current_user: User = Depends(get_current_user)):
    import oauth_microsoft
    try:
        auth_url, _ = oauth_microsoft.build_auth_url()
        return RedirectResponse(auth_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/callback")
def oauth_callback(
    code: str  = Query(None), state: str = Query(None),
    error: str = Query(None), error_description: str = Query(None),
):
    import oauth_microsoft
    if error:
        html = f"""<html><body><script>
            window.opener && window.opener.postMessage({{type:'oauth_error',provider:'microsoft',error:{json.dumps(error_description or error)}}}, '*');
            window.close();
        </script><p>Erreur : {error_description or error}</p></body></html>"""
        return HTMLResponse(html, status_code=400)
    try:
        oauth_microsoft.exchange_code_for_tokens(code, state)
        html = """<html><body><script>
            window.opener && window.opener.postMessage({type:'oauth_success',provider:'microsoft'}, '*');
            window.close();
        </script><p>✅ Connexion réussie ! Vous pouvez fermer cette fenêtre.</p></body></html>"""
        return HTMLResponse(html)
    except Exception as e:
        html = f"""<html><body><script>
            window.opener && window.opener.postMessage({{type:'oauth_error',provider:'microsoft',error:{json.dumps(str(e))}}}, '*');
            window.close();
        </script><p>Erreur : {e}</p></body></html>"""
        return HTMLResponse(html, status_code=400)


@router.post("/disconnect")
def oauth_disconnect(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    for key in ("oauth_access_token", "oauth_refresh_token", "oauth_expires_at", "oauth_token_type", "oauth_scope"):
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = ""
    db.commit()
    return {"message": "Déconnexion OAuth Microsoft effectuée"}


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------

@router.get("/google/start")
def oauth_google_start(current_user: User = Depends(get_current_user)):
    import oauth_google
    try:
        auth_url, _ = oauth_google.build_auth_url()
        return RedirectResponse(auth_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/google/callback")
def oauth_google_callback(
    code: str  = Query(None), state: str = Query(None),
    error: str = Query(None), error_description: str = Query(None),
):
    import oauth_google
    if error:
        html = f"""<html><body><script>
            window.opener && window.opener.postMessage({{type:'oauth_error',provider:'google',error:{json.dumps(error_description or error)}}}, '*');
            window.close();
        </script><p>Erreur : {error_description or error}</p></body></html>"""
        return HTMLResponse(html, status_code=400)
    try:
        result = oauth_google.exchange_code_for_tokens(code, state)
        email_user = result.get("email_user", "")
        html = f"""<html><body><script>
            window.opener && window.opener.postMessage({{type:'oauth_success',provider:'google',email:{json.dumps(email_user)}}}, '*');
            window.close();
        </script><p>✅ Compte Gmail connecté ({email_user}) ! Vous pouvez fermer cette fenêtre.</p></body></html>"""
        return HTMLResponse(html)
    except Exception as e:
        html = f"""<html><body><script>
            window.opener && window.opener.postMessage({{type:'oauth_error',provider:'google',error:{json.dumps(str(e))}}}, '*');
            window.close();
        </script><p>Erreur : {e}</p></body></html>"""
        return HTMLResponse(html, status_code=400)


@router.post("/google/disconnect")
def oauth_google_disconnect(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    for key in ("google_access_token", "google_refresh_token", "google_expires_at",
                "google_token_type", "google_scope", "google_email_user"):
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = ""
    db.commit()
    return {"message": "Déconnexion OAuth Google effectuée"}
