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
import re
import json
import threading
import time
import logging
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional
from prompts import EMAIL_CLASSIFIER_PROMPT

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


def _uid_bytes(uid) -> bytes:
    """Normalise un UID en bytes pour les commandes IMAP."""
    if isinstance(uid, bytes):
        return uid
    return str(uid).encode()


def _folder_str(folder: str) -> str:
    """Encode correctement le nom de dossier pour SELECT/COPY/CREATE."""
    # Si le dossier contient des espaces ou des caractères spéciaux, on met des guillemets
    if any(c in folder for c in (' ', '/', '-', '.')):
        return f'"{folder}"'
    return folder


def _connect(host: str, user: str, password: str, port: int = 993) -> imaplib.IMAP4_SSL:
    """
    Connexion IMAP — supporte deux modes :
    - OAuth2 XOAUTH2 : si oauth_microsoft.is_oauth_configured() → utilisé automatiquement
    - Basique LOGIN  : sinon, utilise user/password (Gmail avec App Password, etc.)
    """
    if not host:
        raise ValueError("Serveur IMAP non configuré. Allez dans Paramètres > Email.")

    # Tenter OAuth2 Google en priorité si le host est Gmail
    if "gmail" in host.lower():
        try:
            import oauth_google
            if oauth_google.is_oauth_configured():
                access_token, oauth_user = oauth_google.get_valid_access_token()
                effective_user = oauth_user or user
                logger.info(f"[email] Connexion OAuth2 Google pour {effective_user}@{host}")
                return oauth_google.connect_imap_oauth(host, effective_user, access_token, port)
        except Exception as e:
            logger.warning(f"[email] OAuth2 Google indisponible : {e}")
            raise ValueError(
                f"Connexion Gmail échouée. "
                f"Gmail exige OAuth2 — configurez votre Client ID Google dans Paramètres > Gmail OAuth2. "
                f"Détail : {e}"
            )

    # Tenter OAuth2 Microsoft pour Outlook/Hotmail/Office365
    if any(k in host.lower() for k in ("outlook", "hotmail", "office365", "live.com", "microsoft")):
        try:
            import oauth_microsoft
            if oauth_microsoft.is_oauth_configured():
                access_token, oauth_user = oauth_microsoft.get_valid_access_token()
                effective_user = oauth_user or user
                logger.info(f"[email] Connexion OAuth2 Microsoft pour {effective_user}@{host}")
                return oauth_microsoft.connect_imap_oauth(host, effective_user, access_token, port)
        except Exception as e:
            logger.warning(f"[email] OAuth2 Microsoft indisponible, tentative login basique : {e}")

    # Fallback : authentification basique
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        typ, data = mail.login(user, password)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"LOGIN returned {typ}")
        logger.info(f"[email] Connexion basique OK pour {user}@{host}")
        return mail
    except imaplib.IMAP4.error as e:
        raw = str(e)
        logger.error(f"[email] Erreur IMAP : {raw!r}")
        if any(k in raw for k in ("LOGIN failed", "AUTHENTICATIONFAILED", "Invalid credentials", "Authentication failed")):
            hint = ""
            if any(k in host.lower() for k in ("outlook", "hotmail", "office365", "live.com")):
                hint = (
                    " Outlook/Hotmail bloque l'auth basique. Utilisez OAuth2 : "
                    "configurez client_id/secret dans Paramètres et cliquez 'Connecter Outlook'."
                )
            elif "gmail" in host.lower():
                hint = (
                    " Gmail exige un App Password : myaccount.google.com/apppasswords (2FA requis)."
                )
            raise ValueError(f"Authentification IMAP échouée.{hint}")
        raise ValueError(f"Erreur IMAP : {raw}")
    except OSError as e:
        logger.error(f"[email] Erreur réseau : {e!r}")
        raise ValueError(f"Impossible de joindre {host}:{port} — vérifiez le serveur et votre réseau.")


def _select_folder(mail: imaplib.IMAP4_SSL, folder: str):
    """Sélectionne un dossier IMAP, lève ValueError si échec."""
    typ, data = mail.select(_folder_str(folder))
    if typ != "OK":
        # Essai sans guillemets si la première tentative échoue
        typ2, data2 = mail.select(folder)
        if typ2 != "OK":
            raise ValueError(f"Dossier IMAP introuvable : {folder!r} (réponse : {data})")
    return data


def _ensure_folder(mail: imaplib.IMAP4_SSL, folder: str):
    """Crée le dossier IMAP s'il n'existe pas."""
    try:
        typ, listing = mail.list('""', f'"{folder}"')
        if typ == "OK" and listing and listing[0]:
            return  # existe déjà
        mail.create(_folder_str(folder))
        logger.info(f"[email] Dossier créé : {folder}")
    except Exception as e:
        logger.warning(f"[email] Impossible de créer/vérifier le dossier {folder!r} : {e}")


def _move_message(mail: imaplib.IMAP4_SSL, uid, destination: str):
    """Déplace un message vers un dossier (COPY + DELETE + EXPUNGE)."""
    uid_b = _uid_bytes(uid)
    try:
        _ensure_folder(mail, destination)
        typ, _ = mail.uid("COPY", uid_b, _folder_str(destination))
        if typ != "OK":
            logger.error(f"[email] COPY échoué pour uid {uid} → {destination}")
            return
        mail.uid("STORE", uid_b, "+FLAGS", "\\Deleted")
        mail.expunge()
        logger.info(f"[email] Message {uid} déplacé vers '{destination}'")
    except Exception as e:
        logger.error(f"[email] Erreur déplacement {uid} → {destination}: {e}")


def _delete_message(mail: imaplib.IMAP4_SSL, uid):
    """Supprime définitivement un message."""
    uid_b = _uid_bytes(uid)
    try:
        mail.uid("STORE", uid_b, "+FLAGS", "\\Deleted")
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
        _select_folder(mail, folder)

        status, data = mail.uid("SEARCH", None, "ALL")
        if status != "OK":
            mail.logout()
            return []

        uids = data[0].split()
        uids_to_fetch = uids[-limit:] if len(uids) > limit else uids
        uids_to_fetch = list(reversed(uids_to_fetch))

        for uid in uids_to_fetch:
            try:
                status, msg_data = mail.uid("FETCH", uid, "(FLAGS RFC822.HEADER)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_headers = msg_data[0][1]
                msg = email.message_from_bytes(raw_headers)
                flags_raw = msg_data[0][0]
                flags_str = flags_raw.decode() if isinstance(flags_raw, bytes) else str(flags_raw)
                is_read = "\\Seen" in flags_str

                date_str = msg.get("Date", "")
                try:
                    dt = parsedate_to_datetime(date_str)
                    date_iso = dt.isoformat()
                except Exception:
                    date_iso = date_str

                # Vérification pièces jointes via BODYSTRUCTURE
                has_attachment = False
                try:
                    status2, full_data = mail.uid("FETCH", uid, "(BODYSTRUCTURE)")
                    if status2 == "OK" and full_data and full_data[0]:
                        body_str = full_data[0].decode() if isinstance(full_data[0], bytes) else str(full_data[0])
                        has_attachment = ("attachment" in body_str.lower()
                                          or "application/pdf" in body_str.lower()
                                          or "image/" in body_str.lower())
                except Exception:
                    pass

                emails.append({
                    "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
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
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"[email] Erreur list_emails: {e}")
        raise
    return emails


def list_folders(host: str, user: str, password: str) -> list[str]:
    """Retourne la liste des dossiers IMAP disponibles."""
    folders = []
    try:
        mail = _connect(host, user, password)
        status, data = mail.list()
        if status == "OK":
            for item in data:
                if not item:
                    continue
                decoded = item.decode() if isinstance(item, bytes) else str(item)
                # Format : (\HasNoChildren) "/" "INBOX" ou (\HasNoChildren) "/" INBOX
                # On extrait la dernière partie après le séparateur
                match = re.search(r'"[^"]*"\s+(.+)$', decoded)
                if match:
                    name = match.group(1).strip().strip('"')
                else:
                    # Fallback : dernier token
                    parts = decoded.rsplit(None, 1)
                    name = parts[-1].strip().strip('"') if parts else ""
                if name and name not in ('/', ''):
                    folders.append(name)
        mail.logout()
    except ValueError:
        raise
    except imaplib.IMAP4.error as e:
        msg = str(e)
        if any(k in msg for k in ("AUTHENTICATIONFAILED", "Invalid credentials", "LOGIN failed")):
            raise ValueError(
                "Authentification IMAP échouée. "
                "Gmail : App Password sur myaccount.google.com/apppasswords. "
                "Outlook/Hotmail : utilisez OAuth2 (section ci-dessous)."
            )
        raise ValueError(f"Erreur IMAP : {msg}")
    except Exception as e:
        logger.error(f"[email] Erreur list_folders: {e}")
        raise ValueError(f"Impossible de lister les dossiers : {e}")
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
    os.makedirs(upload_dir, exist_ok=True)
    try:
        mail = _connect(host, user, password)
        _select_folder(mail, folder)

        search_criteria = "UNSEEN" if only_unread else "ALL"
        status, data = mail.uid("SEARCH", None, search_criteria)
        if status != "OK":
            mail.logout()
            return []

        uids = data[0].split()
        logger.info(f"[email] {len(uids)} email(s) à traiter pour pièces jointes")

        for uid in uids:
            uid_b = _uid_bytes(uid)
            try:
                status, msg_data = mail.uid("FETCH", uid_b, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                subject = _decode_header(msg.get("Subject", ""))
                has_any_attachment = False

                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    disposition = part.get("Content-Disposition", "")
                    if not disposition:
                        continue
                    filename = part.get_filename()
                    if not filename:
                        continue
                    filename = _decode_header(filename)
                    safe_name = re.sub(r'[^\w\.\-]', '_', filename)
                    if not safe_name:
                        safe_name = "attachment"
                    filepath = os.path.join(upload_dir, safe_name)
                    # Éviter les collisions
                    base, ext = os.path.splitext(safe_name)
                    counter = 1
                    while os.path.exists(filepath):
                        safe_name = f"{base}_{counter}{ext}"
                        filepath = os.path.join(upload_dir, safe_name)
                        counter += 1

                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue
                    with open(filepath, "wb") as f:
                        f.write(payload)
                    logger.info(f"[email] Pièce jointe sauvegardée : {safe_name}")
                    downloaded.append({
                        "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                        "subject": subject,
                        "filename": safe_name,
                        "filepath": filepath,
                    })
                    has_any_attachment = True

                if has_any_attachment:
                    _move_message(mail, uid_b, treated_folder)

            except Exception as e:
                logger.warning(f"[email] Erreur traitement uid {uid}: {e}")
                continue

        mail.logout()
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"[email] Erreur download_attachments: {e}")
    return downloaded


# ---------------------------------------------------------------------------
# Détection LLM + suppression des promotionnels
# ---------------------------------------------------------------------------

def _classify_email_llm(subject: str, sender: str, llm_config: dict) -> str:
    """
    Utilise le LLM pour classifier un email.
    Retourne : Promotionnel, Facture, Notification, Personnel, Autre
    """
    try:
        from openai import OpenAI
        client = OpenAI(base_url=llm_config["base_url"], api_key=llm_config["api_key"])
        response = client.chat.completions.create(
            model=llm_config["model"],
            messages=[
                {"role": "system", "content": EMAIL_CLASSIFIER_PROMPT},
                {"role": "user", "content": f"Sujet: {subject}\nExpéditeur: {sender}"},
            ],
            temperature=0,
            max_tokens=10,
        )
        result = response.choices[0].message.content.strip()
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
    Si older_than_days=0, analyse TOUS les emails sans limite d'âge.
    """
    report = {
        "total": 0, "analysed": 0, "deleted": 0,
        "too_recent": 0, "kept": 0, "errors": 0,
        "dry_run": dry_run, "older_than_days": older_than_days,
    }

    cutoff = None
    if older_than_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

    try:
        mail = _connect(host, user, password)
        _select_folder(mail, folder)

        status, data = mail.uid("SEARCH", None, "ALL")
        if status != "OK":
            mail.logout()
            return report

        uids = data[0].split()
        report["total"] = len(uids)
        logger.info(f"[email] Purge promotionnels — {len(uids)} emails dans '{folder}' (cutoff: {cutoff})")

        for uid in uids:
            uid_b = _uid_bytes(uid)
            try:
                status, msg_data = mail.uid("FETCH", uid_b, "(RFC822.HEADER)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    report["errors"] += 1
                    continue

                msg      = email.message_from_bytes(msg_data[0][1])
                subject  = _decode_header(msg.get("Subject", "(sans objet)"))
                sender   = _decode_header(msg.get("From", ""))
                date_str = msg.get("Date", "")

                if cutoff:
                    try:
                        dt = parsedate_to_datetime(date_str)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt > cutoff:
                            report["too_recent"] += 1
                            continue
                    except Exception:
                        pass

                report["analysed"] += 1
                category = _classify_email_llm(subject, sender, llm_config)
                logger.info(f"[email] [{category}] {subject[:50]} | {sender[:30]}")

                if category == "Promotionnel":
                    report["deleted"] += 1
                    if not dry_run:
                        _delete_message(mail, uid_b)
                else:
                    report["kept"] += 1

            except Exception as e:
                logger.warning(f"[email] Erreur uid {uid}: {e}")
                report["errors"] += 1
                continue

        mail.logout()
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"[email] Erreur purge_promotional_emails: {e}")

    logger.info(f"[email] Rapport purge : {report}")
    return report


# ---------------------------------------------------------------------------
# Suppression / déplacement / marquage manuels
# ---------------------------------------------------------------------------

def delete_email(host: str, user: str, password: str,
                 uid: str, folder: str = "INBOX") -> bool:
    """Supprime un email par UID."""
    try:
        mail = _connect(host, user, password)
        _select_folder(mail, folder)
        _delete_message(mail, uid)
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
        _select_folder(mail, source_folder)
        _move_message(mail, uid, destination_folder)
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
        _select_folder(mail, folder)
        mail.uid("STORE", _uid_bytes(uid), "+FLAGS", "\\Seen")
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

                # Vérifier que email_enabled = true
                if cfg.get("email_enabled", "false").lower() != "true":
                    self._stop_event.wait(60)
                    continue

                host = cfg.get("email_host", "")
                user = cfg.get("email_user", "")
                pwd  = cfg.get("email_password", "")
                if not (host and user):
                    self._stop_event.wait(60)
                    continue

                llm_config = {
                    "base_url": cfg.get("llm_base_url", "http://localhost:1234/v1"),
                    "api_key":  cfg.get("llm_api_key",  "lm-studio"),
                    "model":    cfg.get("llm_model",     "local-model"),
                }

                # UPLOAD_DIR : priorité var env, puis valeur DB
                upload_dir     = os.getenv("UPLOAD_DIR", cfg.get("UPLOAD_DIR", "./storage/uploads"))
                treated_folder = cfg.get("email_treated_folder", "PaperFree-Traité")
                attach_interval = int(cfg.get("email_attach_interval_min", "15"))
                purge_interval  = int(cfg.get("email_purge_interval_hours", "24"))
                promo_days      = int(cfg.get("email_promo_days", "7"))
                email_folder    = cfg.get("email_folder", "INBOX")

                # === Téléchargement pièces jointes ===
                logger.info("[email-scheduler] Vérification des pièces jointes...")
                try:
                    downloaded = download_attachments(
                        host, user, pwd, upload_dir,
                        folder=email_folder,
                        treated_folder=treated_folder,
                    )
                    if downloaded:
                        logger.info(f"[email-scheduler] {len(downloaded)} pièce(s) jointe(s) téléchargée(s)")
                        _trigger_processing(downloaded)
                except Exception as e:
                    logger.error(f"[email-scheduler] Erreur sync pièces jointes : {e}")

                # === Purge promotionnels (une fois par intervalle) ===
                now = datetime.now(timezone.utc)
                should_purge = (
                    self._last_purge is None
                    or (now - self._last_purge).total_seconds() >= purge_interval * 3600
                )
                if should_purge:
                    logger.info("[email-scheduler] Purge des emails promotionnels...")
                    try:
                        report = purge_promotional_emails(
                            host, user, pwd,
                            llm_config=llm_config,
                            folder=email_folder,
                            older_than_days=promo_days,
                        )
                        logger.info(f"[email-scheduler] Purge : {report}")
                    except Exception as e:
                        logger.error(f"[email-scheduler] Erreur purge : {e}")
                    self._last_purge = now

            except Exception as e:
                logger.error(f"[email-scheduler] Erreur boucle: {e}")

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
                db_doc = Document(filename=filename, content=None, category=None, summary=None)
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
