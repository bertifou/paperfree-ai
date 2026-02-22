from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Depends, Query, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from sqlalchemy import or_
import os
from passlib.context import CryptContext
from processor import process_document
from database import SessionLocal, Document, User, Setting

app = FastAPI(title='PaperFree-AI API')
security = HTTPBasic()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

UPLOAD_DIR = '/a0/usr/projects/causal/storage/uploads'
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Dependency pour la DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Vérification de l'authentification
def get_current_user(credentials: HTTPBasicCredentials = Depends(security), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or not pwd_context.verify(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user

@app.get('/status')
def get_status(db: Session = Depends(get_db)):
    user_exists = db.query(User).first() is not None
    return {"setup_required": not user_exists}

@app.post('/setup')
def setup_admin(username: str, password: str, llm_url: str, db: Session = Depends(get_db)):
    if db.query(User).first():
        raise HTTPException(status_code=400, detail="Setup already completed")

    # Création utilisateur
    hashed_pw = pwd_context.hash(password)
    new_user = User(username=username, hashed_password=hashed_pw)
    db.add(new_user)

    # Configuration LLM par défaut
    db.add(Setting(key='llm_base_url', value=llm_url))
    db.add(Setting(key='llm_model', value='local-model'))
    db.add(Setting(key='llm_api_key', value='lm-studio'))

    db.commit()
    return {"message": "Setup successful"}

@app.post('/upload')
async def upload_document(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...), 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, 'wb') as f:
        f.write(await file.read())

    db_doc = Document(filename=file.filename, content="En cours de traitement...")
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    background_tasks.add_task(run_processing, db_doc.id, file_path)

    return {'status': 'Processing started', 'doc_id': db_doc.id}

@app.get('/documents')
def list_documents(q: str = Query(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(Document)
    if q:
        query = query.filter(or_(Document.content.contains(q), Document.filename.contains(q)))
    return query.all()

@app.get('/settings')
def get_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    settings = db.query(Setting).all()
    return {s.key: s.value for s in settings}

@app.post('/settings')
def update_setting(key: str, value: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting:
        setting.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.commit()
    return {"message": f"Setting {key} updated"}

def run_processing(doc_id, file_path):
    from database import SessionLocal, Document
    db = SessionLocal()
    try:
        text, analysis = process_document(file_path)
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.content = text
            doc.category = analysis
            db.commit()
    finally:
        db.close()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
