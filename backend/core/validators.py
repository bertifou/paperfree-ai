"""
core/validators.py — Validation des uploads et sécurité des fichiers.
"""
import os
import magic
from fastapi import UploadFile, HTTPException
from core.config import MAX_UPLOAD_SIZE, ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES
import logging

logger = logging.getLogger(__name__)


def validate_file_upload(file: UploadFile) -> None:
    """
    Valide un fichier uploadé :
    - Extension autorisée
    - Type MIME autorisé
    - Taille maximale
    """
    # Vérifier l'extension
    filename = file.filename or ""
    _, ext = os.path.splitext(filename.lower())
    
    if ext not in ALLOWED_EXTENSIONS:
        logger.warning(f"Rejected upload - invalid extension: {ext} for file {filename}")
        raise HTTPException(
            status_code=400,
            detail=f"Extension de fichier non autorisée: {ext}. Extensions acceptées: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Vérifier le type MIME déclaré
    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIME_TYPES:
        logger.warning(f"Rejected upload - invalid MIME type: {content_type} for file {filename}")
        raise HTTPException(
            status_code=400,
            detail=f"Type de fichier non autorisé: {content_type}"
        )


async def validate_file_content(file: UploadFile, content: bytes) -> None:
    """
    Valide le contenu réel du fichier :
    - Taille
    - Type MIME réel (magic bytes)
    """
    # Vérifier la taille
    size = len(content)
    if size == 0:
        raise HTTPException(status_code=400, detail="Fichier vide")
    
    if size > MAX_UPLOAD_SIZE:
        logger.warning(f"Rejected upload - file too large: {size} bytes for {file.filename}")
        raise HTTPException(
            status_code=413,
            detail=f"Fichier trop volumineux. Taille maximale: {MAX_UPLOAD_SIZE // (1024*1024)} MB"
        )
    
    # Vérifier le type MIME réel avec libmagic
    try:
        mime_type = magic.from_buffer(content, mime=True)
        if mime_type not in ALLOWED_MIME_TYPES:
            logger.warning(f"Rejected upload - MIME mismatch: declared={file.content_type}, actual={mime_type} for {file.filename}")
            raise HTTPException(
                status_code=400,
                detail=f"Type de fichier réel non autorisé: {mime_type}"
            )
    except Exception as e:
        logger.error(f"Error during MIME type validation: {e}")
        # On continue si libmagic échoue, mais on log l'erreur


def sanitize_filename(filename: str) -> str:
    """Nettoie un nom de fichier pour éviter les injections de path."""
    import re
    # Supprimer les caractères dangereux
    safe = re.sub(r'[^\w\.\-]', '_', filename)
    # Empêcher les traversées de répertoire
    safe = safe.replace("..", "_")
    # Limiter la longueur
    name, ext = os.path.splitext(safe)
    if len(name) > 200:
        name = name[:200]
    return name + ext if ext else name
