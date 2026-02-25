# 🔄 Guide de Migration v0.4.0 → v0.5.0

## ⚠️ Changements importants

La version **0.5.0** introduit des changements de sécurité majeurs, notamment le passage de **HTTP Basic Auth** à **JWT (JSON Web Tokens)**.

---

## 📋 Étapes de migration

### 1. **Sauvegarder vos données**

```bash
# Sauvegarder la base de données
cp storage/paperfree.db storage/paperfree.db.backup

# Sauvegarder les fichiers
tar -czf storage_backup.tar.gz storage/
```

### 2. **Mettre à jour le code**

```bash
git pull origin main
```

### 3. **Mettre à jour les dépendances**

```bash
cd backend
pip install -r requirements.txt --upgrade
```

Ou avec Docker :

```bash
docker-compose down
docker-compose build --no-cache
```

### 4. **⚠️ IMPORTANT : Configurer SECRET_KEY**

**Cette étape est OBLIGATOIRE pour la sécurité !**

Générer une clé secrète aléatoire :

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Ajouter dans `.env` :

```env
SECRET_KEY=VotreCléGénéréeAléatoirement123456789
```

⚠️ **Ne JAMAIS partager cette clé ni la committer dans Git !**

### 5. **Configurer CORS (optionnel mais recommandé)**

Dans `.env`, remplacer :

```env
# Ancien (v0.4.0) - wildcard permissif
# Pas de variable CORS

# Nouveau (v0.5.0) - origines explicites
ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
```

Si vous accédez depuis d'autres domaines/ports, ajoutez-les :

```env
ALLOWED_ORIGINS=http://localhost:8080,https://docs.example.com,https://192.168.1.100:8080
```

### 6. **Redémarrer l'application**

```bash
# Avec Docker
docker-compose up -d

# Sans Docker
cd backend
python main.py
```

### 7. **Vérifier les logs**

Au démarrage, vous devriez voir :

```
✅ Security middlewares enabled:
   - CORS: ['http://localhost:8080', 'http://127.0.0.1:8080']
   - Security Headers: Active
   - Rate Limiting: Active
🚀 PaperFree-AI v0.5.0 démarré
```

Si vous voyez :

```
⚠️  WARNING: SECRET_KEY not set or using default value!
```

**ARRÊTEZ** et configurez `SECRET_KEY` (étape 4).

---

## 🔑 Changements d'authentification

### Ancien système (v0.4.0)

**HTTP Basic Auth** :
- Username/password à chaque requête
- Pas de session
- Compatible navigateur

### Nouveau système (v0.5.0)

**JWT Tokens** :
- Login initial avec username/password
- Récupération d'un `access_token` (60 min) et `refresh_token` (30 jours)
- Token Bearer dans le header `Authorization`

### Exemple de migration du frontend

**Avant (v0.4.0)** :

```javascript
fetch('/api/documents', {
  headers: {
    'Authorization': 'Basic ' + btoa('username:password')
  }
})
```

**Après (v0.5.0)** :

```javascript
// 1. Login
const loginResponse = await fetch('/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'user', password: 'pass' })
});
const { access_token, refresh_token } = await loginResponse.json();

// Stocker les tokens (localStorage ou autre)
localStorage.setItem('access_token', access_token);
localStorage.setItem('refresh_token', refresh_token);

// 2. Requêtes authentifiées
fetch('/documents', {
  headers: {
    'Authorization': 'Bearer ' + localStorage.getItem('access_token')
  }
});

// 3. Renouvellement automatique (quand access_token expire)
const refreshResponse = await fetch('/refresh', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ refresh_token: localStorage.getItem('refresh_token') })
});
const { access_token: newToken } = await refreshResponse.json();
localStorage.setItem('access_token', newToken);
```

---

## 🚨 Problèmes courants

### Erreur : "Could not validate credentials"

**Cause** : Vous utilisez encore HTTP Basic Auth au lieu de JWT.

**Solution** : Faire un POST `/login` pour obtenir un token, puis utiliser `Authorization: Bearer <token>`

### Erreur : "Rate limit exceeded"

**Cause** : Trop de requêtes en peu de temps.

**Solution** : 
- Login : 5 tentatives/minute maximum
- Upload : 20 fichiers/minute maximum
- Attendre 1 minute avant de réessayer

### Erreur : "Extension de fichier non autorisée"

**Cause** : Validation stricte des uploads activée.

**Solution** : Seules ces extensions sont autorisées :
- PDF : `.pdf`
- Images : `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`

### Erreur CORS

**Cause** : Origine non autorisée.

**Solution** : Ajouter votre domaine dans `ALLOWED_ORIGINS` dans `.env`

---

## 🔄 Retour en arrière (rollback)

Si vous rencontrez des problèmes :

```bash
# 1. Arrêter l'application
docker-compose down

# 2. Revenir à la version précédente
git checkout v0.4.0

# 3. Restaurer la base de données
cp storage/paperfree.db.backup storage/paperfree.db

# 4. Redémarrer
docker-compose up -d
```

---

## 📞 Support

Si vous rencontrez des difficultés :

1. Vérifier les logs : `docker-compose logs -f backend`
2. Ouvrir une issue sur GitHub
3. Consulter `SECURITY.md` pour plus de détails

---

**Bonne migration ! 🚀**
