import os
import re
import threading
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Depends, Query, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pwdlib import PasswordHash

from processor import process_document
from database import SessionLocal, Document, User, Setting

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
