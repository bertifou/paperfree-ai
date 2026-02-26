# Changelog

Tous les changements notables de PaperFree-AI seront documentés dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/),
et ce projet adhère au [Semantic Versioning](https://semver.org/lang/fr/).

---

## [Unreleased] - 2026-02-26

### 🆕 Règles de classification personnalisées

- Nouvelle table `ClassificationRule` en base de données
- Les règles s'appliquent **après** l'analyse LLM et peuvent overrider la catégorie
- Champs supportés : Émetteur (`issuer`), Contenu (`content`), Catégorie LLM (`category`)
- Priorité configurable (la règle de priorité la plus haute l'emporte)
- Activation / désactivation individuelle par règle
- Exemple préinstallé : "Pharmacie → Impôts" (émetteur contient "pharmacie")
- Nouveaux endpoints REST : `GET/POST /rules`, `PUT/DELETE /rules/{id}`
- Interface de gestion dans l'onglet Paramètres → section "Règles de classification"
- Nouveau fichier : `frontend/js/rules.js`

---

## [0.5.0] - 2025-02-25

### 🔒 Ajouté - Sécurité

- **Authentification JWT** : Remplacement complet de HTTP Basic Auth par JWT
  - Access tokens (60 minutes d'expiration)
  - Refresh tokens (30 jours d'expiration)
  - Routes `/login` et `/refresh` pour la gestion des tokens
  - Compatible avec les futures applications mobiles

- **Rate Limiting** : Protection contre les abus
  - `/setup` : 3 tentatives/minute
  - `/login` : 5 tentatives/minute
  - `/upload` : 20 fichiers/minute
  - API générale : 100 requêtes/minute

- **Validation stricte des uploads** :
  - Vérification des extensions autorisées (`.pdf`, `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`)
  - Validation du type MIME réel (magic bytes)
  - Limitation de taille configurable (50 MB par défaut)
  - Sanitization des noms de fichiers (anti path-traversal)

- **Headers de sécurité HTTP** :
  - `Strict-Transport-Security` (HSTS)
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection`
  - `Content-Security-Policy` (CSP)
  - `Referrer-Policy`
  - `Permissions-Policy`

- **CORS restreint** :
  - Configuration des origines autorisées via `.env`
  - Fin du wildcard `allow_origins=["*"]`

- **Logging de sécurité** :
  - Traçage des tentatives de connexion échouées
  - Logs des uploads, modifications et suppressions de documents
  - Fonction centralisée `log_security_event()`
  - Inclusion de l'IP source dans les logs

- **Gestion sécurisée des secrets** :
  - Variable `SECRET_KEY` obligatoire
  - Avertissement au démarrage si clé par défaut détectée
  - Script `generate_secret_key.py` pour générer des clés sécurisées

### 📝 Modifié

- **api/auth.py** : Refonte complète avec JWT et Pydantic models
- **api/documents.py** : Ajout validation uploads et rate limiting
- **core/security.py** : Migration de HTTP Basic vers JWT
- **core/config.py** : Ajout constantes de sécurité
- **main.py** : Activation middlewares de sécurité
- **requirements.txt** : Ajout `python-jose`, `slowapi`, `python-magic-bin`

### 🆕 Nouveaux fichiers

- `backend/core/middleware.py` : Middlewares de sécurité HTTP et rate limiting
- `backend/core/validators.py` : Validation des uploads
- `backend/generate_secret_key.py` : Utilitaire de génération de clés
- `backend/test_security.py` : Suite de tests de sécurité
- `SECURITY.md` : Guide complet de sécurité
- `MIGRATION.md` : Guide de migration v0.4.0 → v0.5.0
- `CHANGELOG.md` : Ce fichier

### ⚠️ Breaking Changes

- **Authentification** : Les clients doivent migrer de HTTP Basic Auth vers JWT
  - Nouvelle route `/login` pour obtenir un token
  - Header `Authorization: Bearer <token>` au lieu de `Authorization: Basic <base64>`
  - Voir `MIGRATION.md` pour les détails

- **CORS** : Les origines doivent être explicitement autorisées dans `.env`
  - Variable `ALLOWED_ORIGINS` requise
  - Exemple : `ALLOWED_ORIGINS=http://localhost:8080,https://app.example.com`

- **SECRET_KEY** : Variable obligatoire dans `.env`
  - Génération recommandée : `python backend/generate_secret_key.py`
  - Application refuse de démarrer avec la valeur par défaut en production

### 📚 Documentation

- Ajout de `SECURITY.md` avec guide complet de sécurité
- Ajout de `MIGRATION.md` avec instructions de mise à jour
- Mise à jour de `README.md` avec nouvelles fonctionnalités
- Mise à jour de `.env.example` avec nouvelles variables

### 🐛 Corrigé

- Vulnérabilité : Uploads sans validation de type MIME
- Vulnérabilité : Absence de rate limiting sur routes sensibles
- Vulnérabilité : CORS trop permissif
- Vulnérabilité : Absence de headers de sécurité HTTP

---

## [0.6.0] - 2026-02-25

### 🆕 Nouveau pipeline vision — double voie parallèle

- **Vision DÉSACTIVÉE** : correction LLM OCR désormais entièrement indépendante de la config vision
  - Activable/désactivable séparément
  - Seuil de confiance propre
  - N'utilise plus `vision_enabled` comme condition
- **Vision ACTIVÉE** : deux voies traitées en parallèle (`ThreadPoolExecutor`)
  - **Voie a)** Image base64 → LLM multimodal → JSON structuré
  - **Voie b)** Tesseract OCR → Score confiance → Fusion/correction avec contexte JSON vision → LLM → JSON structuré
  - **Merge** intelligent des deux JSON (voie b prioritaire sur les champs structurés)
- Nouveau paramètre `ocr_vision_fusion` : active/désactive la fusion vision dans la voie b)
- Nouvelle fonction `correct_ocr_with_vision_fusion()` remplace `correct_ocr_with_vision()`
- Nouvelle fonction `_merge_analyses()` pour combiner les deux JSON
- README mis à jour avec le schéma du nouveau pipeline

---

## [0.4.0] - 2025-01-XX

### Ajouté

- Support vision multimodale (LLM vision)
- Configuration providers (local, OpenAI, Anthropic)
- Correction OCR par LLM
- Score de confiance Tesseract

### Modifié

- Amélioration pipeline OCR
- Optimisation traitement documents

---

## [0.3.0] - 2024-12-XX

### Ajouté

- Surveillance email (OAuth2 Microsoft/Google)
- Détection pièces jointes
- Suppression automatique emails promotionnels

---

## [0.2.0] - 2024-11-XX

### Ajouté

- Recherche plein texte
- Surveillance de dossier (watchdog)
- Configuration LLM à chaud

---

## [0.1.0] - 2024-10-XX

### Ajouté

- Upload de documents
- OCR local (Tesseract)
- Analyse LLM
- Classification automatique
- Interface web basique

---

## Légende

- 🔒 Sécurité
- 🆕 Nouvelle fonctionnalité
- 📝 Modification
- 🐛 Correction de bug
- ⚠️ Breaking change
- 📚 Documentation
