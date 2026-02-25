"""
api/auth.py — Routes publiques d'authentification et de setup initial.
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import SessionLocal, User, Setting
from core.security import get_db, pwd_hasher
from core.config import APP_VERSION

router = APIRouter(tags=["Auth"])


@router.get("/status")
def get_status(db: Session = Depends(get_db)):
    user_exists = db.query(User).first() is not None
    return {"setup_required": not user_exists, "version": APP_VERSION}


@router.post("/setup")
def setup_admin(
    username: str,
    password: str,
    llm_url: str = "",
    db: Session = Depends(get_db),
):
    if db.query(User).first():
        raise HTTPException(status_code=400, detail="Setup déjà effectué")
    db.add(User(username=username, hashed_password=pwd_hasher.hash(password)))
    db.add(Setting(key="llm_base_url", value=llm_url or os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")))
    db.add(Setting(key="llm_model",    value=os.getenv("LLM_MODEL", "local-model")))
    db.add(Setting(key="llm_api_key",  value=os.getenv("LLM_API_KEY", "lm-studio")))
    db.commit()
    return {"message": "Installation réussie"}
