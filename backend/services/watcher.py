"""
services/watcher.py — Surveillance du dossier watch/ pour l'ingestion automatique.
"""
import threading
import logging

from database import SessionLocal, Document
from core.config import WATCH_DIR
from services.processing import run_processing

logger = logging.getLogger(__name__)


def start_folder_watcher():
    """Lance watchdog en arrière-plan sur WATCH_DIR."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if event.is_directory:
                    return
                import os
                fname = os.path.basename(event.src_path)
                ext = os.path.splitext(fname)[1].lower()
                if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
                    return
                logger.info(f"[watcher] Nouveau fichier détecté : {fname}")
                db = SessionLocal()
                try:
                    db_doc = Document(filename=fname, content=None, category=None, summary=None)
                    db.add(db_doc)
                    db.commit()
                    db.refresh(db_doc)
                    threading.Thread(
                        target=run_processing,
                        args=(db_doc.id, event.src_path),
                        daemon=True,
                    ).start()
                finally:
                    db.close()

        observer = Observer()
        observer.schedule(_Handler(), WATCH_DIR, recursive=False)
        observer.start()
        logger.info(f"[watcher] Surveillance active sur : {WATCH_DIR}")
    except Exception as e:
        logger.error(f"[watcher] Impossible de démarrer : {e}")
