import os
import json
import base64
import logging
import pytesseract
from PIL import Image
import PyPDF2
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Valeurs par défaut lues depuis .env, avec fallback sur la DB si besoin
DEFAULT_LLM_CONFIG = {
    "base_url": os.getenv("LLM_BASE_URL", "http://localhost:1234/v1"),
    "api_key":  os.getenv("LLM_API_KEY",  "lm-studio"),
    "model":    os.getenv("LLM_MODEL",    "local-model"),
}

# Backends connus — URL de base par défaut (utile pour l'UI et la validation)
KNOWN_BACKENDS = {
    "lm_studio": "http://localhost:1234/v1",
    "ollama":    "http://localhost:11434/v1",
    "openai":    "https://api.openai.com/v1",
    "gemini":    "https://generativelanguage.googleapis.com/v1beta/openai/",
}

# Modèles Gemini recommandés (exposés via /backends pour l'UI)
GEMINI_MODELS = [
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

SYSTEM_PROMPT = """Tu es un assistant spécialisé dans l'analyse de documents administratifs.
Analyse le texte fourni et réponds UNIQUEMENT avec un objet JSON valide contenant :
{
  "category": "une catégorie parmi : Facture, Impôts, Santé, Banque, Contrat, Assurance, Travail, Courrier, Autre",
  "summary": "résumé en 15 mots maximum",
  "date": "date principale du document au format YYYY-MM-DD ou null",
  "amount": "montant principal en chiffres avec devise ou null",
  "issuer": "organisme ou entreprise émettrice ou null"
}
Ne réponds rien d'autre que le JSON."""

OCR_CORRECTION_PROMPT = """Tu es un expert en correction de texte OCR pour des documents administratifs français.
Le texte suivant a été extrait par OCR (reconnaissance optique de caractères) et peut contenir des erreurs typiques :
- Lettres confondues (l/1/I, 0/O, rn/m, etc.)
- Espaces manquants ou en trop
- Ponctuation incorrecte
- Mots coupés

Corrige ces erreurs en te basant sur le contexte (document administratif français).
Retourne UNIQUEMENT le texte corrigé, sans commentaires ni explications.
Conserve la structure et la mise en page originale autant que possible.
Score de confiance OCR fourni : {confidence}% — plus il est bas, plus la correction est importante."""

VISION_SYSTEM_PROMPT = """Tu es un assistant spécialisé dans l'analyse de documents administratifs par vision.
On te fournit l'image d'un document. Analyse-la et réponds UNIQUEMENT avec un objet JSON valide contenant :
{
  "category": "une catégorie parmi : Facture, Impôts, Santé, Banque, Contrat, Assurance, Travail, Courrier, Autre",
  "summary": "résumé en 15 mots maximum",
  "date": "date principale du document au format YYYY-MM-DD ou null",
  "amount": "montant principal en chiffres avec devise ou null",
  "issuer": "organisme ou entreprise émettrice ou null",
  "extracted_text": "texte principal extrait du document (500 mots max)"
}
Ne réponds rien d'autre que le JSON."""

def get_llm_config() -> dict:
    """Lit la config LLM depuis la DB, avec fallback sur les variables d'env."""
    try:
        from database import SessionLocal, Setting
        db = SessionLocal()
        settings = {s.key: s.value for s in db.query(Setting).all()}
        db.close()
        return {
            "base_url":        settings.get("llm_base_url")        or DEFAULT_LLM_CONFIG["base_url"],
            "api_key":         settings.get("llm_api_key")         or DEFAULT_LLM_CONFIG["api_key"],
            "model":           settings.get("llm_model")           or DEFAULT_LLM_CONFIG["model"],
            # Vision
            "vision_enabled":  settings.get("llm_vision_enabled",  "false").lower() == "true",
            "vision_provider": settings.get("llm_vision_provider", "local"),   # local | openai | anthropic
            "vision_model":    settings.get("llm_vision_model",    ""),        # vide = utiliser model principal
            "vision_api_key":  settings.get("llm_vision_api_key",  ""),
            "vision_base_url": settings.get("llm_vision_base_url", ""),
            # OCR
            "ocr_llm_correction": settings.get("ocr_llm_correction", "true").lower() == "true",
            "ocr_correction_threshold": int(settings.get("ocr_correction_threshold", "80")),
        }
    except Exception:
        return {**DEFAULT_LLM_CONFIG,
                "vision_enabled": False, "vision_provider": "local",
                "vision_model": "", "vision_api_key": "", "vision_base_url": "",
                "ocr_llm_correction": True, "ocr_correction_threshold": 80}


# ---------------------------------------------------------------------------
# OCR avec score de confiance
# ---------------------------------------------------------------------------

def extract_text_with_confidence(file_path: str) -> tuple[str, float]:
    """
    Extrait le texte d'une image avec le score de confiance moyen Tesseract.
    Retourne (texte, confidence_0_to_100).
    Pour les PDF, retourne (texte, 100.0) car extraction native = fiable.
    """
    if file_path.lower().endswith(".pdf"):
        text = _extract_pdf_text(file_path)
        return text, 100.0

    try:
        img = Image.open(file_path)
        # Données détaillées incluant les scores par mot
        data = pytesseract.image_to_data(img, lang="fra+eng", output_type=pytesseract.Output.DICT)
        confidences = [int(c) for c in data["conf"] if int(c) >= 0]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        # Texte brut standard
        text = pytesseract.image_to_string(img, lang="fra+eng").strip()
        logger.info(f"[ocr] Confiance moyenne : {avg_conf:.1f}% ({len(confidences)} mots)")
        return text, avg_conf
    except Exception as e:
        logger.error(f"[ocr] Erreur Tesseract : {e}")
        return "", 0.0

def _extract_pdf_text(file_path: str) -> str:
    """Extraction texte native depuis un PDF."""
    text = ""
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text.strip()


# ---------------------------------------------------------------------------
# Correction OCR par LLM (texte uniquement)
# ---------------------------------------------------------------------------

def correct_ocr_with_llm(text: str, confidence: float, config: dict) -> str:
    """
    Soumet le texte OCR brut au LLM pour correction des erreurs typiques.
    Utilisé quand la confiance est sous le seuil OU systématiquement selon config.
    """
    if not text.strip():
        return text

    threshold = config.get("ocr_correction_threshold", 80)
    if not config.get("ocr_llm_correction", True):
        return text  # Correction désactivée dans les settings

    # Toujours corriger si confiance < seuil, sinon légère passe de nettoyage
    prompt = OCR_CORRECTION_PROMPT.format(confidence=f"{confidence:.0f}")
    logger.info(f"[ocr-correction] Confiance {confidence:.0f}% → correction LLM activée")

    try:
        client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
        response = client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user",   "content": text[:4000]},
            ],
            temperature=0.1,
        )
        corrected = response.choices[0].message.content.strip()
        logger.info(f"[ocr-correction] Texte corrigé ({len(corrected)} chars)")
        return corrected
    except Exception as e:
        logger.warning(f"[ocr-correction] Erreur LLM, texte brut conservé : {e}")
        return text


# ---------------------------------------------------------------------------
# Analyse par vision (image → LLM multimodal)
# ---------------------------------------------------------------------------

def _get_vision_client(config: dict) -> tuple:
    """Retourne (client, model) selon le provider vision configuré."""
    provider = config.get("vision_provider", "local")
    v_model  = config.get("vision_model") or config.get("model", "")
    v_key    = config.get("vision_api_key") or config.get("api_key", "")
    v_url    = config.get("vision_base_url") or config.get("base_url", "")

    if provider == "openai":
        client = OpenAI(api_key=v_key or os.getenv("OPENAI_API_KEY", ""))
        model  = v_model or "gpt-4o"
    elif provider == "anthropic":
        # Utilise l'API Anthropic via interface compatible OpenAI (claude-3-5-sonnet)
        client = OpenAI(
            base_url="https://api.anthropic.com/v1",
            api_key=v_key or os.getenv("ANTHROPIC_API_KEY", ""),
        )
        model = v_model or "claude-3-5-sonnet-20241022"
    else:
        # Local (LM Studio / Ollama avec modèle vision — ex: llava, minicpm-v)
        client = OpenAI(base_url=v_url, api_key=v_key)
        model  = v_model or config.get("model", "local-model")

    return client, model

def _image_to_base64(file_path: str) -> tuple[str, str]:
    """Encode une image en base64 et retourne (data_url_prefix, b64_string)."""
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".bmp": "image/bmp",
                ".tiff": "image/tiff", ".webp": "image/webp"}
    mime = mime_map.get(ext, "image/jpeg")
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return mime, b64


def analyze_with_vision(file_path: str, config: dict) -> dict:
    """
    Analyse un document image via un LLM multimodal (vision).
    Retourne le dict structuré incluant extracted_text.
    """
    logger.info(f"[vision] Analyse vision de : {file_path}")
    try:
        mime, b64 = _image_to_base64(file_path)
        client, model = _get_vision_client(config)

        response = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}},
                    {"type": "text", "text": VISION_SYSTEM_PROMPT},
                ],
            }],
            temperature=0.1,
            max_tokens=1500,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        logger.info(f"[vision] Résultat : {result.get('category')} — {result.get('summary')}")
        return result
    except json.JSONDecodeError:
        logger.warning("[vision] JSON invalide, fallback analyse texte")
        return {"category": "Autre", "summary": "Analyse vision impossible (JSON invalide)",
                "date": None, "amount": None, "issuer": None, "extracted_text": ""}
    except Exception as e:
        logger.error(f"[vision] Erreur : {e}")
        return {"category": "Erreur", "summary": str(e)[:100],
                "date": None, "amount": None, "issuer": None, "extracted_text": ""}


# ---------------------------------------------------------------------------
# Analyse texte standard par LLM
# ---------------------------------------------------------------------------

def analyze_with_llm(text: str, config: dict | None = None) -> dict:
    """Envoie le texte au LLM et retourne un dict structuré."""
    if config is None:
        config = get_llm_config()
    try:
        client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
        response = client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": text[:3000]},
            ],
            temperature=0.1,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"category": "Autre", "summary": "Analyse impossible (JSON invalide)",
                "date": None, "amount": None, "issuer": None}
    except Exception as e:
        return {"category": "Erreur", "summary": str(e)[:100],
                "date": None, "amount": None, "issuer": None}


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def process_document(file_path: str) -> tuple[str, dict]:
    """
    Pipeline complet : OCR → correction LLM → analyse structurée.
    Si vision activée et fichier image → bypass OCR, analyse directe par vision.
    Retourne (texte_brut_ou_corrigé, analyse_dict).
    """
    config = get_llm_config()
    ext = os.path.splitext(file_path)[1].lower()
    is_image = ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp")

    # ── Chemin vision (image + vision activée) ──────────────────────────────
    if is_image and config.get("vision_enabled"):
        logger.info("[processor] Mode VISION activé")
        vision_result = analyze_with_vision(file_path, config)
        # Le texte extrait par vision sert de contenu OCR stocké en DB
        extracted_text = vision_result.pop("extracted_text", "") or ""
        # Si le texte extrait est substantiel, on l'enrichit avec une passe OCR aussi
        if not extracted_text:
            ocr_text, _ = extract_text_with_confidence(file_path)
            extracted_text = ocr_text
        return extracted_text, vision_result

    # ── Chemin OCR + correction LLM + analyse ──────────────────────────────
    if is_image:
        ocr_text, confidence = extract_text_with_confidence(file_path)
        logger.info(f"[processor] OCR confiance={confidence:.1f}%")
        # Correction LLM si texte non vide
        if ocr_text.strip():
            corrected_text = correct_ocr_with_llm(ocr_text, confidence, config)
        else:
            corrected_text = ocr_text
    else:
        # PDF — extraction native, pas d'OCR Tesseract nécessaire
        corrected_text = _extract_pdf_text(file_path)
        confidence = 100.0

    analysis = analyze_with_llm(corrected_text, config)
    # Stocker le score OCR dans le résumé si confiance basse (debug utile)
    if confidence < 60 and is_image:
        analysis["ocr_confidence"] = round(confidence, 1)

    return corrected_text, analysis