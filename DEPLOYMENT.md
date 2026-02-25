# 🚀 Guide de Déploiement Sécurisé

Ce guide vous accompagne pour déployer PaperFree-AI en production de manière sécurisée.

---

## 📋 Pré-requis

- [ ] Docker et Docker Compose installés
- [ ] Nom de domaine configuré (recommandé)
- [ ] Certificat SSL/TLS (Let's Encrypt recommandé)
- [ ] Serveur Linux avec au moins 2 GB RAM

---

## 🔐 Étape 1 : Configuration Sécurisée

### 1.1 Générer une SECRET_KEY

```bash
cd paperfree-ai
python3 backend/generate_secret_key.py
```

Copiez la clé générée dans votre fichier `.env`.

### 1.2 Configurer les variables d'environnement

Créez votre fichier `.env` depuis l'exemple :

```bash
cp .env.example .env
nano .env
```

**Variables OBLIGATOIRES à configurer :**

```env
# CRITIQUE : Ne jamais utiliser la valeur par défaut !
SECRET_KEY=VotreCléGénéréeAléatoirement

# CORS : Définir vos domaines exacts
ALLOWED_ORIGINS=https://votre-domaine.com,https://app.votre-domaine.com

# LLM (adapter selon votre configuration)
LLM_BASE_URL=http://localhost:1234/v1
LLM_API_KEY=votre-clé-api
LLM_MODEL=votre-modele

# Limites (optionnel)
MAX_UPLOAD_SIZE_MB=50
```

### 1.3 Vérifier la configuration

```bash
python3 check_security.py
```

Tous les checks doivent être ✓ verts avant de continuer.

---

## 🌐 Étape 2 : Reverse Proxy (Nginx/Caddy)

### Option A : Nginx avec Let's Encrypt

1. **Installer Certbot** :

```bash
sudo apt install certbot python3-certbot-nginx
```

2. **Obtenir un certificat SSL** :

```bash
sudo certbot --nginx -d votre-domaine.com
```

3. **Configuration Nginx** (`/etc/nginx/sites-available/paperfree`) :

```nginx
# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name votre-domaine.com;
    return 301 https://$server_name$request_uri;
}

# HTTPS server
server {
    listen 443 ssl http2;
    server_name votre-domaine.com;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/votre-domaine.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/votre-domaine.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Client body size (pour uploads)
    client_max_body_size 50M;

    # Frontend
    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Backend API
    location /api {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts pour uploads longs
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

4. **Activer et recharger** :

```bash
sudo ln -s /etc/nginx/sites-available/paperfree /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Option B : Caddy (plus simple)

1. **Installer Caddy** :

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

2. **Configuration Caddy** (`/etc/caddy/Caddyfile`) :

```caddy
votre-domaine.com {
    # HTTPS automatique via Let's Encrypt
    
    # Frontend
    reverse_proxy localhost:8080
    
    # Backend API
    handle /api/* {
        reverse_proxy localhost:8000
    }
    
    # Security Headers
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Frame-Options "DENY"
        X-Content-Type-Options "nosniff"
        X-XSS-Protection "1; mode=block"
    }
    
    # Max upload size
    request_body {
        max_size 50MB
    }
}
```

3. **Recharger Caddy** :

```bash
sudo systemctl reload caddy
```

---

## 🐳 Étape 3 : Démarrage avec Docker

```bash
# Build et démarrage
docker-compose up -d --build

# Vérifier les logs
docker-compose logs -f backend

# Vous devriez voir :
# ✅ Security middlewares enabled:
#    - CORS: ['https://votre-domaine.com']
#    - Security Headers: Active
#    - Rate Limiting: Active
# 🚀 PaperFree-AI v0.5.0 démarré
```

---

## 🔥 Étape 4 : Firewall

### UFW (Ubuntu/Debian)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### Firewalld (CentOS/RHEL)

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

---

## 📊 Étape 5 : Monitoring et Logs

### Configurer la rotation des logs

Créez `/etc/logrotate.d/paperfree` :

```
/var/log/paperfree/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 www-data www-data
    sharedscripts
    postrotate
        docker-compose -f /chemin/vers/paperfree-ai/docker-compose.yml restart backend
    endscript
}
```

### Surveiller les logs de sécurité

```bash
# Tentatives de login échouées
docker-compose logs backend | grep "LOGIN_FAILED"

# Uploads rejetés
docker-compose logs backend | grep "Rejected upload"

# Événements de sécurité
docker-compose logs backend | grep "SECURITY"
```

---

## 🔄 Étape 6 : Sauvegardes Automatiques

### Script de backup quotidien

Créez `/usr/local/bin/backup-paperfree.sh` :

```bash
#!/bin/bash
BACKUP_DIR="/backups/paperfree"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Backup de la base de données
cp /chemin/vers/paperfree-ai/storage/paperfree.db "$BACKUP_DIR/paperfree_$DATE.db"

# Backup des fichiers uploadés (optionnel si volumineux)
tar -czf "$BACKUP_DIR/uploads_$DATE.tar.gz" /chemin/vers/paperfree-ai/storage/uploads/

# Supprimer les backups de plus de 30 jours
find "$BACKUP_DIR" -type f -mtime +30 -delete

echo "Backup terminé: $DATE"
```

### Cron job quotidien

```bash
sudo crontab -e
# Ajouter :
0 3 * * * /usr/local/bin/backup-paperfree.sh
```

---

## 🔧 Étape 7 : Mises à Jour

### Procédure de mise à jour

```bash
# 1. Sauvegarder
./backup-paperfree.sh

# 2. Récupérer les mises à jour
git pull origin main

# 3. Reconstruire
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# 4. Vérifier
docker-compose logs -f backend
```

---

## ✅ Checklist Finale de Sécurité

Avant de mettre en production, vérifiez :

- [ ] `SECRET_KEY` générée aléatoirement et unique
- [ ] `ALLOWED_ORIGINS` configuré avec vos domaines exacts
- [ ] HTTPS activé avec certificat SSL valide
- [ ] Firewall configuré (ports 80/443 uniquement)
- [ ] Reverse proxy (Nginx/Caddy) configuré
- [ ] Logs de sécurité activés et surveillés
- [ ] Sauvegardes automatiques configurées
- [ ] Script `check_security.py` passe tous les checks
- [ ] Rate limiting activé et testé
- [ ] Headers de sécurité HTTP présents
- [ ] Base de données sauvegardée régulièrement
- [ ] Plan de restauration testé

---

## 🚨 En Cas de Problème

### Logs détaillés

```bash
docker-compose logs --tail=100 -f backend
```

### Redémarrage

```bash
docker-compose restart backend
```

### Restauration depuis backup

```bash
docker-compose down
cp /backups/paperfree/paperfree_YYYYMMDD.db storage/paperfree.db
docker-compose up -d
```

---

## 📞 Support

- Documentation : `README.md`, `SECURITY.md`, `MIGRATION.md`
- Issues GitHub : [lien vers votre repo]
- Communauté : [Discord/Forum]

---

**Déploiement sécurisé terminé ! 🎉**
