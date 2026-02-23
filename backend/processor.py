import os
import json
import pytesseract
from PIL import Image
import PyPDF2
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Valeurs par défaut lues depuis .env, avec fallback sur la DB si besoin
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


def extract_text(file_path: str) -> str:
    """Extrait le texte brut d'un PDF ou d'une image."""
    text = ""
    if file_path.lower().endswith(".pdf"):
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    else:
        text = pytesseract.image_to_string(Image.open(file_path))
    return text.strip()


def analyze_with_llm(text: str) -> dict:
    """Envoie le texte au LLM et retourne un dict structuré."""
    config = get_llm_config()
    try:
        client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
        response = client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text[:3000]},
            ],
            temperature=0.1,
        )
        raw = response.choices[0].message.content.strip()
        # Nettoyer les éventuels blocs markdown ```json ... ```
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"category": "Autre", "summary": "Analyse impossible (JSON invalide)", "date": None, "amount": None, "issuer": None}
    except Exception as e:
        return {"category": "Erreur", "summary": str(e)[:100], "date": None, "amount": None, "issuer": None}


def process_document(file_path: str) -> tuple[str, dict]:
    """Retourne (texte_brut, analyse_dict)."""
    text = extract_text(file_path)
    analysis = analyze_with_llm(text)
    return text, analysis
