"""
api/email.py — Routes de gestion email (IMAP, OAuth, logs, sync pièces jointes).
"""
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from database import Setting, User, EmailLog
from core.security import get_db, get_current_user
from core.config import UPLOAD_DIR
import email_monitor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/email", tags=["Email"])


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _get_email_creds(db: Session):
    """Lit host/user/password depuis la DB. Lève 400 si non configuré."""
    settings = {s.key: s.value for s in db.query(Setting).all()}
    host = settings.get("email_host", "")
    user = settings.get("email_user", "")
    pwd  = settings.get("email_password", "")
    if not host or not user:
        raise HTTPException(status_code=400, detail="Compte email non configuré. Allez dans Paramètres > Email.")
    if not pwd:
        import oauth_google, oauth_microsoft
        if not oauth_google.is_oauth_configured() and not oauth_microsoft.is_oauth_configured():
            raise HTTPException(status_code=400, detail="Mot de passe manquant et aucun OAuth2 configuré.")
    return host, user, pwd, settings


# ---------------------------------------------------------------------------
# Test connexion & dossiers
# ---------------------------------------------------------------------------

@router.get("/test")
def test_email_connection(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = {s.key: s.value for s in db.query(Setting).all()}
    host = settings.get("email_host", "")
    user = settings.get("email_user", "")
    pwd  = settings.get("email_password", "")
    import oauth_microsoft, oauth_google
    oauth_ok = oauth_microsoft.is_oauth_configured() or oauth_google.is_oauth_configured()

    if not host:
        return {"ok": False, "error": "Serveur IMAP non configuré", "oauth": oauth_ok}
    if not user:
        return {"ok": False, "error": "Adresse email non configurée", "oauth": oauth_ok}
    if not pwd and not oauth_ok:
        return {"ok": False, "error": "Mot de passe manquant et aucun OAuth2 configuré", "oauth": oauth_ok}

    try:
        folders = email_monitor.list_folders(host, user, pwd)
        return {"ok": True, "folders_count": len(folders), "oauth": oauth_ok, "host": host, "user": user}
    except ValueError as e:
        return {"ok": False, "error": str(e), "oauth": oauth_ok}
    except Exception as e:
        return {"ok": False, "error": str(e), "oauth": oauth_ok}


@router.get("/folders")
def get_email_folders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host, user, pwd, _ = _get_email_creds(db)
    try:
        folders = email_monitor.list_folders(host, user, pwd)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur IMAP : {e}")
    return {"folders": folders}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@router.get("/messages")
def get_email_messages(
    folder: str = Query("INBOX"),
    limit: int  = Query(50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host, user, pwd, _ = _get_email_creds(db)
    messages = email_monitor.list_emails(host, user, pwd, folder=folder, limit=limit)
    return {"folder": folder, "messages": messages, "count": len(messages)}


@router.delete("/messages/{uid}")
def delete_email_message(
    uid: str,
    folder: str = Query("INBOX"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host, user, pwd, _ = _get_email_creds(db)
    ok = email_monitor.delete_email(host, user, pwd, uid=uid, folder=folder)
    if not ok:
        raise HTTPException(status_code=500, detail="Erreur lors de la suppression")
    db.add(EmailLog(action="manual_delete", uid=uid, folder=folder))
    db.commit()
    return {"message": f"Email {uid} supprimé"}


@router.post("/messages/{uid}/move")
def move_email_message(
    uid: str,
    source_folder: str      = Query("INBOX"),
    destination_folder: str = Query("PaperFree-Traité"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host, user, pwd, _ = _get_email_creds(db)
    ok = email_monitor.move_email(host, user, pwd, uid=uid,
                                  source_folder=source_folder,
                                  destination_folder=destination_folder)
    if not ok:
        raise HTTPException(status_code=500, detail="Erreur lors du déplacement")
    db.add(EmailLog(action="move", uid=uid, folder=source_folder, detail=destination_folder))
    db.commit()
    return {"message": f"Email {uid} déplacé vers {destination_folder}"}


@router.post("/messages/{uid}/read")
def mark_email_read(
    uid: str,
    folder: str = Query("INBOX"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host, user, pwd, _ = _get_email_creds(db)
    email_monitor.mark_as_read(host, user, pwd, uid=uid, folder=folder)
    return {"message": "Marqué comme lu"}


# ---------------------------------------------------------------------------
# Sync & purge
# ---------------------------------------------------------------------------

@router.post("/sync-attachments")
def sync_email_attachments(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host, user, pwd, settings = _get_email_creds(db)
    treated = settings.get("email_treated_folder", "PaperFree-Traité")
    folder  = settings.get("email_folder", "INBOX")

    from database import SessionLocal

    def _run():
        downloaded = email_monitor.download_attachments(
            host, user, pwd, UPLOAD_DIR,
            folder=folder, treated_folder=treated,
        )
        if downloaded:
            email_monitor._trigger_processing(downloaded)
            inner_db = SessionLocal()
            try:
                for item in downloaded:
                    inner_db.add(EmailLog(
                        action="download_attachment",
                        uid=item["uid"], subject=item["subject"],
                        folder=folder, detail=item["filename"],
                    ))
                inner_db.commit()
            finally:
                inner_db.close()

    background_tasks.add_task(_run)
    return {"message": "Synchronisation des pièces jointes lancée en arrière-plan"}


@router.post("/purge-promotional")
def purge_promotional(
    dry_run: bool        = Query(False),
    older_than_days: int = Query(-1, description="Âge minimum en jours (-1 = utiliser le setting)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host, user, pwd, settings = _get_email_creds(db)
    from processor import get_llm_config
    llm_config = get_llm_config()
    folder     = settings.get("email_folder", "INBOX")
    promo_days = older_than_days if older_than_days >= 0 else int(settings.get("email_promo_days", "7"))

    report = email_monitor.purge_promotional_emails(
        host, user, pwd,
        llm_config=llm_config,
        folder=folder,
        older_than_days=promo_days,
        dry_run=dry_run,
    )
    if not dry_run and report["deleted"] > 0:
        db.add(EmailLog(action="purge_promo", detail=str(report)))
        db.commit()
    return report


@router.get("/logs")
def get_email_logs(
    limit: int = Query(100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logs = db.query(EmailLog).order_by(EmailLog.created_at.desc()).limit(limit).all()
    return logs
