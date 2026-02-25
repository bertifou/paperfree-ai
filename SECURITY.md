# 🔒 Guide de Sécurité PaperFree-AI

## Vue d'ensemble des améliorations (v0.5.0)

PaperFree-AI implémente désormais une architecture de sécurité complète, conforme aux bonnes pratiques pour les applications web modernes et les API mobiles.

---

## 🎯 Améliorations implémentées

### 1. **Authentification JWT** ✅
- ✅ Remplacement de HTTP Basic Auth par JWT (JSON Web Tokens)
- ✅ Access tokens (durée courte : 60 minutes)
- ✅ Refresh tokens (durée longue : 30 jours)
- ✅ Expiration automatique et renouvellement sécurisé

**Avantages pour l'app mobile :**
- Pas besoin de stocker username/password sur l'appareil
- Tokens révocables
- Meilleure sécurité et expérience utilisateur

### 2. **Rate Limiting** ✅
- ✅ Protection contre brute force
- ✅ Limites par endpoint :
  - `/setup` : 3 tentatives/minute
  - `/login` : 5 tentatives/minute
  - `/upload` : 20 fichiers/minute
  - API générale : 100 requêtes/minute

### 3. **CORS Restreint** ✅
- ✅ Configuration des origines autorisées via `.env`
- ✅ Fin du wildcard `allow_origins=["*"]`
- ✅ Headers exposés de manière contrôlée

### 4. **Validation des Entrées** ✅
- ✅ Modèles Pydantic pour toutes les routes critiques
- ✅ Validation stricte des uploads (types MIME, taille, extensions)
- ✅ Sanitization des noms de fichiers
- ✅ Protection contre path traversal

### 5. **Sécurité des Fichiers** ✅
- ✅ Vérification des extensions autorisées
- ✅ Validation du type MIME réel (magic bytes)
- ✅ Limitation de taille (50 MB par défaut, configurable)
- ✅ Liste blanche stricte : `.pdf`, `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`

**Extensions futures :**
- [ ] Scan antivirus optionnel (ClamAV)
- [ ] Analyse de contenu malveillant

### 6. **Variables d'Environnement Sensibles** ✅
- ✅ `SECRET_KEY` obligatoire avec génération aléatoire
- ✅ Avertissement au démarrage si clé par défaut détectée
- ✅ Génération automatique en fallback temporaire

### 7. **Headers de Sécurité HTTP** ✅
- ✅ `Strict-Transport-Security` (HSTS)
- ✅ `X-Content-Type-Options: nosniff`
- ✅ `X-Frame-Options: DENY`
- ✅ `X-XSS-Protection: 1; mode=block`
- ✅ `Content-Security-Policy` (CSP)
- ✅ `Referrer-Policy`
- ✅ `Permissions-Policy`

### 8. **Logging de Sécurité** ✅
- ✅ Traçage des tentatives de connexion échouées
- ✅ Logs d'upload, modification et suppression de documents
- ✅ Événements de sécurité avec IP source
- ✅ Fonction centralisée `log_security_event()`

---

## 🔑 Configuration de la Sécurité

### Générer une clé secrète sécurisée

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copiez la sortie dans votre fichier `.env` :

```env
SECRET_KEY=VotreCléGénéréeAléatoirement123456789
```

### Configurer les origines CORS

Dans `.env`, définissez les origines autorisées :

```env
ALLOWED_ORIGINS=http://localhost:8080,https://app.example.com,https://mobile.example.com
```

### Ajuster les limites d'upload

```env
MAX_UPLOAD_SIZE_MB=100
```

---

## 📱 Intégration Mobile Future

Les améliorations JWT facilitent grandement l'intégration d'une app mobile :

### Flux d'authentification mobile

1. **Login initial**
   ```
   POST /login
   {
     "username": "user",
     "password": "pass"
   }
   
   Response:
   {
     "access_token": "eyJ0eXAi...",
     "refresh_token": "eyJ0eXAi...",
     "expires_in": 3600
   }
   ```

2. **Stockage sécurisé**
   - iOS : Keychain
   - Android : EncryptedSharedPreferences
   - Jamais en clair !

3. **Requêtes authentifiées**
   ```
   Authorization: Bearer eyJ0eXAi...
   ```

4. **Renouvellement automatique**
   ```
   POST /refresh
   {
     "refresh_token": "eyJ0eXAi..."
   }
   ```

---

## 🛡️ Checklist de Déploiement

Avant de mettre en production :

- [ ] `SECRET_KEY` générée aléatoirement
- [ ] `ALLOWED_ORIGINS` configuré avec vos domaines réels
- [ ] HTTPS activé (reverse proxy Nginx/Caddy)
- [ ] Certificat SSL valide
- [ ] Logs de sécurité activés et surveillés
- [ ] Backup régulier de la base de données
- [ ] Firewall configuré (ports 80/443 uniquement)
- [ ] Mise à jour régulière des dépendances

---

## 🔍 Monitoring de Sécurité

### Logs importants à surveiller

```bash
# Tentatives de login échouées
grep "LOGIN_FAILED" logs/app.log

# Uploads rejetés
grep "Rejected upload" logs/app.log

# Événements de sécurité
grep "SECURITY" logs/app.log
```

### Alertes recommandées

- Plus de 10 tentatives de login échouées en 1 minute
- Upload de fichiers avec extensions suspectes
- Pics de requêtes inhabituels (DDoS potentiel)

---

## 🚀 Prochaines Étapes

- [ ] Authentification multi-facteur (2FA)
- [ ] Gestion des sessions actives
- [ ] Révocation manuelle des tokens
- [ ] Audit trail complet
- [ ] Scan antivirus des uploads (ClamAV)
- [ ] WAF (Web Application Firewall)
- [ ] Chiffrement des données sensibles en DB

---

## 📚 Ressources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [JWT Best Practices](https://tools.ietf.org/html/rfc8725)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)

---

**Version:** 0.5.0  
**Dernière mise à jour:** Février 2025
