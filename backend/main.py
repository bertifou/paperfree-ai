import os
import threading
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Depends, Query, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from passlib.context import CryptContext

from processor import process_document
from database import SessionLocal, Document, User, Setting

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./storage/uploads")
WATCH_DIR  = os.getenv("WATCH_DIR",  "./storage/watch")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WATCH_DIR,  exist_ok=True)

app = FastAPI(title="PaperFree-AI API", version="0.2.0")
security = HTTPBasic()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# CORS — autorise le frontend servi sur n'importe quel port local
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers DB & Auth
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
    if not user or not pwd_context.verify(credentials.password, user.hashed_password):
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
    return {"setup_required": not user_exists, "version": "0.2.0"}


@app.post("/setup")
def setup_admin(username: str, password: str, llm_url: str = "", db: Session = Depends(get_db)):
    if db.query(User).first():
        raise HTTPException(status_code=400, detail="Setup déjà effectué")

    db.add(User(username=username, hashed_password=pwd_context.hash(password)))
    db.add(Setting(key="llm_base_url", value=llm_url or os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")))
    db.add(Setting(key="llm_model",    value=os.getenv("LLM_MODEL", "local-model")))
    db.add(Setting(key="llm_api_key",  value=os.getenv("LLM_API_KEY", "lm-studio")))
    db.commit()
    return {"message": "Installation réussie"}

# ---------------------------------------------------------------------------
# Routes documents
# ---------------------------------------------------------------------------
@app.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    db_doc = Document(filename=file.filename, content=None, category=None, summary=None)
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    background_tasks.add_task(_run_processing, db_doc.id, file_path)
    return {"status": "processing", "doc_id": db_doc.id}


@app.get("/documents")
def list_documents(
    q: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Document)
    if q:
        query = query.filter(
            or_(Document.content.contains(q), Document.filename.contains(q), Document.category.contains(q))
        )
    return query.order_by(Document.created_at.desc()).all()


@app.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return doc


@app.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")

    # Supprimer le fichier physique si présent
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
# Routes paramètres
# ---------------------------------------------------------------------------
@app.get("/settings")
def get_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    settings = db.query(Setting).all()
    return {s.key: s.value for s in settings}


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
            db.commit()
    except Exception as e:
        print(f"[processor] Erreur doc {doc_id}: {e}")
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Watcher de dossier (thread daemon)
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
                print(f"[watcher] Nouveau fichier détecté : {fname}")
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
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
