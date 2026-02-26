import os
import json
import base64
import logging
import subprocess
import tempfile
import shutil
import concurrent.futures
import pytesseract
from PIL import Image
from enhance import enhance_image
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

GEMINI_MODELS = [
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-pro-preview-05-06",
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

OCR_VISION_FUSION_PROMPT = """Tu es un expert en correction de texte OCR pour des documents administratifs français.
L'image originale du document t'est fournie ainsi que le texte extrait automatiquement par OCR.
Une analyse préliminaire par vision a également été effectuée et est fournie comme contexte.

Score de confiance OCR : {confidence}%
Contexte vision (analyse préliminaire) : {vision_context}

Erreurs OCR typiques à corriger en t'aidant de l'image et du contexte vision :
- Lettres confondues (l/1/I, 0/O, rn/m, cl/d, etc.)
- Espaces manquants ou en trop
- Ponctuation incorrecte
- Mots coupés ou fusionnés
- Chiffres mal reconnus dans les montants et dates

Texte OCR à corriger :
{ocr_text}

Retourne UNIQUEMENT le texte corrigé, sans commentaires ni explications.
Conserve la structure et la mise en page originale."""

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
            "vision_provider": settings.get("llm_vision_provider", "local"),
            "vision_model":    settings.get("llm_vision_model",    ""),
            "vision_api_key":  settings.get("llm_vision_api_key",  ""),
            "vision_base_url": settings.get("llm_vision_base_url", ""),
            # OCR — correction indépendante de la vision
            "ocr_llm_correction":          settings.get("ocr_llm_correction", "true").lower() == "true",
            "ocr_correction_threshold":    int(settings.get("ocr_correction_threshold", "80")),
            "ocr_vision_fusion":           settings.get("ocr_vision_fusion", "true").lower() == "true",
        }
    except Exception:
        return {**DEFAULT_LLM_CONFIG,
                "vision_enabled": False, "vision_provider": "local",
                "vision_model": "", "vision_api_key": "", "vision_base_url": "",
                "ocr_llm_correction": True, "ocr_correction_threshold": 80,
                "ocr_vision_fusion": True}


# ---------------------------------------------------------------------------
# Génération PDF avec image originale + texte OCR invisible (Tesseract natif)
# ---------------------------------------------------------------------------

def generate_text_pdf(
    text: str,
    output_dir: str,
    base_name: str,
    meta: dict | None = None,
    image_path: str | None = None,
) -> str | None:
    if image_path and os.path.exists(image_path):
        return _generate_searchable_pdf(image_path, output_dir, base_name)
    return _generate_text_only_pdf(text, output_dir, base_name, meta)


def _generate_searchable_pdf(image_path: str, output_dir: str, base_name: str) -> str | None:
    try:
        enhanced_path = enhance_image(image_path, output_dir=None)
        cleanup_enhanced = (enhanced_path != image_path)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_base = os.path.join(tmp, "out")
            subprocess.run(
                ["tesseract", enhanced_path, tmp_base, "-l", "fra+eng", "--dpi", "300", "pdf"],
                check=True, capture_output=True,
            )
            tmp_pdf = tmp_base + ".pdf"
            if not os.path.exists(tmp_pdf):
                raise FileNotFoundError("Tesseract n'a pas produit de PDF")
            dest = os.path.join(output_dir, base_name + "_scan.pdf")
            shutil.move(tmp_pdf, dest)
        if cleanup_enhanced and os.path.exists(enhanced_path):
            os.remove(enhanced_path)
        logger.info(f"[pdf-scan] PDF searchable généré : {dest}")
        return dest
    except subprocess.CalledProcessError as e:
        logger.error(f"[pdf-scan] Tesseract erreur : {e.stderr.decode()}")
        return None
    except Exception as e:
        logger.error(f"[pdf-scan] Erreur : {e}")
        return None


def _generate_text_only_pdf(
    text: str, output_dir: str, base_name: str, meta: dict | None
) -> str | None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

        pdf_path = os.path.join(output_dir, base_name + "_ocr.pdf")
        meta = meta or {}
        doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                                leftMargin=2.5*cm, rightMargin=2.5*cm,
                                topMargin=2.5*cm, bottomMargin=2.5*cm)
        styles = getSampleStyleSheet()
        body = ParagraphStyle("Body", parent=styles["Normal"],
                              fontSize=10, leading=15,
                              textColor=colors.HexColor("#1f2937"), spaceAfter=6)
        story = []
        if meta.get("category"):
            story.append(Paragraph(meta["category"], styles["Heading1"]))
        if meta.get("summary"):
            story.append(Paragraph(f"<i>{meta['summary']}</i>", styles["Normal"]))
            story.append(Spacer(1, 0.4*cm))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e5e7eb")))
        story.append(Spacer(1, 0.3*cm))
        for line in (text or "").splitlines():
            safe = line.strip().replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            story.append(Paragraph(safe, body) if safe else Spacer(1, 0.2*cm))
        doc.build(story)
        logger.info(f"[pdf-text] PDF texte généré : {pdf_path}")
        return pdf_path
    except Exception as e:
        logger.error(f"[pdf-text] Erreur : {e}")
        return None


# ---------------------------------------------------------------------------
# OCR avec score de confiance
# ---------------------------------------------------------------------------

def extract_text_with_confidence(file_path: str) -> tuple[str, float]:
    if file_path.lower().endswith(".pdf"):
        return _extract_pdf_text(file_path), 100.0
    try:
        img = Image.open(file_path)
        data = pytesseract.image_to_data(img, lang="fra+eng", output_type=pytesseract.Output.DICT)
        confidences = [int(c) for c in data["conf"] if int(c) >= 0]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        text = pytesseract.image_to_string(img, lang="fra+eng").strip()
        logger.info(f"[ocr] Confiance moyenne : {avg_conf:.1f}% ({len(confidences)} mots)")
        return text, avg_conf
    except Exception as e:
        logger.error(f"[ocr] Erreur Tesseract : {e}")
        return "", 0.0

def _extract_pdf_text(file_path: str) -> str:
    text = ""
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text.strip()


def _pdf_page_to_image(file_path: str, page: int = 0) -> str | None:
    """
    Convertit une page d'un PDF en image PNG temporaire.
    Utilise pdf2image (poppler) si disponible, sinon tente PyMuPDF (fitz).
    Retourne le chemin de l'image temporaire, ou None en cas d'échec.
    """
    tmp_path = None
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(file_path, first_page=page + 1, last_page=page + 1, dpi=200)
        if images:
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp_path = tmp.name
            tmp.close()
            images[0].save(tmp_path, "PNG")
            logger.info(f"[pdf→img] Page {page} extraite via pdf2image : {tmp_path}")
            return tmp_path
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"[pdf→img] pdf2image échoué : {e}")

    try:
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        pix = doc[page].get_pixmap(dpi=200)
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()
        pix.save(tmp_path)
        logger.info(f"[pdf→img] Page {page} extraite via PyMuPDF : {tmp_path}")
        return tmp_path
    except ImportError:
        logger.warning("[pdf→img] Ni pdf2image ni PyMuPDF disponibles — fallback PDF scanné impossible")
    except Exception as e:
        logger.warning(f"[pdf→img] PyMuPDF échoué : {e}")

    return None


# ---------------------------------------------------------------------------
# Correction OCR — indépendante (texte seul)
# ---------------------------------------------------------------------------

def correct_ocr_with_llm(text: str, confidence: float, config: dict) -> str:
    """
    Correction OCR par LLM texte uniquement.
    Activée si ocr_llm_correction=True ET confiance < seuil.
    Totalement indépendante de la configuration vision.
    """
    if not text.strip():
        return text
    if not config.get("ocr_llm_correction", True):
        return text
    threshold = config.get("ocr_correction_threshold", 80)
    if confidence >= threshold:
        logger.info(f"[ocr-correction] Confiance {confidence:.0f}% ≥ seuil {threshold}% → pas de correction")
        return text

    logger.info(f"[ocr-correction] Confiance {confidence:.0f}% < seuil {threshold}% → correction LLM")
    prompt = OCR_CORRECTION_PROMPT.format(confidence=f"{confidence:.0f}")
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
# Correction OCR avec fusion vision — utilisée dans la voie b) vision activée
# ---------------------------------------------------------------------------

def correct_ocr_with_vision_fusion(
    file_path: str, ocr_text: str, confidence: float,
    config: dict, vision_context: dict | None = None
) -> str:
    """
    Correction OCR avancée : image + texte OCR + contexte JSON vision préliminaire.
    Le contexte vision enrichit la correction pour aligner noms, montants, dates.
    Fallback sur correct_ocr_with_llm si erreur vision.
    """
    if not ocr_text.strip():
        return ocr_text
    if not config.get("ocr_llm_correction", True):
        return ocr_text

    threshold = config.get("ocr_correction_threshold", 80)
    if confidence >= threshold and not vision_context:
        logger.info(f"[ocr-fusion] Confiance {confidence:.0f}% ≥ seuil, pas de fusion nécessaire")
        return correct_ocr_with_llm(ocr_text, confidence, config)

    logger.info(f"[ocr-fusion] Correction avec fusion vision (confiance={confidence:.0f}%)")
    try:
        mime, b64 = _image_to_base64(file_path)
        client, model = _get_vision_client(config)
        ctx_str = json.dumps(vision_context, ensure_ascii=False) if vision_context else "Non disponible"
        prompt = OCR_VISION_FUSION_PROMPT.format(
            confidence=f"{confidence:.0f}",
            vision_context=ctx_str[:500],
            ocr_text=ocr_text[:3000],
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            temperature=0.1,
            max_tokens=2000,
        )
        corrected = response.choices[0].message.content.strip()
        logger.info(f"[ocr-fusion] Texte corrigé ({len(corrected)} chars)")
        return corrected
    except Exception as e:
        logger.warning(f"[ocr-fusion] Erreur vision, fallback correction texte : {e}")
        return correct_ocr_with_llm(ocr_text, confidence, config)


# ---------------------------------------------------------------------------
# Vision — client et utilitaires
# ---------------------------------------------------------------------------

def _get_vision_client(config: dict) -> tuple:
    provider = config.get("vision_provider", "local")
    v_model  = config.get("vision_model") or config.get("model", "")
    v_key    = config.get("vision_api_key") or config.get("api_key", "")
    v_url    = config.get("vision_base_url") or config.get("base_url", "")

    if provider == "openai":
        return OpenAI(api_key=v_key or os.getenv("OPENAI_API_KEY", "")), v_model or "gpt-4o"
    elif provider == "anthropic":
        return OpenAI(
            base_url="https://api.anthropic.com/v1",
            api_key=v_key or os.getenv("ANTHROPIC_API_KEY", ""),
        ), v_model or "claude-3-5-sonnet-20241022"
    elif provider == "gemini":
        return OpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=v_key or os.getenv("GEMINI_API_KEY", ""),
        ), v_model or "gemini-2.5-flash-preview-05-20"
    else:
        return OpenAI(base_url=v_url, api_key=v_key), v_model or config.get("model", "local-model")

def _image_to_base64(file_path: str) -> tuple[str, str]:
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".bmp": "image/bmp",
                ".tiff": "image/tiff", ".webp": "image/webp"}
    mime = mime_map.get(ext, "image/jpeg")
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return mime, b64


def analyze_with_vision(file_path: str, config: dict) -> dict:
    """Voie a) : Image base64 → LLM multimodal → JSON structuré."""
    logger.info(f"[vision-a] Analyse vision directe : {file_path}")
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
        logger.info(f"[vision-a] {result.get('category')} — {result.get('summary')}")
        return result
    except json.JSONDecodeError:
        logger.warning("[vision-a] JSON invalide")
        return {"category": "Autre", "summary": "Analyse vision impossible (JSON invalide)",
                "date": None, "amount": None, "issuer": None, "extracted_text": ""}
    except Exception as e:
        logger.error(f"[vision-a] Erreur : {e}")
        return {"category": "Erreur", "summary": str(e)[:100],
                "date": None, "amount": None, "issuer": None, "extracted_text": ""}


# ---------------------------------------------------------------------------
# Analyse texte standard par LLM
# ---------------------------------------------------------------------------

def analyze_with_llm(text: str, config: dict | None = None) -> dict:
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


def _merge_analyses(vision_json: dict, ocr_json: dict) -> dict:
    """
    Fusionne les deux JSON (voie a et voie b).
    Priorité à la voie b (OCR corrigé + LLM) pour le texte structuré,
    mais garde les champs vision si la voie b a échoué ou est moins précise.
    """
    merged = {**vision_json}
    for key in ("category", "summary", "date", "amount", "issuer"):
        val_b = ocr_json.get(key)
        if val_b and val_b not in ("Erreur", "Autre", None):
            merged[key] = val_b
    merged["extracted_text"] = vision_json.get("extracted_text", "")
    merged["pipeline_sources"] = ["vision", "ocr+llm"]
    return merged


# ---------------------------------------------------------------------------
# Règles de reclassification personnalisées
# ---------------------------------------------------------------------------

def apply_classification_rules(analysis: dict, text: str = "") -> dict:
    """Applique les règles de reclassification personnalisées (conditions AND) après l'analyse LLM."""
    try:
        from database import SessionLocal, ClassificationRule, RuleCondition
        db = SessionLocal()
        rules = (
            db.query(ClassificationRule)
            .filter(ClassificationRule.enabled == "true")
            .order_by(ClassificationRule.priority.desc())
            .all()
        )

        for rule in rules:
            conditions = db.query(RuleCondition).filter(RuleCondition.rule_id == rule.id).all()
            if not conditions:
                continue

            all_match = True
            for cond in conditions:
                field = cond.match_field
                value = (cond.match_value or "").lower().strip()

                if field == "issuer":
                    haystack = (analysis.get("issuer") or "").lower()
                    if value not in haystack:
                        all_match = False; break
                elif field == "category":
                    haystack = (analysis.get("category") or "").lower()
                    if value not in haystack:
                        all_match = False; break
                elif field == "content":
                    if value not in text.lower():
                        all_match = False; break
                elif field == "amount_not_null":
                    if not analysis.get("amount"):
                        all_match = False; break
                elif field == "amount_null":
                    if analysis.get("amount"):
                        all_match = False; break
                else:
                    continue

            if all_match:
                original = analysis.get("category")
                analysis["category"] = rule.target_category
                logger.info(f"[rules] Règle '{rule.name}' appliquée : {original} → {rule.target_category}")
                break  # La règle prioritaire gagne

        db.close()
    except Exception as e:
        logger.warning(f"[rules] Erreur lors de l'application des règles : {e}")

    return analysis


# ---------------------------------------------------------------------------
# Point d'entrée principal — nouveau pipeline
# ---------------------------------------------------------------------------

def process_document(file_path: str) -> tuple[str, dict]:
    """
    Pipeline complet selon le type de fichier et la configuration.

    PDF natif (texte extractible) :
      PyPDF2 → Texte → LLM → JSON
      (la vision n'est JAMAIS utilisée pour un PDF — inutile et coûteux)

    PDF scanné (texte extrait < seuil) :
      Conversion pages → images → OCR/Vision selon config → LLM → JSON

    Image — Vision DÉSACTIVÉE :
      Enhance → Tesseract OCR → Score confiance → Correction LLM si < seuil → LLM → JSON

    Image — Vision ACTIVÉE (double voie parallèle) :
      Voie a) Image base64 → LLM multimodal → JSON structuré
      Voie b) Tesseract OCR → Score confiance → Fusion/correction avec JSON vision → LLM → JSON
      → Merge des deux JSON (voie b prioritaire sur les champs structurés)

    Retourne (texte_extrait_ou_corrigé, analyse_dict).
    """
    config = get_llm_config()
    ext = os.path.splitext(file_path)[1].lower()
    is_image = ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp")

    # ── Prétraitement image ─────────────────────────────────────────────────
    enhanced_path = file_path
    cleanup_enhanced = False
    if is_image:
        enhanced_path = enhance_image(file_path, output_dir=None)
        cleanup_enhanced = (enhanced_path != file_path)
        if cleanup_enhanced:
            logger.info(f"[processor] Image améliorée : {os.path.basename(enhanced_path)}")

    try:
        # ── Vision ACTIVÉE — double voie parallèle ──────────────────────────
        if is_image and config.get("vision_enabled"):
            logger.info("[processor] Mode VISION activé — double voie parallèle")

            # Lancer les deux voies en parallèle
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                # Voie a) : vision directe
                future_a = executor.submit(analyze_with_vision, enhanced_path, config)
                # Voie b) commence par l'OCR (indépendant)
                future_ocr = executor.submit(extract_text_with_confidence, enhanced_path)

                vision_result = future_a.result()
                ocr_text, confidence = future_ocr.result()

            logger.info(f"[processor] Voie a) JSON vision prêt — Voie b) OCR confiance={confidence:.1f}%")

            # Voie b) : correction/fusion OCR avec contexte vision, puis analyse LLM
            extracted_text = vision_result.get("extracted_text", "") or ocr_text
            if ocr_text.strip() and config.get("ocr_vision_fusion", True):
                corrected_text = correct_ocr_with_vision_fusion(
                    enhanced_path, ocr_text, confidence, config,
                    vision_context={k: v for k, v in vision_result.items() if k != "extracted_text"}
                )
            elif ocr_text.strip():
                corrected_text = correct_ocr_with_llm(ocr_text, confidence, config)
            else:
                corrected_text = extracted_text

            ocr_json = analyze_with_llm(corrected_text, config)
            logger.info(f"[processor] Voie b) JSON OCR+LLM : {ocr_json.get('category')}")

            # Fusion des deux JSON
            final_result = _merge_analyses(vision_result, ocr_json)
            final_result = apply_classification_rules(final_result, corrected_text or extracted_text)
            return corrected_text or extracted_text, final_result

        # ── Vision DÉSACTIVÉE — pipeline OCR classique ──────────────────────
        if is_image:
            ocr_text, confidence = extract_text_with_confidence(enhanced_path)
            logger.info(f"[processor] OCR confiance={confidence:.1f}%")
            corrected_text = correct_ocr_with_llm(ocr_text, confidence, config) if ocr_text.strip() else ocr_text
        else:
            corrected_text = _extract_pdf_text(file_path)
            confidence = 100.0

            # ── Fallback PDF scanné : texte trop court → OCR sur la 1ère page ──
            if len(corrected_text.strip()) < 50:
                logger.info("[processor] PDF scanné détecté (texte insuffisant) — fallback OCR sur page 1")
                page_image_path = _pdf_page_to_image(file_path, page=0)
                if page_image_path:
                    try:
                        if config.get("vision_enabled"):
                            # Réutiliser la voie vision sur l'image extraite
                            vision_result = analyze_with_vision(page_image_path, config)
                            ocr_text, ocr_conf = extract_text_with_confidence(page_image_path)
                            corrected_text = ocr_text or vision_result.get("extracted_text", "")
                            analysis = analyze_with_llm(corrected_text, config)
                            analysis = _merge_analyses(vision_result, analysis)
                            analysis["pipeline_sources"] = ["vision", "ocr+llm"]
                        else:
                            ocr_text, confidence = extract_text_with_confidence(page_image_path)
                            corrected_text = correct_ocr_with_llm(ocr_text, confidence, config) if ocr_text.strip() else ocr_text
                            analysis = analyze_with_llm(corrected_text, config)
                            analysis["pipeline_sources"] = ["ocr+llm"]
                        analysis = apply_classification_rules(analysis, corrected_text)
                        return corrected_text, analysis
                    finally:
                        try:
                            os.remove(page_image_path)
                        except OSError:
                            pass

        analysis = analyze_with_llm(corrected_text, config)
        if confidence < 60 and is_image:
            analysis["ocr_confidence"] = round(confidence, 1)
        analysis = apply_classification_rules(analysis, corrected_text)
        return corrected_text, analysis

    finally:
        if cleanup_enhanced and os.path.exists(enhanced_path):
            try:
                os.remove(enhanced_path)
            except OSError:
                pass
