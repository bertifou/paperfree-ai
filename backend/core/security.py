"""
core/security.py — Authentification JWT, gestion des tokens et sécurité.
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pwdlib import PasswordHash
from sqlalchemy.orm import Session
import logging

from database import SessionLocal, User
from core.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS

logger = logging.getLogger(__name__)
security = HTTPBearer()
pwd_hasher = PasswordHash.recommended()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Crée un JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """Crée un JWT refresh token avec expiration longue."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str, token_type: str = "access") -> dict:
    """Vérifie et décode un JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != token_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token type, expected {token_type}"
            )
        return payload
    except JWTError as e:
        logger.warning(f"Token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Récupère l'utilisateur courant depuis le JWT token."""
    token = credentials.credentials
    payload = verify_token(token, "access")
    username: str = payload.get("sub")
    
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )
    
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        logger.warning(f"User not found in database: {username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    return user


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Authentifie un utilisateur et log les tentatives échouées."""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        logger.warning(f"Failed login attempt - user not found: {username}")
        return None
    
    if not pwd_hasher.verify(password, user.hashed_password):
        logger.warning(f"Failed login attempt - invalid password for user: {username}")
        return None
    
    logger.info(f"Successful login: {username}")
    return user


def log_security_event(event_type: str, details: dict, request: Request = None):
    """Log des événements de sécurité importants."""
    ip = request.client.host if request else "unknown"
    logger.warning(f"SECURITY [{event_type}] IP={ip} | {details}")
