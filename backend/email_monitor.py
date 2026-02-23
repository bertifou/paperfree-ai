"""
email_monitor.py — Module de surveillance et gestion des emails IMAP
- Consultation des emails (inbox + dossiers)
- Téléchargement et classement des pièces jointes
- Détection LLM des emails promotionnels
- Suppression automatique après délai configurable
- Déplacement dans un dossier 'Traité' après traitement des pièces jointes
"""

import imaplib
import email
import email.header
import os
import json
import threading
import time
import logging
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers IMAP
# ---------------------------------------------------------------------------

def _decode_header(value: str) -> str:
    """Décode un en-tête email (gestion charset)."""
    if not value:
        return ""
    parts = email.header.decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(charset or "utf-8", errors="replace"))
            except Exception:
                result.append(part.decode("latin-1", errors="replace"))
        else:
            result.append(str(part))
    return " ".join(result)


def _connect(host: str, user: str, password: str, port: int = 993) -> imaplib.IMAP4_SSL:
    mail = imaplib.IMAP4_SSL(host, port)
    mail.login(user, password)
    return mail


def _ensure_folder(mail: imaplib.IMAP4_SSL, folder: str):
    """Crée le dossier IMAP s'il n'existe pas."""
    result = mail.list('""', f'"{folder}"')
    if result[0] == "OK" and result[1] and result[1][0]:
        return  # existe déjà
    mail.create(folder)
    logger.info(f"[email] Dossier créé : {folder}")


def _move_message(mail: imaplib.IMAP4_SSL, uid: str, destination: str):
    """Déplace un message vers un dossier (COPY + DELETE + EXPUNGE)."""
    try:
        _ensure_folder(mail, destination)
        mail.uid("COPY", uid, destination)
        mail.uid("STORE", uid, "+FLAGS", "\\Deleted")
        mail.expunge()
        logger.info(f"[email] Message {uid} déplacé vers '{destination}'")
    except Exception as e:
        logger.error(f"[email] Erreur déplacement {uid} → {destination}: {e}")


def _delete_message(mail: imaplib.IMAP4_SSL, uid: str):
    """Supprime définitivement un message."""
    try:
        mail.uid("STORE", uid, "+FLAGS", "\\Deleted")
        mail.expunge()
        logger.info(f"[email] Message {uid} supprimé")
    except Exception as e:
        logger.error(f"[email] Erreur suppression {uid}: {e}")


# ---------------------------------------------------------------------------
# Lecture des emails
# ---------------------------------------------------------------------------

def list_emails(host: str, user: str, password: str,
                folder: str = "INBOX", limit: int = 50) -> list[dict]:
    """
    Retourne les N derniers emails d'un dossier sous forme de liste de dicts.
    Ne télécharge pas les pièces jointes (lecture légère).
    """
    emails = []
    try:
        mail = _connect(host, user, password)
        mail.select(f'"{folder}"' if " " in folder else folder)

        status, data = mail.uid("SEARCH", None, "ALL")
        if status != "OK":
            mail.logout()
            return []

        uids = data[0].split()
        # Prendre les N plus récents
        uids_to_fetch = uids[-limit:] if len(uids) > limit else uids
        uids_to_fetch = list(reversed(uids_to_fetch))  # du plus récent au plus ancien

        for uid in uids_to_fetch:
            try:
                status, msg_data = mail.uid("FETCH", uid, "(FLAGS RFC822.HEADER)")
                if status != "OK":
                    continue
                raw_headers = msg_data[0][1]
                msg = email.message_from_bytes(raw_headers)
                flags_str = msg_data[0][0].decode() if isinstance(msg_data[0][0], bytes) else str(msg_data[0][0])
                is_read = "\\Seen" in flags_str

                # Date
                date_str = msg.get("Date", "")
                try:
                    dt = parsedate_to_datetime(date_str)
                    date_iso = dt.isoformat()
                except Exception:
                    date_iso = date_str

                # Pièces jointes (lecture rapide via structure)
                has_attachment = False
                status2, full_data = mail.uid("FETCH", uid, "(BODYSTRUCTURE)")
                if status2 == "OK" and full_data[0]:
                    body_str = full_data[0].decode() if isinstance(full_data[0], bytes) else str(full_data[0])
                    has_attachment = "attachment" in body_str.lower() or "application/" in body_str.lower()

                emails.append({
                    "uid": uid.decode(),
                    "subject": _decode_header(msg.get("Subject", "(sans objet)")),
                    "sender":  _decode_header(msg.get("From", "")),
                    "date":    date_iso,
                    "is_read": is_read,
                    "has_attachment": has_attachment,
                    "folder": folder,
                })
            except Exception as e:
                logger.warning(f"[email] Erreur lecture uid {uid}: {e}")
                continue

        mail.logout()
    except Exception as e:
        logger.error(f"[email] Erreur list_emails: {e}")
    return emails


def list_folders(host: str, user: str, password: str) -> list[str]:
    """Retourne la liste des dossiers IMAP disponibles."""
    folders = []
    try:
        mail = _connect(host, user, password)
        status, data = mail.list()
        if status == "OK":
            for item in data:
                if item:
                    decoded = item.decode() if isinstance(item, bytes) else str(item)
                    # Extraire le nom du dossier (dernier élément)
                    parts = decoded.split('"')
                    if len(parts) >= 2:
                        name = parts[-2] if parts[-1].strip() == "" else parts[-1].strip()
                        if name and name not in ('/', ''):
                            folders.append(name)
        mail.logout()
    except Exception as e:
        logger.error(f"[email] Erreur list_folders: {e}")
    return folders


# ---------------------------------------------------------------------------
# Téléchargement des pièces jointes
# ---------------------------------------------------------------------------

def download_attachments(host: str, user: str, password: str,
                         upload_dir: str,
                         folder: str = "INBOX",
                         treated_folder: str = "PaperFree-Traité",
                         only_unread: bool = True) -> list[dict]:
    """
    Télécharge les pièces jointes des emails non lus (ou tous si only_unread=False).
    Déplace chaque email traité vers treated_folder.
    Retourne la liste des fichiers téléchargés avec leur uid source.
    """
    downloaded = []
    try:
        mail = _connect(host, user, password)
        mail.select(f'"{folder}"' if " " in folder else folder)

        search_criteria = "UNSEEN" if only_unread else "ALL"
        status, data = mail.uid("SEARCH", None, search_criteria)
        if status != "OK":
            mail.logout()
            return []

        uids = data[0].split()
        logger.info(f"[email] {len(uids)} email(s) à traiter pour pièces jointes")

        for uid in uids:
            try:
                status, msg_data = mail.uid("FETCH", uid, "(RFC822)")
                if status != "OK":
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                subject = _decode_header(msg.get("Subject", ""))
                has_any_attachment = False

                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    if part.get("Content-Disposition") is None:
                        continue
                    filename = part.get_filename()
                    if not filename:
                        continue
                    filename = _decode_header(filename)
                    # Sanitize
                    import re
                    safe_name = re.sub(r'[^\w\.\-]', '_', filename)
                    filepath = os.path.join(upload_dir, safe_name)
                    # Éviter les collisions
                    base, ext = os.path.splitext(safe_name)
                    counter = 1
                    while os.path.exists(filepath):
                        safe_name = f"{base}_{counter}{ext}"
                        filepath = os.path.join(upload_dir, safe_name)
                        counter += 1

                    with open(filepath, "wb") as f:
                        f.write(part.get_payload(decode=True))
                    logger.info(f"[email] Pièce jointe sauvegardée : {safe_name}")
                    downloaded.append({
                        "uid": uid.decode(),
                        "subject": subject,
                        "filename": safe_name,
                        "filepath": filepath,
                    })
                    has_any_attachment = True

                if has_any_attachment:
                    _move_message(mail, uid, treated_folder)

            except Exception as e:
                logger.warning(f"[email] Erreur traitement uid {uid}: {e}")
                continue

        mail.logout()
    except Exception as e:
        logger.error(f"[email] Erreur download_attachments: {e}")
    return downloaded


# ---------------------------------------------------------------------------
# Détection LLM + suppression des promotionnels
# ---------------------------------------------------------------------------

def _classify_email_llm(subject: str, sender: str, llm_config: dict) -> str:
    """
    Utilise le LLM pour classifier un email.
    Retourne une catégorie parmi : Promotionnel, Facture, Notification, Personnel, Autre
    """
    try:
        from openai import OpenAI
        client = OpenAI(base_url=llm_config["base_url"], api_key=llm_config["api_key"])
        response = client.chat.completions.create(
            model=llm_config["model"],
            messages=[
                {"role": "system", "content": (
                    "Tu es un classificateur d'emails. "
                    "Réponds UNIQUEMENT avec UN seul mot parmi : "
                    "Promotionnel, Facture, Notification, Personnel, Autre.\n"
                    "Promotionnel = newsletter, pub, offre commerciale, soldes, marketing.\n"
                    "Facture = reçu, invoice, confirmation de paiement.\n"
                    "Notification = alerte système, 2FA, confirmation inscription.\n"
                    "Personnel = échange humain direct.\n"
                    "Autre = tout le reste."
                )},
                {"role": "user", "content": f"Sujet: {subject}\nExpéditeur: {sender}"},
            ],
            temperature=0,
            max_tokens=10,
        )
        result = response.choices[0].message.content.strip()
        # Valider
        valid = {"Promotionnel", "Facture", "Notification", "Personnel", "Autre"}
        for v in valid:
            if v.lower() in result.lower():
                return v
        return "Autre"
    except Exception as e:
        logger.error(f"[email] Erreur classification LLM: {e}")
        return "Autre"


def purge_promotional_emails(host: str, user: str, password: str,
                             llm_config: dict,
                             folder: str = "INBOX",
                             older_than_days: int = 7,
                             dry_run: bool = False) -> dict:
    """
    Analyse les emails du dossier et supprime les promotionnels
    plus vieux que older_than_days jours.
    Si dry_run=True, liste sans supprimer.
    Retourne un rapport {analysed, deleted, skipped}.
    """
    report = {"analysed": 0, "deleted": 0, "skipped": 0, "dry_run": dry_run}
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

    try:
        mail = _connect(host, user, password)
        mail.select(f'"{folder}"' if " " in folder else folder)

        status, data = mail.uid("SEARCH", None, "ALL")
        if status != "OK":
            mail.logout()
            return report

        uids = data[0].split()
        logger.info(f"[email] Analyse purge promotionnels : {len(uids)} emails dans {folder}")

        for uid in uids:
            try:
                status, msg_data = mail.uid("FETCH", uid, "(RFC822.HEADER)")
                if status != "OK":
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                subject = _decode_header(msg.get("Subject", ""))
                sender  = _decode_header(msg.get("From",    ""))
                date_str = msg.get("Date", "")

                # Vérifier l'ancienneté
                try:
                    dt = parsedate_to_datetime(date_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt > cutoff:
                        report["skipped"] += 1
                        continue  # Trop récent
                except Exception:
                    pass

                report["analysed"] += 1
                category = _classify_email_llm(subject, sender, llm_config)
                logger.info(f"[email] [{category}] {subject[:50]}")

                if category == "Promotionnel":
                    if not dry_run:
                        _delete_message(mail, uid)
                    report["deleted"] += 1
                else:
                    report["skipped"] += 1

            except Exception as e:
                logger.warning(f"[email] Erreur uid {uid}: {e}")
                continue

        mail.logout()
    except Exception as e:
        logger.error(f"[email] Erreur purge_promotional_emails: {e}")

    return report


# ---------------------------------------------------------------------------
# Suppression manuelle d'un email
# ---------------------------------------------------------------------------

def delete_email(host: str, user: str, password: str,
                 uid: str, folder: str = "INBOX") -> bool:
    """Supprime un email par UID."""
    try:
        mail = _connect(host, user, password)
        mail.select(f'"{folder}"' if " " in folder else folder)
        _delete_message(mail, uid.encode())
        mail.logout()
        return True
    except Exception as e:
        logger.error(f"[email] Erreur delete_email {uid}: {e}")
        return False


def move_email(host: str, user: str, password: str,
               uid: str, source_folder: str, destination_folder: str) -> bool:
    """Déplace un email vers un autre dossier."""
    try:
        mail = _connect(host, user, password)
        mail.select(f'"{source_folder}"' if " " in source_folder else source_folder)
        _move_message(mail, uid.encode(), destination_folder)
        mail.logout()
        return True
    except Exception as e:
        logger.error(f"[email] Erreur move_email {uid}: {e}")
        return False


def mark_as_read(host: str, user: str, password: str,
                 uid: str, folder: str = "INBOX") -> bool:
    """Marque un email comme lu."""
    try:
        mail = _connect(host, user, password)
        mail.select(f'"{folder}"' if " " in folder else folder)
        mail.uid("STORE", uid.encode(), "+FLAGS", "\\Seen")
        mail.logout()
        return True
    except Exception as e:
        logger.error(f"[email] Erreur mark_as_read {uid}: {e}")
        return False


# ---------------------------------------------------------------------------
# Scheduler automatique
# ---------------------------------------------------------------------------

class EmailScheduler:
    """
    Tourne en arrière-plan et exécute les tâches email périodiquement.
    Intervalle configurable (défaut: toutes les 15 min pour les pièces jointes,
    toutes les 24h pour la purge promotionnels).
    """

    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_purge: Optional[datetime] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("[email-scheduler] Démarré")

    def stop(self):
        self._stop_event.set()
        logger.info("[email-scheduler] Arrêté")

    def _get_config(self):
        """Lit la config email depuis la DB."""
        try:
            from database import SessionLocal, Setting
            db = SessionLocal()
            settings = {s.key: s.value for s in db.query(Setting).all()}
            db.close()
            return settings
        except Exception:
            return {}

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                cfg = self._get_config()

                # Vérifier que le compte email est configuré
                host = cfg.get("email_host")
                user = cfg.get("email_user")
                pwd  = cfg.get("email_password")
                if not (host and user and pwd):
                    self._stop_event.wait(60)
                    continue

                llm_config = {
                    "base_url": cfg.get("llm_base_url", "http://localhost:1234/v1"),
                    "api_key":  cfg.get("llm_api_key",  "lm-studio"),
                    "model":    cfg.get("llm_model",     "local-model"),
                }

                upload_dir     = cfg.get("UPLOAD_DIR", "./storage/uploads")
                treated_folder = cfg.get("email_treated_folder", "PaperFree-Traité")
                attach_interval = int(cfg.get("email_attach_interval_min", "15"))
                purge_interval  = int(cfg.get("email_purge_interval_hours", "24"))
                promo_days      = int(cfg.get("email_promo_days", "7"))
                email_folder    = cfg.get("email_folder", "INBOX")

                # === Téléchargement pièces jointes ===
                logger.info("[email-scheduler] Vérification des pièces jointes...")
                downloaded = download_attachments(
                    host, user, pwd, upload_dir,
                    folder=email_folder,
                    treated_folder=treated_folder,
                )
                if downloaded:
                    logger.info(f"[email-scheduler] {len(downloaded)} pièce(s) jointe(s) téléchargée(s)")
                    # Déclencher le traitement OCR/LLM pour chaque fichier
                    _trigger_processing(downloaded)

                # === Purge promotionnels (une fois par jour) ===
                now = datetime.now(timezone.utc)
                should_purge = (
                    self._last_purge is None
                    or (now - self._last_purge).total_seconds() >= purge_interval * 3600
                )
                if should_purge:
                    logger.info("[email-scheduler] Purge des emails promotionnels...")
                    report = purge_promotional_emails(
                        host, user, pwd,
                        llm_config=llm_config,
                        folder=email_folder,
                        older_than_days=promo_days,
                    )
                    logger.info(f"[email-scheduler] Purge : {report}")
                    self._last_purge = now

            except Exception as e:
                logger.error(f"[email-scheduler] Erreur boucle: {e}")

            # Attendre jusqu'au prochain cycle
            self._stop_event.wait(attach_interval * 60)


def _trigger_processing(downloaded: list[dict]):
    """Lance le traitement OCR+LLM pour les fichiers téléchargés."""
    try:
        from database import SessionLocal, Document
        from processor import process_document

        for item in downloaded:
            filepath = item["filepath"]
            filename = item["filename"]
            ext = os.path.splitext(filename)[1].lower()
            if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
                continue

            db = SessionLocal()
            try:
                db_doc = Document(
                    filename=filename,
                    content=None,
                    category=None,
                    summary=None,
                )
                db.add(db_doc)
                db.commit()
                db.refresh(db_doc)
                doc_id = db_doc.id
            finally:
                db.close()

            def _process(did, fp):
                from database import SessionLocal, Document
                db2 = SessionLocal()
                try:
                    text, analysis = process_document(fp)
                    doc = db2.query(Document).filter(Document.id == did).first()
                    if doc:
                        doc.content  = text
                        doc.category = analysis.get("category")
                        doc.summary  = analysis.get("summary")
                        doc.doc_date = analysis.get("date")
                        doc.amount   = analysis.get("amount")
                        doc.issuer   = analysis.get("issuer")
                        db2.commit()
                        logger.info(f"[email-scheduler] Doc #{did} traité : {analysis.get('category')}")
                except Exception as e:
                    logger.error(f"[email-scheduler] Erreur traitement doc {did}: {e}")
                finally:
                    db2.close()

            threading.Thread(target=_process, args=(doc_id, filepath), daemon=True).start()

    except Exception as e:
        logger.error(f"[email-scheduler] Erreur _trigger_processing: {e}")


# Instance globale
scheduler = EmailScheduler()
