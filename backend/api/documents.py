"""
api/documents.py — Routes CRUD documents, upload et recherche.
"""
import os
import re
import json
import logging

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends, Query, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel

from database import Document, User
from core.security import get_db, get_current_user, log_security_event, create_file_token, verify_file_token
from core.config import UPLOAD_DIR
from core.validators import validate_file_upload, validate_file_content, sanitize_filename
from core.middleware import limiter
from services.processing import run_processing

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Documents"])


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class FormDataUpdate(BaseModel):
    category: str = None
    doc_date: str = None
    amount: str = None
    issuer: str = None
    summary: str = None


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@router.post("/upload")
@limiter.limit("20/minute")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload d'un document avec validation de sécurité.
    Limité à 20 uploads/minute par IP.
    """
    # Validation avant lecture du contenu
    validate_file_upload(file)
    
    # Lecture et validation du contenu
    content = await file.read()
    await validate_file_content(file, content)
    
    # Nom de fichier sécurisé
    original_name = file.filename or "document"
    safe_name = sanitize_filename(original_name)
    
    logger.info(f"[upload] User={current_user.username} | '{original_name}' → '{safe_name}' | size={len(content)} bytes | type={file.content_type}")

    # Gestion des doublons
    base, ext = os.path.splitext(safe_name)
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    counter = 1
    while os.path.exists(file_path):
        safe_name = f"{base}_{counter}{ext}"
        file_path = os.path.join(UPLOAD_DIR, safe_name)
        counter += 1

    # Sauvegarde sécurisée
    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        logger.error(f"[upload] Failed to write file: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'écriture du fichier")

    # Création de l'entrée DB
    db_doc = Document(filename=safe_name, content=None, category=None, summary=None)
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    logger.info(f"[upload] Doc #{db_doc.id} créé, traitement en arrière-plan...")
    log_security_event("DOCUMENT_UPLOADED", {"doc_id": db_doc.id, "filename": safe_name, "user": current_user.username}, request)
    
    background_tasks.add_task(run_processing, db_doc.id, file_path)
    return {"status": "processing", "doc_id": db_doc.id, "filename": safe_name}


# ---------------------------------------------------------------------------
# Liste et détail
# ---------------------------------------------------------------------------

@router.get("/documents")
@limiter.limit("100/minute")
def list_documents(
    request: Request,
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
@limiter.limit("50/minute")
def update_form_data(
    request: Request,
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
    
    log_security_event("DOCUMENT_UPDATED", {"doc_id": doc_id, "user": current_user.username}, request)
    return {"message": "Formulaire sauvegardé"}


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------

@router.delete("/documents/{doc_id}")
@limiter.limit("30/minute")
def delete_document(
    request: Request,
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    
    # Suppression des fichiers
    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    if doc.pdf_filename:
        pdf_path = os.path.join(UPLOAD_DIR, doc.pdf_filename)
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
    
    db.delete(doc)
    db.commit()
    
    log_security_event("DOCUMENT_DELETED", {"doc_id": doc_id, "filename": doc.filename, "user": current_user.username}, request)
    return {"message": f"Document {doc_id} supprimé"}


# ---------------------------------------------------------------------------
# Téléchargement fichiers
# ---------------------------------------------------------------------------

@router.get("/documents/{doc_id}/file-token")
def get_file_token(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Génère un token signé 60s pour accéder au fichier sans header Authorization.
    Utilisé par le frontend pour construire l'URL de l'<iframe>.
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    token = create_file_token(doc_id=doc_id, username=current_user.username)
    return {"token": token, "expires_in": 60}


@router.get("/documents/{doc_id}/file")
def download_document(
    doc_id: int,
    token: str = Query(None),
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
):
    """
    Sert le fichier original. Accepte :
    - Bearer JWT dans Authorization (téléchargement classique)
    - ?token= signé (aperçu iframe, téléchargement mobile)
    """
    if token:
        verify_file_token(token, doc_id)
    elif credentials:
        from core.security import verify_token
        verify_token(credentials.credentials, "access")
    else:
        raise HTTPException(status_code=401, detail="Authentification requise", headers={"WWW-Authenticate": "Bearer"})

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier physique introuvable")

    # ?token= → aperçu inline (iframe) | Bearer → téléchargement forcé
    disposition = "inline" if token else "attachment"
    return FileResponse(
        file_path,
        filename=doc.filename,
        headers={"Content-Disposition": f'{disposition}; filename="{doc.filename}"'},
    )


@router.get("/documents/{doc_id}/pdf")
def get_document_pdf(
    doc_id: int,
    token: str = Query(None),
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
):
    """
    Sert le PDF généré. Même logique d'authentification que /file.
    """
    if token:
        verify_file_token(token, doc_id)
    elif credentials:
        from core.security import verify_token
        verify_token(credentials.credentials, "access")
    else:
        raise HTTPException(status_code=401, detail="Authentification requise", headers={"WWW-Authenticate": "Bearer"})

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    if not doc.pdf_filename:
        raise HTTPException(status_code=404, detail="Aucun PDF généré pour ce document")
    pdf_path = os.path.join(UPLOAD_DIR, doc.pdf_filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Fichier PDF introuvable")

    # ?token= → aperçu inline (iframe) | Bearer → téléchargement forcé
    disposition = "inline" if token else "attachment"
    return FileResponse(
        pdf_path,
        filename=doc.pdf_filename,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{doc.pdf_filename}"'},
    )


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


# ---------------------------------------------------------------------------
# Règles de classification personnalisées (multi-conditions AND)
# ---------------------------------------------------------------------------

class ConditionIn(BaseModel):
    match_field: str   # 'issuer' | 'content' | 'category' | 'amount_not_null' | 'amount_null'
    match_value: str | None = None

class RuleCreate(BaseModel):
    name: str
    target_category: str
    priority: int = 0
    enabled: str = "true"
    conditions: list[ConditionIn] = []

class RuleUpdate(BaseModel):
    name: str | None = None
    target_category: str | None = None
    priority: int | None = None
    enabled: str | None = None
    conditions: list[ConditionIn] | None = None


def _rule_to_dict(r, conditions):
    return {
        "id": r.id, "name": r.name,
        "target_category": r.target_category,
        "priority": r.priority, "enabled": r.enabled,
        "conditions": [{"id": c.id, "match_field": c.match_field, "match_value": c.match_value}
                       for c in conditions],
    }


@router.get("/rules")
@limiter.limit("60/minute")
def list_rules(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from database import ClassificationRule, RuleCondition
    rules = db.query(ClassificationRule).order_by(ClassificationRule.priority.desc()).all()
    result = []
    for r in rules:
        conds = db.query(RuleCondition).filter(RuleCondition.rule_id == r.id).all()
        result.append(_rule_to_dict(r, conds))
    return result


@router.post("/rules", status_code=201)
@limiter.limit("30/minute")
def create_rule(request: Request, rule: RuleCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from database import ClassificationRule, RuleCondition
    r = ClassificationRule(name=rule.name, target_category=rule.target_category,
                           priority=rule.priority, enabled=rule.enabled)
    db.add(r)
    db.commit()
    db.refresh(r)
    for cond in rule.conditions:
        db.add(RuleCondition(rule_id=r.id, match_field=cond.match_field, match_value=cond.match_value))
    db.commit()
    conds = db.query(RuleCondition).filter(RuleCondition.rule_id == r.id).all()
    log_security_event("RULE_CREATED", {"rule_id": r.id, "name": r.name, "user": current_user.username}, request)
    return _rule_to_dict(r, conds)


@router.put("/rules/{rule_id}")
@limiter.limit("30/minute")
def update_rule(request: Request, rule_id: int, data: RuleUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from database import ClassificationRule, RuleCondition
    r = db.query(ClassificationRule).filter(ClassificationRule.id == rule_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Règle introuvable")
    for field, value in data.dict(exclude={"conditions"}, exclude_none=True).items():
        setattr(r, field, value)
    if data.conditions is not None:
        db.query(RuleCondition).filter(RuleCondition.rule_id == rule_id).delete()
        for cond in data.conditions:
            db.add(RuleCondition(rule_id=rule_id, match_field=cond.match_field, match_value=cond.match_value))
    db.commit()
    conds = db.query(RuleCondition).filter(RuleCondition.rule_id == rule_id).all()
    return _rule_to_dict(r, conds)


@router.delete("/rules/{rule_id}")
@limiter.limit("30/minute")
def delete_rule(request: Request, rule_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from database import ClassificationRule, RuleCondition
    r = db.query(ClassificationRule).filter(ClassificationRule.id == rule_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Règle introuvable")
    db.query(RuleCondition).filter(RuleCondition.rule_id == rule_id).delete()
    db.delete(r)
    db.commit()
    log_security_event("RULE_DELETED", {"rule_id": rule_id, "user": current_user.username}, request)
    return {"message": "Règle supprimée"}
