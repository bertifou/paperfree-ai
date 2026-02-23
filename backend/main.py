import os
import re
import threading
import logging
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Depends, Query, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pwdlib import PasswordHash

from processor import process_document
from database import SessionLocal, Document, User, Setting, EmailLog
import email_monitor

logger = logging.getLogger("uvicorn.access")

# ---------------------------------------------------------------------------
# Filtre de log — masque les valeurs sensibles dans les URLs
# ---------------------------------------------------------------------------
SENSITIVE_KEYS = {"email_password", "password", "llm_api_key", "token", "secret"}

class _SensitiveFilter(logging.Filter):
    _pattern = re.compile(
        r'((?:' + '|'.join(SENSITIVE_KEYS) + r')=)[^&\s"\']+ ',
        re.IGNORECASE
    )

    def _mask(self, text: str) -> str:
        return self._pattern.sub(r'\1*** ', text)

    def filter(self, record: logging.LogRecord) -> bool:
        # Masquer dans le message formaté final
        record.msg = self._mask(str(record.msg))
        # Masquer dans les args (tuples uvicorn : method, path, status...)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    self._mask(a) if isinstance(a, str) else a
                    for a in record.args
                )
            elif isinstance(record.args, str):
                record.args = self._mask(record.args)
        return True

# Appliquer à tous les loggers uvicorn
for _log_name in ("uvicorn.access", "uvicorn", "uvicorn.error", "fastapi"):
    logging.getLogger(_log_name).addFilter(_SensitiveFilter())

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./storage/uploads")
WATCH_DIR  = os.getenv("WATCH_DIR",  "./storage/watch")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WATCH_DIR,  exist_ok=True)

app = FastAPI(title="PaperFree-AI API", version="0.3.0")
security = HTTPBasic()
pwd_hasher = PasswordHash.recommended()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or not pwd_hasher.verify(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants incorrects",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user

# ---------------------------------------------------------------------------
# Routes publiques
# ---------------------------------------------------------------------------
@app.get("/status")
def get_status(db: Session = Depends(get_db)):
    user_exists = db.query(User).first() is not None
    return {"setup_required": not user_exists, "version": "0.3.0"}

@app.post("/setup")
def setup_admin(username: str, password: str, llm_url: str = "", db: Session = Depends(get_db)):
    if db.query(User).first():
        raise HTTPException(status_code=400, detail="Setup déjà effectué")
    db.add(User(username=username, hashed_password=pwd_hasher.hash(password)))
    db.add(Setting(key="llm_base_url", value=llm_url or os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")))
    db.add(Setting(key="llm_model",    value=os.getenv("LLM_MODEL", "local-model")))
    db.add(Setting(key="llm_api_key",  value=os.getenv("LLM_API_KEY", "lm-studio")))
    db.commit()
    return {"message": "Installation réussie"}

# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
@app.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    original_name = file.filename or "document"
    safe_name = re.sub(r'[^\w\.\-]', '_', original_name)
    if not safe_name:
        safe_name = "document"

    print(f"[upload] '{original_name}' → '{safe_name}' | type: {file.content_type}")

    # Éviter les collisions
    base, ext = os.path.splitext(safe_name)
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    counter = 1
    while os.path.exists(file_path):
        safe_name = f"{base}_{counter}{ext}"
        file_path = os.path.join(UPLOAD_DIR, safe_name)
        counter += 1

    content = await file.read()
    print(f"[upload] Taille : {len(content)} octets")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Fichier vide")

    with open(file_path, "wb") as f:
        f.write(content)

    db_doc = Document(filename=safe_name, content=None, category=None, summary=None)
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    print(f"[upload] Doc #{db_doc.id} créé, traitement en arrière-plan...")
    background_tasks.add_task(_run_processing, db_doc.id, file_path)
    return {"status": "processing", "doc_id": db_doc.id, "filename": safe_name}


# ---------------------------------------------------------------------------
# Routes documents
# ---------------------------------------------------------------------------
@app.get("/documents")
def list_documents(
    q: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Document)
    if q:
        query = query.filter(
            or_(Document.content.contains(q), Document.filename.contains(q),
                Document.category.contains(q), Document.issuer.contains(q),
                Document.summary.contains(q))
        )
    return query.order_by(Document.created_at.desc()).all()


@app.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return doc


@app.patch("/documents/{doc_id}/form")
def update_form_data(doc_id: int, form_data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    import json
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    doc.form_data = json.dumps(form_data, ensure_ascii=False)
    if "category" in form_data: doc.category = form_data["category"]
    if "doc_date"  in form_data: doc.doc_date  = form_data["doc_date"]
    if "amount"    in form_data: doc.amount    = form_data["amount"]
    if "issuer"    in form_data: doc.issuer    = form_data["issuer"]
    if "summary"   in form_data: doc.summary   = form_data["summary"]
    db.commit()
    return {"message": "Formulaire sauvegardé"}


@app.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    db.delete(doc)
    db.commit()
    return {"message": f"Document {doc_id} supprimé"}


@app.get("/documents/{doc_id}/file")
def download_document(doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier physique introuvable")
    return FileResponse(file_path, filename=doc.filename)


# ---------------------------------------------------------------------------
# Recherche
# ---------------------------------------------------------------------------
@app.get("/search")
def search_documents(
    q: str = Query(...),
    mode: str = Query("text"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    results = db.query(Document).filter(
        or_(
            Document.content.contains(q),
            Document.filename.contains(q),
            Document.category.contains(q),
            Document.issuer.contains(q),
            Document.summary.contains(q),
        )
    ).order_by(Document.created_at.desc()).limit(10).all()

    if mode == "text":
        return {"mode": "text", "results": results, "llm_answer": None}

    if not results:
        return {"mode": "llm", "results": [], "llm_answer": "Aucun document correspondant trouvé."}

    context_parts = []
    for doc in results:
        snippet = (doc.content or "")[:800]
        context_parts.append(
            f"[{doc.filename} | {doc.category} | {doc.doc_date} | {doc.issuer}]\n{snippet}"
        )

    try:
        from processor import get_llm_config
        from openai import OpenAI
        config = get_llm_config()
        client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
        response = client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": (
                    "Tu es un assistant qui aide à retrouver des informations dans des documents administratifs. "
                    "Réponds en français, de façon concise, uniquement à partir des documents fournis."
                )},
                {"role": "user", "content": f"Question : {q}\n\nDocuments :\n\n" + "\n\n---\n\n".join(context_parts)},
            ],
            temperature=0.2,
        )
        llm_answer = response.choices[0].message.content.strip()
    except Exception as e:
        llm_answer = f"Erreur LLM : {str(e)}"

    return {"mode": "llm", "results": results, "llm_answer": llm_answer}


# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------
@app.get("/settings")
def get_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {s.key: s.value for s in db.query(Setting).all()}

@app.post("/settings")
def update_setting(key: str, value: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting:
        setting.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.commit()
    return {"message": f"Paramètre '{key}' mis à jour"}


# ---------------------------------------------------------------------------
# Background processing
# ---------------------------------------------------------------------------
def _run_processing(doc_id: int, file_path: str):
    db = SessionLocal()
    try:
        text, analysis = process_document(file_path)
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.content  = text
            doc.category = analysis.get("category")
            doc.summary  = analysis.get("summary")
            doc.doc_date = analysis.get("date")
            doc.amount   = analysis.get("amount")
            doc.issuer   = analysis.get("issuer")
            db.commit()
            print(f"[processor] Doc #{doc_id} traité : {analysis.get('category')} — {analysis.get('summary')}")
    except Exception as e:
        print(f"[processor] Erreur doc {doc_id}: {e}")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Watcher de dossier
# ---------------------------------------------------------------------------
def _start_folder_watcher():
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if event.is_directory:
                    return
                fname = os.path.basename(event.src_path)
                ext = os.path.splitext(fname)[1].lower()
                if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
                    return
                print(f"[watcher] Nouveau fichier : {fname}")
                db = SessionLocal()
                try:
                    db_doc = Document(filename=fname, content=None, category=None, summary=None)
                    db.add(db_doc)
                    db.commit()
                    db.refresh(db_doc)
                    threading.Thread(target=_run_processing, args=(db_doc.id, event.src_path), daemon=True).start()
                finally:
                    db.close()

        observer = Observer()
        observer.schedule(_Handler(), WATCH_DIR, recursive=False)
        observer.start()
        print(f"[watcher] Surveillance active sur : {WATCH_DIR}")
    except Exception as e:
        print(f"[watcher] Impossible de démarrer : {e}")


threading.Thread(target=_start_folder_watcher, daemon=True).start()

# ---------------------------------------------------------------------------
# Démarrage du scheduler email
# ---------------------------------------------------------------------------
email_monitor.scheduler.start()


# ---------------------------------------------------------------------------
# Routes Email
# ---------------------------------------------------------------------------

def _get_email_creds(db: Session):
    """Lit host/user/password depuis la DB. Lève 400 si non configuré."""
    settings = {s.key: s.value for s in db.query(Setting).all()}
    host = settings.get("email_host", "")
    user = settings.get("email_user", "")
    pwd  = settings.get("email_password", "")
    if not (host and user and pwd):
        raise HTTPException(status_code=400, detail="Compte email non configuré. Allez dans Paramètres > Email.")
    return host, user, pwd, settings


@app.get("/email/test")
def test_email_connection(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Diagnostic complet de la connexion email."""
    settings = {s.key: s.value for s in db.query(Setting).all()}
    host = settings.get("email_host", "")
    user = settings.get("email_user", "")
    pwd  = settings.get("email_password", "")
    import oauth_microsoft
    oauth_ok = oauth_microsoft.is_oauth_configured()

    if not host:
        return {"ok": False, "error": "Serveur IMAP non configuré", "oauth": oauth_ok}
    if not user:
        return {"ok": False, "error": "Adresse email non configurée", "oauth": oauth_ok}
    if not pwd and not oauth_ok:
        return {"ok": False, "error": "Mot de passe manquant et OAuth2 non configuré", "oauth": oauth_ok}

    try:
        folders = email_monitor.list_folders(host, user, pwd)
        return {"ok": True, "folders_count": len(folders), "oauth": oauth_ok,
                "host": host, "user": user}
    except ValueError as e:
        return {"ok": False, "error": str(e), "oauth": oauth_ok}
    except Exception as e:
        return {"ok": False, "error": str(e), "oauth": oauth_ok}


@app.get("/email/folders")
def get_email_folders(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    host, user, pwd, _ = _get_email_creds(db)
    try:
        folders = email_monitor.list_folders(host, user, pwd)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur IMAP : {e}")
    return {"folders": folders}


@app.get("/email/messages")
def get_email_messages(
    folder: str = Query("INBOX"),
    limit: int  = Query(50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host, user, pwd, _ = _get_email_creds(db)
    messages = email_monitor.list_emails(host, user, pwd, folder=folder, limit=limit)
    return {"folder": folder, "messages": messages, "count": len(messages)}


@app.delete("/email/messages/{uid}")
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


@app.post("/email/messages/{uid}/move")
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
    db.add(EmailLog(action="move", uid=uid, folder=source_folder,
                    detail=destination_folder))
    db.commit()
    return {"message": f"Email {uid} déplacé vers {destination_folder}"}


@app.post("/email/messages/{uid}/read")
def mark_email_read(
    uid: str,
    folder: str = Query("INBOX"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host, user, pwd, _ = _get_email_creds(db)
    email_monitor.mark_as_read(host, user, pwd, uid=uid, folder=folder)
    return {"message": "Marqué comme lu"}


@app.post("/email/sync-attachments")
def sync_email_attachments(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Déclenche manuellement le téléchargement des pièces jointes."""
    host, user, pwd, settings = _get_email_creds(db)
    treated = settings.get("email_treated_folder", "PaperFree-Traité")
    folder  = settings.get("email_folder", "INBOX")

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


@app.post("/email/purge-promotional")
def purge_promotional(
    dry_run: bool    = Query(False),
    older_than_days: int = Query(-1, description="Âge minimum en jours (-1 = utiliser le setting)"),
    db: Session      = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Déclenche manuellement la purge des emails promotionnels."""
    host, user, pwd, settings = _get_email_creds(db)
    from processor import get_llm_config
    llm_config  = get_llm_config()
    folder      = settings.get("email_folder", "INBOX")
    promo_days  = older_than_days if older_than_days >= 0 else int(settings.get("email_promo_days", "7"))

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


@app.get("/email/logs")
def get_email_logs(
    limit: int = Query(100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logs = db.query(EmailLog).order_by(EmailLog.created_at.desc()).limit(limit).all()
    return logs


# ---------------------------------------------------------------------------
# Routes OAuth2 Microsoft
# ---------------------------------------------------------------------------

@app.get("/email/oauth/status")
def oauth_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Retourne l'état de la connexion OAuth2."""
    import oauth_microsoft
    configured  = bool(db.query(Setting).filter(Setting.key == "oauth_client_id", Setting.value != "").first())
    connected   = oauth_microsoft.is_oauth_configured()
    expires_at  = float(db.query(Setting).filter(Setting.key == "oauth_expires_at").first().value or 0
                        if db.query(Setting).filter(Setting.key == "oauth_expires_at").first() else 0)
    email_user  = db.query(Setting).filter(Setting.key == "email_user").first()
    return {
        "configured": configured,
        "connected":  connected,
        "expires_at": expires_at,
        "email_user": email_user.value if email_user else "",
    }


@app.get("/email/oauth/start")
def oauth_start(current_user: User = Depends(get_current_user)):
    """Lance le flux OAuth2 — redirige vers Microsoft login."""
    import oauth_microsoft
    try:
        auth_url, state = oauth_microsoft.build_auth_url()
        return RedirectResponse(auth_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/email/oauth/callback")
def oauth_callback(code: str = Query(None), state: str = Query(None),
                   error: str = Query(None), error_description: str = Query(None)):
    """Reçoit le code Microsoft, échange contre des tokens, ferme la popup."""
    import oauth_microsoft
    if error:
        html = f"""<html><body><script>
            window.opener && window.opener.postMessage({{type:'oauth_error', error:{json.dumps(error_description or error)}}}, '*');
            window.close();
        </script><p>Erreur : {error_description or error}</p></body></html>"""
        return HTMLResponse(html, status_code=400)
    try:
        tokens = oauth_microsoft.exchange_code_for_tokens(code, state)
        html = """<html><body><script>
            window.opener && window.opener.postMessage({type:'oauth_success'}, '*');
            window.close();
        </script><p>✅ Connexion réussie ! Vous pouvez fermer cette fenêtre.</p></body></html>"""
        return HTMLResponse(html)
    except Exception as e:
        html = f"""<html><body><script>
            window.opener && window.opener.postMessage({{type:'oauth_error', error:{json.dumps(str(e))}}}, '*');
            window.close();
        </script><p>Erreur : {e}</p></body></html>"""
        return HTMLResponse(html, status_code=400)


@app.post("/email/oauth/disconnect")
def oauth_disconnect(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Révoque et supprime les tokens OAuth stockés."""
    for key in ("oauth_access_token", "oauth_refresh_token", "oauth_expires_at", "oauth_token_type", "oauth_scope"):
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = ""
    db.commit()
    return {"message": "Déconnexion OAuth effectuée"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
