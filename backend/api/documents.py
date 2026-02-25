"""
api/documents.py — Routes CRUD documents, upload et recherche.
"""
import os
import re
import json
import logging

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends, Query, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_

from database import Document, User
from core.security import get_db, get_current_user
from core.config import UPLOAD_DIR
from services.processing import run_processing

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Documents"])


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@router.post("/upload")
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

    logger.info(f"[upload] '{original_name}' → '{safe_name}' | type: {file.content_type}")

    base, ext = os.path.splitext(safe_name)
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    counter = 1
    while os.path.exists(file_path):
        safe_name = f"{base}_{counter}{ext}"
        file_path = os.path.join(UPLOAD_DIR, safe_name)
        counter += 1

    content = await file.read()
    logger.info(f"[upload] Taille : {len(content)} octets")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Fichier vide")

    with open(file_path, "wb") as f:
        f.write(content)

    db_doc = Document(filename=safe_name, content=None, category=None, summary=None)
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    logger.info(f"[upload] Doc #{db_doc.id} créé, traitement en arrière-plan...")
    background_tasks.add_task(run_processing, db_doc.id, file_path)
    return {"status": "processing", "doc_id": db_doc.id, "filename": safe_name}


# ---------------------------------------------------------------------------
# Liste et détail
# ---------------------------------------------------------------------------

@router.get("/documents")
def list_documents(
    q: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Document)
    if q:
        query = query.filter(
            or_(
                Document.content.contains(q),
                Document.filename.contains(q),
                Document.category.contains(q),
                Document.issuer.contains(q),
                Document.summary.contains(q),
            )
        )
    return query.order_by(Document.created_at.desc()).all()


@router.get("/documents/{doc_id}")
def get_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return doc


# ---------------------------------------------------------------------------
# Modification
# ---------------------------------------------------------------------------

@router.patch("/documents/{doc_id}/form")
def update_form_data(
    doc_id: int,
    form_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------

@router.delete("/documents/{doc_id}")
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    if doc.pdf_filename:
        pdf_path = os.path.join(UPLOAD_DIR, doc.pdf_filename)
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
    db.delete(doc)
    db.commit()
    return {"message": f"Document {doc_id} supprimé"}


# ---------------------------------------------------------------------------
# Téléchargement fichiers
# ---------------------------------------------------------------------------

@router.get("/documents/{doc_id}/file")
def download_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier physique introuvable")
    return FileResponse(file_path, filename=doc.filename)


@router.get("/documents/{doc_id}/pdf")
def get_document_pdf(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    if not doc.pdf_filename:
        raise HTTPException(status_code=404, detail="Aucun PDF généré pour ce document")
    pdf_path = os.path.join(UPLOAD_DIR, doc.pdf_filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Fichier PDF introuvable")
    return FileResponse(pdf_path, filename=doc.pdf_filename, media_type="application/pdf")


# ---------------------------------------------------------------------------
# Recherche
# ---------------------------------------------------------------------------

@router.get("/search")
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
