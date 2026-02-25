# Core Security Architecture

Ce dossier contient les modules de sécurité de PaperFree-AI.

---

## 📁 Structure

```
core/
├── config.py           # Configuration globale et constantes de sécurité
├── security.py         # Authentification JWT et gestion des utilisateurs
├── middleware.py       # Middlewares de sécurité HTTP et rate limiting
├── validators.py       # Validation des uploads et sécurité des fichiers
└── logging_filter.py   # Filtres de logs pour masquer les données sensibles
```

---

## 🔐 Modules

### `config.py` - Configuration

Définit toutes les constantes de sécurité :

- **JWT** : `SECRET_KEY`, `ALGORITHM`, durées d'expiration
- **Uploads** : Taille max, extensions autorisées, types MIME
- **Rate Limiting** : Limites par endpoint
- **CORS** : Origines autorisées

**Variables d'environnement** :
- `SECRET_KEY` (obligatoire) : Clé secrète pour JWT
- `ALLOWED_ORIGINS` : Liste des origines CORS autorisées
- `MAX_UPLOAD_SIZE_MB` : Taille maximale des uploads

### `security.py` - Authentification JWT

**Fonctions principales** :

- `create_access_token()` : Génère un token d'accès (60 min)
- `create_refresh_token()` : Génère un token de renouvellement (30 jours)
- `verify_token()` : Vérifie et décode un JWT
- `get_current_user()` : Dépendance FastAPI pour l'authentification
- `authenticate_user()` : Vérifie username/password
- `log_security_event()` : Log les événements de sécurité

**Utilisation** :

```python
from core.security import get_current_user

@router.get("/protected")
def protected_route(current_user: User = Depends(get_current_user)):
    return {"user": current_user.username}
```

### `middleware.py` - Middlewares de Sécurité

#### SecurityHeadersMiddleware

Ajoute automatiquement les headers de sécurité HTTP à toutes les réponses :

- `Strict-Transport-Security` (HSTS)
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection`
- `Content-Security-Policy`
- `Referrer-Policy`
- `Permissions-Policy`

#### Rate Limiting

Configuration globale du rate limiter avec `slowapi`.

**Utilisation** :

```python
from core.middleware import limiter

@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, ...):
    ...
```

### `validators.py` - Validation des Uploads

**Fonctions de validation** :

- `validate_file_upload()` : Vérifie extension et type MIME déclaré
- `validate_file_content()` : Vérifie taille et type MIME réel (magic bytes)
- `sanitize_filename()` : Nettoie les noms de fichiers (anti path-traversal)

**Liste blanche** :

```python
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/tiff"
}
```

**Utilisation** :

```python
from core.validators import validate_file_upload, validate_file_content, sanitize_filename

@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    validate_file_upload(file)
    content = await file.read()
    await validate_file_content(file, content)
    safe_name = sanitize_filename(file.filename)
    ...
```

---

## 🔍 Flux d'Authentification

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │
       │ POST /login
       │ {username, password}
       ▼
┌─────────────────────┐
│  authenticate_user  │
│  (security.py)      │
└──────┬──────────────┘
       │
       │ User found & password OK
       ▼
┌─────────────────────┐
│ create_access_token │
│ create_refresh_token│
└──────┬──────────────┘
       │
       │ Return tokens
       ▼
┌─────────────┐
│   Client    │
│ Store tokens│
└──────┬──────┘
       │
       │ GET /documents
       │ Authorization: Bearer <token>
       ▼
┌─────────────────────┐
│  get_current_user   │
│  verify_token       │
└──────┬──────────────┘
       │
       │ Token valid
       ▼
┌─────────────┐
│  Response   │
└─────────────┘
```

---

## 🛡️ Flux de Validation d'Upload

```
┌─────────────┐
│   Upload    │
└──────┬──────┘
       │
       ▼
┌──────────────────────┐
│ validate_file_upload │
│ - Extension OK?      │
│ - MIME déclaré OK?   │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ Read file content    │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│validate_file_content │
│ - Size < max?        │
│ - Real MIME OK?      │
│   (magic bytes)      │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ sanitize_filename    │
│ - Remove ../         │
│ - Remove special chars│
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ Safe to save         │
└──────────────────────┘
```

---

## 📊 Logging de Sécurité

Tous les événements de sécurité sont loggés avec :

- Type d'événement (LOGIN_FAILED, DOCUMENT_UPLOADED, etc.)
- IP source
- Username
- Timestamp
- Détails additionnels

**Exemple de log** :

```
WARNING SECURITY [LOGIN_FAILED] IP=192.168.1.100 | {'username': 'admin'}
INFO SECURITY [DOCUMENT_UPLOADED] IP=192.168.1.100 | {'doc_id': 42, 'filename': 'facture.pdf', 'user': 'admin'}
```

---

## 🔧 Configuration Recommandée

### Production

```env
# .env
SECRET_KEY=VotreCléGénéréeAléatoirement  # OBLIGATOIRE
ALLOWED_ORIGINS=https://app.example.com,https://mobile.example.com
MAX_UPLOAD_SIZE_MB=50
```

### Développement

```env
# .env
SECRET_KEY=dev-secret-key-not-for-production
ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
MAX_UPLOAD_SIZE_MB=100
```

---

## 🧪 Tests

Exécuter les tests de sécurité :

```bash
cd backend
pytest test_security.py -v
```

---

## 📚 Ressources

- [JWT Best Practices](https://tools.ietf.org/html/rfc8725)
- [OWASP Security Headers](https://owasp.org/www-project-secure-headers/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Rate Limiting Guide](https://cloud.google.com/architecture/rate-limiting-strategies-techniques)

---

**Dernière mise à jour** : v0.5.0 - Février 2025
