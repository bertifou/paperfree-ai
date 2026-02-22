from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
import os
from processor import process_document
from database import SessionLocal, Document

app = FastAPI(title='PaperFree-AI API')

UPLOAD_DIR = '/a0/usr/projects/causal/storage/uploads'
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Dependency pour la DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get('/')
def read_root():
    return {'message': 'PaperFree-AI Backend is running'}

@app.post('/upload')
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, 'wb') as f:
        f.write(await file.read())

    db_doc = Document(filename=file.filename, content="En cours de traitement...")
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    background_tasks.add_task(run_processing, db_doc.id, file_path)

    return {'status': 'Processing started', 'doc_id': db_doc.id}

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

@app.get('/documents')
def list_documents(q: str = Query(None), db: Session = Depends(get_db)):
    if q:
        return db.query(Document).filter(or_(Document.content.contains(q), Document.filename.contains(q))).all()
    return db.query(Document).all()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
