# 🤝 Guide de Contribution

Merci de votre intérêt pour contribuer à PaperFree-AI ! Ce guide vous aidera à soumettre des contributions de qualité.

---

## 📋 Table des Matières

- [Code de Conduite](#code-de-conduite)
- [Comment Contribuer](#comment-contribuer)
- [Standards de Code](#standards-de-code)
- [Standards de Sécurité](#standards-de-sécurité)
- [Tests](#tests)
- [Documentation](#documentation)

---

## 📜 Code de Conduite

- Soyez respectueux et inclusif
- Acceptez les critiques constructives
- Concentrez-vous sur ce qui est meilleur pour la communauté
- Faites preuve d'empathie envers les autres membres

---

## 🔧 Comment Contribuer

### 1. Fork et Clone

```bash
git clone https://github.com/VOTRE-USERNAME/paperfree-ai.git
cd paperfree-ai
```

### 2. Créer une branche

```bash
git checkout -b feature/ma-nouvelle-fonctionnalite
# ou
git checkout -b fix/correction-bug
```

### 3. Développer et tester

```bash
# Installer les dépendances
cd backend
pip install -r requirements.txt

# Lancer les tests
pytest

# Vérifier la sécurité
cd ..
python check_security.py
```

### 4. Commit

Utilisez des messages de commit clairs :

```bash
git commit -m "feat: Ajout authentification 2FA"
git commit -m "fix: Correction validation MIME types"
git commit -m "docs: Mise à jour guide de sécurité"
```

Format recommandé :
- `feat:` Nouvelle fonctionnalité
- `fix:` Correction de bug
- `docs:` Documentation
- `style:` Formatage
- `refactor:` Refactoring
- `test:` Ajout de tests
- `chore:` Maintenance

### 5. Push et Pull Request

```bash
git push origin feature/ma-nouvelle-fonctionnalite
```

Créez une Pull Request sur GitHub avec :
- Description claire des changements
- Référence aux issues liées
- Screenshots si applicable
- Résultats des tests

---

## 💻 Standards de Code

### Python (Backend)

- **Style** : PEP 8
- **Formatage** : Black (ou autopep8)
- **Linting** : flake8, pylint
- **Type hints** : Encouragés

```python
# ✅ BON
def create_token(user: User) -> str:
    """Crée un JWT token pour l'utilisateur."""
    return jwt.encode({"sub": user.username}, SECRET_KEY)

# ❌ MAUVAIS
def create_token(user):
    return jwt.encode({"sub":user.username},SECRET_KEY)
```

### JavaScript (Frontend)

- **Style** : Standard JS ou ESLint
- **Formatage** : Prettier
- **Moderne** : ES6+

```javascript
// ✅ BON
const fetchDocuments = async () => {
  const response = await fetch('/documents', {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  return response.json();
};

// ❌ MAUVAIS
function fetchDocuments() {
  return fetch('/documents', {headers: {'Authorization': 'Bearer ' + token}}).then(r => r.json())
}
```

---

## 🔒 Standards de Sécurité

### ⚠️ RÈGLES CRITIQUES

1. **Ne JAMAIS committer de secrets**
   ```bash
   # ❌ INTERDIT
   git add .env
   
   # ✅ Vérifier avant commit
   git status
   ```

2. **Valider TOUTES les entrées utilisateur**
   ```python
   # ✅ BON
   from pydantic import BaseModel, Field, validator
   
   class LoginRequest(BaseModel):
       username: str = Field(..., min_length=3, max_length=50)
       password: str = Field(..., min_length=8)
       
       @validator('username')
       def username_alphanumeric(cls, v):
           if not v.isalnum():
               raise ValueError('Invalid username')
           return v
   
   # ❌ MAUVAIS
   def login(username, password):
       # Pas de validation !
       user = db.query(User).filter(User.username == username).first()
   ```

3. **Rate limiting sur routes sensibles**
   ```python
   # ✅ BON
   from core.middleware import limiter
   
   @router.post("/login")
   @limiter.limit("5/minute")
   def login(request: Request, ...):
       ...
   
   # ❌ MAUVAIS
   @router.post("/login")
   def login(...):
       # Pas de rate limiting = brute force possible
   ```

4. **Authentification sur routes protégées**
   ```python
   # ✅ BON
   from core.security import get_current_user
   
   @router.get("/documents")
   def list_documents(current_user: User = Depends(get_current_user)):
       return documents
   
   # ❌ MAUVAIS
   @router.get("/documents")
   def list_documents():
       # Pas d'auth = accès public !
       return documents
   ```

5. **Logger les événements de sécurité**
   ```python
   # ✅ BON
   from core.security import log_security_event
   
   if not user:
       log_security_event("LOGIN_FAILED", {"username": username}, request)
       raise HTTPException(401)
   
   # ❌ MAUVAIS
   if not user:
       raise HTTPException(401)  # Pas de log !
   ```

### Checklist Sécurité pour PR

Avant de soumettre une PR, vérifiez :

- [ ] Aucun secret committé (`.env`, clés API, mots de passe)
- [ ] Toutes les entrées utilisateur sont validées
- [ ] Routes sensibles protégées par authentification
- [ ] Rate limiting sur routes publiques
- [ ] Logs de sécurité pour événements critiques
- [ ] Tests de sécurité ajoutés/mis à jour
- [ ] `check_security.py` passe tous les checks
- [ ] Documentation de sécurité mise à jour si nécessaire

---

## 🧪 Tests

### Exécuter les tests

```bash
cd backend
pytest -v
```

### Ajouter des tests

Créez des tests pour :
- Nouvelles fonctionnalités
- Corrections de bugs
- Cas limites

```python
# test_ma_fonctionnalite.py
def test_login_success():
    """Test login avec credentials valides."""
    response = client.post("/login", json={
        "username": "admin",
        "password": "test123"
    })
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_login_invalid():
    """Test login avec mauvais credentials."""
    response = client.post("/login", json={
        "username": "admin",
        "password": "wrong"
    })
    assert response.status_code == 401
```

### Couverture de code

```bash
pytest --cov=backend --cov-report=html
```

Visez une couverture > 80% pour les nouvelles fonctionnalités.

---

## 📚 Documentation

### Code

- Docstrings pour fonctions publiques
- Commentaires pour logique complexe
- Type hints Python

```python
def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """
    Authentifie un utilisateur.
    
    Args:
        db: Session de base de données
        username: Nom d'utilisateur
        password: Mot de passe en clair
    
    Returns:
        User si authentification réussie, None sinon
    """
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user
```

### Fichiers de documentation

Mettez à jour si applicable :
- `README.md` : Fonctionnalités principales
- `SECURITY.md` : Aspects de sécurité
- `MIGRATION.md` : Changements breaking
- `CHANGELOG.md` : Historique des versions
- `DEPLOYMENT.md` : Guide de déploiement

---

## 🚀 Workflow de PR

1. **Créer la PR** sur GitHub
2. **Attendre review** (1-2 contributeurs)
3. **Adresser les commentaires** si nécessaire
4. **CI/CD passe** (tests, linting, sécurité)
5. **Merge** par un mainteneur

### Template de PR

```markdown
## Description
Brève description des changements

## Type de changement
- [ ] Nouvelle fonctionnalité (feat)
- [ ] Correction de bug (fix)
- [ ] Documentation (docs)
- [ ] Breaking change (nécessite MIGRATION.md)

## Tests
- [ ] Tests ajoutés/mis à jour
- [ ] Tous les tests passent
- [ ] check_security.py validé

## Sécurité
- [ ] Aucun secret committé
- [ ] Entrées validées
- [ ] Authentification en place
- [ ] Rate limiting si applicable
- [ ] Logs de sécurité

## Documentation
- [ ] README mis à jour
- [ ] Docstrings ajoutées
- [ ] CHANGELOG mis à jour

## Screenshots
(si applicable)
```

---

## 🆘 Besoin d'Aide ?

- **Issues** : Ouvrez une issue sur GitHub
- **Discussions** : Utilisez GitHub Discussions
- **Email** : contact@paperfree-ai.example.com

---

## 🙏 Merci !

Votre contribution rend PaperFree-AI meilleur pour tous. Merci de prendre le temps de suivre ces guidelines !

---

**Happy coding! 🚀**
