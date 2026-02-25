"""
services/processing.py — Traitement OCR + LLM en arrière-plan.
"""
import os
import logging

from database import SessionLocal, Document
from processor import process_document, generate_text_pdf
from core.config import UPLOAD_DIR

logger = logging.getLogger(__name__)


def run_processing(doc_id: int, file_path: str):
    """Traite un document (OCR + LLM) et met à jour la DB."""
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
            # Sources du pipeline (ex: ["vision","ocr+llm"] ou None)
            sources = analysis.get("pipeline_sources")
            if sources:
                import json as _json
                doc.pipeline_sources = _json.dumps(sources)

            # Générer un PDF searchable si la source est une image
            ext = os.path.splitext(file_path)[1].lower()
            if ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"):
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                meta = {
                    "category": doc.category,
                    "summary":  doc.summary,
                    "date":     doc.doc_date,
                    "amount":   doc.amount,
                    "issuer":   doc.issuer,
                }
                pdf_path = generate_text_pdf(
                    text, UPLOAD_DIR, base_name, meta,
                    image_path=file_path,
                )
                if pdf_path:
                    doc.pdf_filename = os.path.basename(pdf_path)

            db.commit()
            logger.info(f"[processor] Doc #{doc_id} traité : {analysis.get('category')} — {analysis.get('summary')}")
    except Exception as e:
        logger.error(f"[processor] Erreur doc {doc_id}: {e}")
    finally:
        db.close()
