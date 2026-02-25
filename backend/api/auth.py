"""
api/auth.py — Routes d'authentification JWT, login et setup initial.
"""
import os
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, validator

from database import SessionLocal, User, Setting
from core.security import (
    get_db, 
    pwd_hasher, 
    authenticate_user,
    create_access_token,
    create_refresh_token,
    verify_token,
    log_security_event
)
from core.config import APP_VERSION, ACCESS_TOKEN_EXPIRE_MINUTES
from core.middleware import limiter

router = APIRouter(tags=["Auth"])


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class SetupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=100)
    llm_url: str = Field(default="")
    
    @validator('username')
    def username_alphanumeric(cls, v):
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError('Username must be alphanumeric (with _ or - allowed)')
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status")
def get_status(db: Session = Depends(get_db)):
    """Vérifie si le setup initial est requis."""
    user_exists = db.query(User).first() is not None
    return {"setup_required": not user_exists, "version": APP_VERSION}


@router.post("/setup", response_model=dict)
@limiter.limit("3/minute")
def setup_admin(
    request: Request,
    setup_data: SetupRequest,
    db: Session = Depends(get_db),
):
    """
    Setup initial : création du premier utilisateur admin.
    Limité à 3 tentatives/minute pour éviter les abus.
    """
    # Vérifier qu'aucun utilisateur n'existe
    if db.query(User).first():
        log_security_event("SETUP_ATTEMPT_REJECTED", {"reason": "already_configured"}, request)
        raise HTTPException(status_code=400, detail="Setup déjà effectué")
    
    # Créer l'utilisateur admin
    db.add(User(
        username=setup_data.username, 
        hashed_password=pwd_hasher.hash(setup_data.password)
    ))
    
    # Initialiser les settings LLM
    db.add(Setting(
        key="llm_base_url", 
        value=setup_data.llm_url or os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")
    ))
    db.add(Setting(key="llm_model", value=os.getenv("LLM_MODEL", "local-model")))
    db.add(Setting(key="llm_api_key", value=os.getenv("LLM_API_KEY", "lm-studio")))
    
    db.commit()
    
    log_security_event("SETUP_COMPLETED", {"username": setup_data.username}, request)
    return {"message": "Installation réussie"}


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(
    request: Request,
    login_data: LoginRequest,
    db: Session = Depends(get_db),
):
    """
    Authentification par username/password.
    Retourne un access token JWT et un refresh token.
    Limité à 5 tentatives/minute.
    """
    user = authenticate_user(db, login_data.username, login_data.password)
    
    if not user:
        log_security_event("LOGIN_FAILED", {"username": login_data.username}, request)
        raise HTTPException(
            status_code=401,
            detail="Identifiants incorrects"
        )
    
    # Créer les tokens
    access_token = create_access_token(data={"sub": user.username})
    refresh_token = create_refresh_token(data={"sub": user.username})
    
    log_security_event("LOGIN_SUCCESS", {"username": user.username}, request)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
def refresh_token_endpoint(
    request: Request,
    refresh_data: RefreshRequest,
    db: Session = Depends(get_db),
):
    """
    Renouvelle un access token à partir d'un refresh token valide.
    """
    # Vérifier le refresh token
    payload = verify_token(refresh_data.refresh_token, "refresh")
    username = payload.get("sub")
    
    if not username:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    
    # Vérifier que l'utilisateur existe toujours
    user = db.query(User).filter(User.username == username).first()
    if not user:
        log_security_event("REFRESH_FAILED", {"username": username, "reason": "user_not_found"}, request)
        raise HTTPException(status_code=401, detail="User not found")
    
    # Créer un nouveau access token
    access_token = create_access_token(data={"sub": username})
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_data.refresh_token,  # On garde le même refresh token
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
