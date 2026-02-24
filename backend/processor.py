import os
import json
import base64
import logging
import math

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import PyPDF2
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config LLM
# ---------------------------------------------------------------------------
DEFAULT_LLM_CONFIG = {
    "base_url": os.getenv("LLM_BASE_URL", "http://localhost:1234/v1"),
    "api_key":  os.getenv("LLM_API_KEY",  "lm-studio"),
    "model":    os.getenv("LLM_MODEL",    "local-model"),
}

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

VISION_PROMPT = """Tu es un assistant spécialisé dans l'analyse de documents administratifs photographiés.
Lis attentivement ce document et réponds UNIQUEMENT avec un objet JSON valide contenant :
{
  "category": "une catégorie parmi : Facture, Impôts, Santé, Banque, Contrat, Assurance, Travail, Courrier, Autre",
  "summary": "résumé en 15 mots maximum",
  "date": "date principale du document au format YYYY-MM-DD ou null",
  "amount": "montant principal en chiffres avec devise ou null",
  "issuer": "organisme ou entreprise émettrice ou null",
  "ocr_text": "le texte complet que tu lis dans l'image, fidèlement retranscrit"
}
Ne réponds rien d'autre que le JSON."""


def get_llm_config():
    """Lit la config LLM depuis la DB, avec fallback sur les variables d'env."""
    try:
        from database import SessionLocal, Setting
        db = SessionLocal()
        settings = {s.key: s.value for s in db.query(Setting).all()}
        db.close()
        return {
            "base_url": settings.get("llm_base_url") or DEFAULT_LLM_CONFIG["base_url"],
            "api_key":  settings.get("llm_api_key")  or DEFAULT_LLM_CONFIG["api_key"],
            "model":    settings.get("llm_model")    or DEFAULT_LLM_CONFIG["model"],
        }
    except Exception:
        return DEFAULT_LLM_CONFIG


# ---------------------------------------------------------------------------
# Prétraitement image — Pipeline OpenCV
# ---------------------------------------------------------------------------

def _try_import_cv2():
    """Importe OpenCV si disponible."""
    try:
        import cv2
        import numpy as np
        return cv2, np
    except ImportError:
        logger.warning("[processor] OpenCV non disponible — prétraitement de base uniquement")
        return None, None


def _correct_perspective(img_cv2, cv2, np):
    """
    Détecte les bords du document et corrige la perspective.
    Retourne l'image corrigée, ou l'originale si la détection échoue.
    """
    try:
        gray = cv2.cvtColor(img_cv2, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)

        # Dilatation pour connecter les bords
        kernel = np.ones((5, 5), np.uint8)
        dilated = cv2.dilate(edges, kernel, iterations=2)

        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return img_cv2

        # Trouver le plus grand contour quadrilatère
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        doc_contour = None

        for cnt in contours[:5]:
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            if len(approx) == 4:
                area = cv2.contourArea(approx)
                img_area = img_cv2.shape[0] * img_cv2.shape[1]
                # Le document doit couvrir au moins 20% de l'image
                if area > 0.20 * img_area:
                    doc_contour = approx
                    break

        if doc_contour is None:
            return img_cv2

        # Ordonner les points : haut-gauche, haut-droit, bas-droit, bas-gauche
        pts = doc_contour.reshape(4, 2).astype(np.float32)
        s = pts.sum(axis=1)
        diff = np.diff(pts, axis=1)
        ordered = np.array([
            pts[np.argmin(s)],    # haut-gauche
            pts[np.argmin(diff)], # haut-droit
            pts[np.argmax(s)],    # bas-droit
            pts[np.argmax(diff)], # bas-gauche
        ], dtype=np.float32)

        # Calcul des dimensions cibles
        wA = np.linalg.norm(ordered[2] - ordered[3])
        wB = np.linalg.norm(ordered[1] - ordered[0])
        hA = np.linalg.norm(ordered[1] - ordered[2])
        hB = np.linalg.norm(ordered[0] - ordered[3])
        W = int(max(wA, wB))
        H = int(max(hA, hB))

        if W < 100 or H < 100:
            return img_cv2

        dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype=np.float32)
        M = cv2.getPerspectiveTransform(ordered, dst)
        warped = cv2.warpPerspective(img_cv2, M, (W, H))
        logger.info(f"[processor] Correction perspective appliquée → {W}x{H}")
        return warped

    except Exception as e:
        logger.warning(f"[processor] Correction perspective échouée : {e}")
        return img_cv2


def _auto_rotate(img_cv2, cv2, np):
    """
    Détecte et corrige la rotation du document (texte incliné).
    Utilise les lignes de texte pour détecter l'angle.
    """
    try:
        gray = cv2.cvtColor(img_cv2, cv2.COLOR_BGR2GRAY)
        # Utiliser Tesseract OSD pour détecter la rotation
        pil_img = Image.fromarray(cv2.cvtColor(img_cv2, cv2.COLOR_BGR2RGB))
        osd = pytesseract.image_to_osd(pil_img, config="--psm 0 -c min_characters_to_try=5",
                                       output_type=pytesseract.Output.DICT)
        angle = osd.get("rotate", 0)
        if angle and angle != 0:
            logger.info(f"[processor] Rotation détectée : {angle}°")
            h, w = img_cv2.shape[:2]
            M = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
            rotated = cv2.warpAffine(img_cv2, M, (w, h),
                                     flags=cv2.INTER_CUBIC,
                                     borderMode=cv2.BORDER_REPLICATE)
            return rotated
    except Exception:
        pass
    return img_cv2


def preprocess_image_for_ocr(file_path: str) -> Image.Image:
    """
    Pipeline de prétraitement complet pour optimiser l'OCR sur photos de documents.
    Retourne une image PIL prête pour Tesseract.
    """
    cv2, np = _try_import_cv2()

    # --- Pillow seul si OpenCV absent ---
    if cv2 is None:
        return _preprocess_pillow_only(file_path)

    # === Pipeline OpenCV ===
    img = cv2.imread(file_path)
    if img is None:
        # Fallback via Pillow (HEIC, formats exotiques)
        pil = Image.open(file_path).convert("RGB")
        img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    logger.info(f"[processor] Image originale : {img.shape[1]}x{img.shape[0]}")

    # 1. Upscaling si trop petite (Tesseract aime les images à ~300 DPI)
    h, w = img.shape[:2]
    min_dim = 1800  # pixels
    if max(w, h) < min_dim:
        scale = min_dim / max(w, h)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        logger.info(f"[processor] Upscaling ×{scale:.1f} → {img.shape[1]}x{img.shape[0]}")

    # 2. Correction de perspective (redressement du document)
    img = _correct_perspective(img, cv2, np)

    # 3. Auto-rotation
    img = _auto_rotate(img, cv2, np)

    # 4. Conversion en niveaux de gris
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 5. Correction d'éclairage non uniforme (ombres, reflets)
    #    Utilise un flou gaussien large comme fond de référence
    bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=50)
    normalized = cv2.divide(gray, bg, scale=255)

    # 6. Débruitage
    denoised = cv2.fastNlMeansDenoising(normalized, h=10, templateWindowSize=7, searchWindowSize=21)

    # 7. Binarisation adaptative (meilleure que le seuillage global pour les photos)
    binary = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=21,
        C=10,
    )

    # 8. Légère dilatation pour reconnecter les lettres fragmentées
    kernel = np.ones((1, 1), np.uint8)
    binary = cv2.dilate(binary, kernel, iterations=1)

    # Convertir en PIL pour Tesseract
    result = Image.fromarray(binary)
    logger.info(f"[processor] Prétraitement terminé → {result.size[0]}x{result.size[1]} (L)")
    return result


def _preprocess_pillow_only(file_path: str) -> Image.Image:
    """Prétraitement léger sans OpenCV."""
    img = Image.open(file_path).convert("RGB")

    # Upscaling
    w, h = img.size
    if max(w, h) < 1800:
        scale = 1800 / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    # Netteté
    img = img.filter(ImageFilter.SHARPEN)
    img = img.filter(ImageFilter.SHARPEN)

    # Contraste
    img = ImageEnhance.Contrast(img).enhance(1.8)
    img = ImageEnhance.Sharpness(img).enhance(2.0)

    # Niveaux de gris
    gray = img.convert("L")
    return gray


# ---------------------------------------------------------------------------
# OCR Tesseract
# ---------------------------------------------------------------------------

TESSERACT_CONFIG = (
    "--oem 3 "        # LSTM engine (le plus précis)
    "--psm 1 "        # Segmentation auto avec OSD
    "-l fra+eng "     # Français + Anglais
    "--dpi 300 "      # Indiquer la résolution
    "-c preserve_interword_spaces=1 "
    "-c tessedit_char_whitelist="
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "ÀÂÄÈÉÊËÎÏÔÙÛÜÇàâäèéêëîïôùûüç"
    "0123456789 .,;:!?@#€$%&*()-_=+[]{}|/<>\"'\\n\\t"
)

def _ocr_image(pil_img: Image.Image) -> str:
    """Lance Tesseract avec config optimisée."""
    try:
        text = pytesseract.image_to_string(pil_img, config=TESSERACT_CONFIG)
        return text.strip()
    except Exception:
        # Fallback config minimale
        try:
            return pytesseract.image_to_string(
                pil_img, lang="fra+eng", config="--oem 3 --psm 6"
            ).strip()
        except Exception as e:
            logger.error(f"[processor] OCR échoué : {e}")
            return ""


def _ocr_quality_score(text: str) -> float:
    """
    Retourne un score 0-1 de qualité du texte OCR.
    Un score bas indique que le résultat est probablement mauvais.
    """
    if not text or len(text.strip()) < 10:
        return 0.0

    words = text.split()
    if len(words) < 3:
        return 0.1

    # Ratio de caractères valides vs bruit
    valid_chars = sum(1 for c in text if c.isalnum() or c in " .,;:!?\n€$%-")
    noise_ratio = 1 - (valid_chars / max(len(text), 1))

    # Trop de lignes avec < 2 caractères = bruit
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    short_lines = sum(1 for l in lines if len(l) < 3)
    short_ratio = short_lines / max(len(lines), 1)

    score = 1.0 - (noise_ratio * 0.6) - (short_ratio * 0.4)
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Fallback Vision LLM
# ---------------------------------------------------------------------------

def _analyze_with_vision_llm(file_path: str, config: dict) -> tuple[str, dict] | None:
    """
    Envoie l'image au LLM avec capacités Vision (GPT-4V, LLaVA, etc.)
    Retourne (texte_ocr, analyse_dict) ou None si le LLM ne supporte pas la vision.
    """
    try:
        with open(file_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        # Détecter le type MIME
        ext = os.path.splitext(file_path)[1].lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".bmp": "image/bmp",
                    ".tiff": "image/tiff", ".webp": "image/webp"}
        mime = mime_map.get(ext, "image/jpeg")

        client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
        response = client.chat.completions.create(
            model=config["model"],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{img_b64}"},
                        },
                        {"type": "text", "text": VISION_PROMPT},
                    ],
                }
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        ocr_text = result.pop("ocr_text", "")
        logger.info("[processor] Vision LLM utilisé avec succès")
        return ocr_text, result

    except Exception as e:
        logger.info(f"[processor] Vision LLM non disponible : {e}")
        return None


# ---------------------------------------------------------------------------
# Extraction texte
# ---------------------------------------------------------------------------

def extract_text(file_path: str) -> str:
    """Extrait le texte brut d'un PDF ou d'une image avec prétraitement."""
    if file_path.lower().endswith(".pdf"):
        return _extract_pdf_text(file_path)
    return _extract_image_text(file_path)


def _extract_pdf_text(file_path: str) -> str:
    """Extrait le texte d'un PDF natif, avec fallback OCR si le PDF est scanné."""
    text = ""
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        logger.error(f"[processor] Erreur lecture PDF : {e}")

    # Si le PDF est vide (PDF scanné), faire OCR page par page
    if len(text.strip()) < 50:
        logger.info("[processor] PDF semble scanné — tentative OCR")
        try:
            import fitz  # PyMuPDF (optionnel)
            doc = fitz.open(file_path)
            for page in doc:
                mat = fitz.Matrix(2.0, 2.0)  # ×2 résolution
                pix = page.get_pixmap(matrix=mat)
                pil = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                text += _ocr_image(pil) + "\n"
        except ImportError:
            logger.info("[processor] PyMuPDF absent — PDF scanné non traité")
        except Exception as e:
            logger.error(f"[processor] OCR PDF scanné échoué : {e}")

    return text.strip()


def _extract_image_text(file_path: str) -> str:
    """Pipeline complet d'extraction depuis une image photo."""
    # 1. Prétraitement
    processed = preprocess_image_for_ocr(file_path)

    # 2. OCR Tesseract
    text = _ocr_image(processed)
    score = _ocr_quality_score(text)
    logger.info(f"[processor] OCR qualité : {score:.2f} | {len(text)} chars")

    # 3. Si qualité insuffisante, essayer d'autres configs PSM
    if score < 0.5:
        logger.info("[processor] Qualité OCR faible — tentative PSM alternatifs")
        best_text = text
        best_score = score

        for psm in [3, 4, 6, 11]:
            try:
                alt_text = pytesseract.image_to_string(
                    processed, lang="fra+eng",
                    config=f"--oem 3 --psm {psm} --dpi 300"
                ).strip()
                alt_score = _ocr_quality_score(alt_text)
                if alt_score > best_score:
                    best_text, best_score = alt_text, alt_score
                    logger.info(f"[processor] PSM {psm} améliore : score {alt_score:.2f}")
            except Exception:
                pass

        text = best_text
        score = best_score

    logger.info(f"[processor] Texte final OCR : {len(text)} chars | score {score:.2f}")
    return text


# ---------------------------------------------------------------------------
# Analyse LLM
# ---------------------------------------------------------------------------

def analyze_with_llm(text: str, file_path: str = None, ocr_score: float = 1.0) -> dict:
    """
    Analyse le texte avec le LLM.
    Si l'OCR est de mauvaise qualité ET que le LLM supporte la vision,
    utilise directement l'image.
    """
    config = get_llm_config()

    # Tenter Vision LLM si OCR de mauvaise qualité et qu'on a le fichier image
    if file_path and ocr_score < 0.4 and not file_path.lower().endswith(".pdf"):
        logger.info("[processor] OCR insuffisant → tentative Vision LLM")
        vision_result = _analyze_with_vision_llm(file_path, config)
        if vision_result:
            return vision_result[1]  # retourner uniquement l'analyse

    # Analyse texte standard
    try:
        client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
        response = client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text[:4000]},
            ],
            temperature=0.1,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
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
    Retourne (texte_brut, analyse_dict).
    Pipeline amélioré avec prétraitement image et fallback Vision LLM.
    """
    is_image = not file_path.lower().endswith(".pdf")

    if is_image:
        processed = preprocess_image_for_ocr(file_path)
        text = _ocr_image(processed)
        score = _ocr_quality_score(text)

        # Essayer PSM alternatifs si qualité faible
        if score < 0.5:
            best_text, best_score = text, score
            for psm in [3, 4, 6, 11]:
                try:
                    alt = pytesseract.image_to_string(
                        processed, lang="fra+eng",
                        config=f"--oem 3 --psm {psm} --dpi 300"
                    ).strip()
                    s = _ocr_quality_score(alt)
                    if s > best_score:
                        best_text, best_score = alt, s
                except Exception:
                    pass
            text, score = best_text, best_score
    else:
        text = extract_text(file_path)
        score = _ocr_quality_score(text) if text else 0.0

    # Analyse LLM (avec fallback vision si image de mauvaise qualité)
    analysis = analyze_with_llm(text, file_path=file_path if is_image else None, ocr_score=score)

    # Si Vision LLM a fourni un texte OCR meilleur, l'utiliser
    if isinstance(analysis, tuple):
        text_from_vision, analysis = analysis
        if text_from_vision and len(text_from_vision) > len(text):
            text = text_from_vision

    logger.info(f"[processor] Traitement terminé : {analysis.get('category')} | score OCR {score:.2f}")
    return text, analysis
