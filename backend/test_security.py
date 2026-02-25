"""
test_security.py — Tests de sécurité pour PaperFree-AI v0.5.0
"""
import pytest
from fastapi.testclient import TestClient
from main import app
from core.security import create_access_token, create_refresh_token, verify_token
from datetime import timedelta

client = TestClient(app)


# ---------------------------------------------------------------------------
# Tests d'authentification JWT
# ---------------------------------------------------------------------------

def test_login_success():
    """Test login avec credentials valides."""
    # Supposer qu'un utilisateur existe déjà (créé via /setup)
    response = client.post("/login", json={
        "username": "admin",
        "password": "testpassword123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_login_invalid_credentials():
    """Test login avec mauvais credentials."""
    response = client.post("/login", json={
        "username": "admin",
        "password": "wrongpassword"
    })
    assert response.status_code == 401
    assert "Identifiants incorrects" in response.json()["detail"]


def test_refresh_token():
    """Test renouvellement de token."""
    # D'abord se connecter
    login_response = client.post("/login", json={
        "username": "admin",
        "password": "testpassword123"
    })
    refresh_token = login_response.json()["refresh_token"]
    
    # Utiliser le refresh token
    refresh_response = client.post("/refresh", json={
        "refresh_token": refresh_token
    })
    assert refresh_response.status_code == 200
    assert "access_token" in refresh_response.json()


def test_protected_route_without_token():
    """Test accès à route protégée sans token."""
    response = client.get("/documents")
    assert response.status_code == 403  # Forbidden


def test_protected_route_with_valid_token():
    """Test accès à route protégée avec token valide."""
    # Login
    login_response = client.post("/login", json={
        "username": "admin",
        "password": "testpassword123"
    })
    token = login_response.json()["access_token"]
    
    # Requête avec token
    response = client.get("/documents", headers={
        "Authorization": f"Bearer {token}"
    })
    assert response.status_code == 200


def test_token_expiration():
    """Test expiration de token."""
    # Créer un token expiré
    expired_token = create_access_token(
        data={"sub": "admin"},
        expires_delta=timedelta(seconds=-10)  # Déjà expiré
    )
    
    response = client.get("/documents", headers={
        "Authorization": f"Bearer {expired_token}"
    })
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tests de validation des uploads
# ---------------------------------------------------------------------------

def test_upload_invalid_extension():
    """Test upload avec extension non autorisée."""
    # Login
    login_response = client.post("/login", json={
        "username": "admin",
        "password": "testpassword123"
    })
    token = login_response.json()["access_token"]
    
    # Upload fichier .exe (non autorisé)
    response = client.post(
        "/upload",
        files={"file": ("malware.exe", b"fake content", "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 400
    assert "Extension de fichier non autorisée" in response.json()["detail"]


def test_upload_empty_file():
    """Test upload fichier vide."""
    login_response = client.post("/login", json={
        "username": "admin",
        "password": "testpassword123"
    })
    token = login_response.json()["access_token"]
    
    response = client.post(
        "/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 400
    assert "Fichier vide" in response.json()["detail"]


def test_upload_valid_pdf():
    """Test upload PDF valide."""
    login_response = client.post("/login", json={
        "username": "admin",
        "password": "testpassword123"
    })
    token = login_response.json()["access_token"]
    
    # Créer un faux PDF minimal
    pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\n%%EOF"
    
    response = client.post(
        "/upload",
        files={"file": ("test.pdf", pdf_content, "application/pdf")},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert "doc_id" in response.json()


# ---------------------------------------------------------------------------
# Tests de rate limiting
# ---------------------------------------------------------------------------

def test_rate_limit_login():
    """Test rate limit sur /login."""
    # Faire 6 requêtes rapidement (limite = 5/minute)
    for _ in range(6):
        response = client.post("/login", json={
            "username": "admin",
            "password": "wrongpass"
        })
    
    # La 6ème devrait être bloquée
    assert response.status_code == 429  # Too Many Requests


def test_rate_limit_upload():
    """Test rate limit sur /upload."""
    login_response = client.post("/login", json={
        "username": "admin",
        "password": "testpassword123"
    })
    token = login_response.json()["access_token"]
    
    pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\n%%EOF"
    
    # Faire 21 uploads rapidement (limite = 20/minute)
    for i in range(21):
        response = client.post(
            "/upload",
            files={"file": (f"test{i}.pdf", pdf_content, "application/pdf")},
            headers={"Authorization": f"Bearer {token}"}
        )
    
    # Le 21ème devrait être bloqué
    assert response.status_code == 429


# ---------------------------------------------------------------------------
# Tests de sécurité headers
# ---------------------------------------------------------------------------

def test_security_headers():
    """Vérifier la présence des headers de sécurité."""
    response = client.get("/status")
    
    assert "X-Content-Type-Options" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    
    assert "X-Frame-Options" in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"
    
    assert "Strict-Transport-Security" in response.headers
    assert "Content-Security-Policy" in response.headers


# ---------------------------------------------------------------------------
# Tests de validation Pydantic
# ---------------------------------------------------------------------------

def test_setup_invalid_username():
    """Test setup avec username invalide."""
    response = client.post("/setup", json={
        "username": "a",  # Trop court (min 3)
        "password": "validpassword123",
        "llm_url": ""
    })
    assert response.status_code == 422  # Validation error


def test_setup_invalid_password():
    """Test setup avec password trop court."""
    response = client.post("/setup", json={
        "username": "admin",
        "password": "short",  # Trop court (min 8)
        "llm_url": ""
    })
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests CORS
# ---------------------------------------------------------------------------

def test_cors_allowed_origin():
    """Test requête depuis origine autorisée."""
    response = client.get("/status", headers={
        "Origin": "http://localhost:8080"
    })
    assert "Access-Control-Allow-Origin" in response.headers


def test_cors_preflight():
    """Test requête OPTIONS (preflight)."""
    response = client.options("/documents", headers={
        "Origin": "http://localhost:8080",
        "Access-Control-Request-Method": "POST"
    })
    assert response.status_code == 200
    assert "Access-Control-Allow-Methods" in response.headers


# ---------------------------------------------------------------------------
# Tests de logging de sécurité
# ---------------------------------------------------------------------------

def test_security_logging_failed_login(caplog):
    """Vérifier que les login échoués sont loggés."""
    import logging
    caplog.set_level(logging.WARNING)
    
    client.post("/login", json={
        "username": "admin",
        "password": "wrongpassword"
    })
    
    assert "LOGIN_FAILED" in caplog.text
    assert "admin" in caplog.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
