"""
api/settings.py — Routes de gestion des paramètres applicatifs et des backends LLM.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import Setting, User
from core.security import get_db, get_current_user

router = APIRouter(tags=["Settings"])


@router.get("/backends")
def get_backends():
    """Retourne la liste des backends LLM connus avec leurs URLs et modèles suggérés."""
    from processor import KNOWN_BACKENDS, GEMINI_MODELS
    return {
        "backends": [
            {
                "id":       "lm_studio",
                "label":    "LM Studio",
                "base_url": KNOWN_BACKENDS["lm_studio"],
                "api_key":  "lm-studio",
                "models":   ["local-model"],
                "hint":     "Modèle local via LM Studio",
            },
            {
                "id":       "ollama",
                "label":    "Ollama",
                "base_url": KNOWN_BACKENDS["ollama"],
                "api_key":  "ollama",
                "models":   ["llama3", "mistral", "qwen2.5"],
                "hint":     "Modèle local via Ollama",
            },
            {
                "id":       "openai",
                "label":    "OpenAI",
                "base_url": KNOWN_BACKENDS["openai"],
                "api_key":  "",
                "models":   ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
                "hint":     "Clé API sur platform.openai.com",
            },
            {
                "id":       "gemini",
                "label":    "Google Gemini",
                "base_url": KNOWN_BACKENDS["gemini"],
                "api_key":  "",
                "models":   GEMINI_MODELS,
                "hint":     "Clé API sur aistudio.google.com/apikey",
            },
        ]
    }


@router.get("/settings")
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {s.key: s.value for s in db.query(Setting).all()}


@router.post("/settings")
def update_setting(
    key: str,
    value: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting:
        setting.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.commit()
    return {"message": f"Paramètre '{key}' mis à jour"}
