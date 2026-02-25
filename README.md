# PaperFree-AI 📄🚀

Une solution open-source pour la gestion intelligente de documents, inspirée par Immich.
Tout tourne en local : OCR, LLM, stockage.

## 🌟 Vision
- **Confidentialité Totale** : Aucune donnée n'quitte votre réseau.
- **Capture Mobile** : Scan depuis le navigateur ou l'app compagnon.
- **IA Flexible** : Compatible LM Studio, Ollama, OpenAI ou tout backend OpenAI-compatible.
- **Accès Universel** : Réseau local + accès distant sécurisé.
- **🔒 Sécurité Renforcée** : JWT, rate limiting, validation stricte des uploads.

## 🏗️ Stack
- **Backend** : FastAPI (Python 3.11)
- **OCR** : Tesseract (local)
- **LLM** : OpenAI-compatible (LM Studio / Ollama / OpenAI)
- **DB** : SQLite
- **Frontend** : HTML/JS vanilla (Tailwind CSS)
- **Déploiement** : Docker Compose
- **Sécurité** : JWT, rate limiting, validation MIME, headers sécurisés

## 🚀 Démarrage rapide

```bash
# 1. Cloner le repo
git clone https://github.com/bertifou/paperfree-ai.git
cd paperfree-ai

# 2. Configurer l'environnement
cp .env.example .env
# Éditer .env : renseigner LLM_BASE_URL selon votre backend

# 3. Lancer avec Docker
docker-compose up -d

# 4. Ouvrir le frontend
# http://localhost:8080
# (Première visite → écran de configuration du compte admin)
```

## ⚙️ Configuration LLM

Modifier `LLM_BASE_URL` dans `.env`, ou choisir directement depuis l'interface web (onglet Paramètres → boutons de sélection rapide) :

| Backend        | URL                                                                 | Modèles suggérés                                    |
|----------------|---------------------------------------------------------------------|-----------------------------------------------------|
| LM Studio      | `http://localhost:1234/v1`                                          | `local-model`                                       |
| Ollama         | `http://localhost:11434/v1`                                         | `llama3`, `mistral`, `qwen2.5`                      |
| OpenAI         | `https://api.openai.com/v1`                                         | `gpt-4o-mini`, `gpt-4o`                             |
| Google Gemini  | `https://generativelanguage.googleapis.com/v1beta/openai/`         | `gemini-2.5-flash-preview-05-20`, `gemini-2.0-flash`, `gemini-1.5-flash` |

> **Gemini** : Clé API gratuite disponible sur [aistudio.google.com/apikey](https://aistudio.google.com/apikey).  
> L'API Gemini expose un endpoint compatible OpenAI — aucune librairie supplémentaire requise.

La config peut aussi être modifiée à chaud depuis l'interface web (onglet Paramètres).

## 📁 Structure

```
paperfree-ai/
├── backend/
│   ├── main.py          # API FastAPI
│   ├── processor.py     # OCR + analyse LLM
│   ├── database.py      # Modèles SQLAlchemy
│   ├── email_monitor.py # Surveillance boîte mail
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── index.html
├── docker-compose.yml
└── .env.example
```

## 🛠️ Fonctionnalités

- [x] Upload de documents (PDF, images)
- [x] OCR local (Tesseract, français + anglais)
- [x] **Score de confiance OCR** — Tesseract retourne un score par mot (0–100 %)
- [x] **Correction OCR par LLM** — le texte brut est envoyé au LLM pour corriger l/1/I, 0/O, mots coupés…
- [x] **Analyse par vision (LLM multimodal)** — bypass OCR, envoie l'image directement au LLM
- [x] Classification automatique par LLM (Facture, Impôts, Santé…)
- [x] Extraction structurée (date, montant, émetteur)
- [x] Recherche plein texte
- [x] Suppression de documents
- [x] Surveillance de dossier (watchdog)
- [x] Configuration LLM modifiable à chaud
- [x] **Authentification JWT** — tokens sécurisés pour API et mobile
- [x] **Rate limiting** — protection contre brute force et abus
- [x] **Validation stricte des uploads** — vérification MIME, taille, extensions
- [x] **Headers de sécurité HTTP** — HSTS, CSP, XSS protection
- [x] **Logging de sécurité** — traçage des événements critiques
- [ ] Surveillance boîte mail (email_monitor.py — branché prochainement)
- [ ] Application mobile compagnon
- [ ] Authentification multi-facteur (2FA)
- [ ] Pagination

## 🔍 Pipeline OCR & Vision

```
Image uploadée
     │
     ├─── Vision activée ? ──YES──→ Image en base64 → LLM multimodal → JSON structuré
     │                                                                        │
     │                                                                  Texte extrait (stored)
     │
     └─── Vision désactivée ──→ Tesseract OCR
                                     │
                               Score confiance (0–100%)
                                     │
                               Correction LLM si < seuil
                               (ou systématique si activée)
                                     │
                               Texte corrigé → LLM → JSON structuré
```

| Mode | Avantages | Inconvénients |
|------|-----------|---------------|
| OCR seul | Rapide, 100% local | Erreurs sur docs complexes |
| OCR + correction LLM | Meilleure qualité, 100% local | Requête LLM supplémentaire |
| Vision locale (llava…) | Excellent sur manuscrits/tampons, local | Modèle vision requis, plus lent |
| Vision OpenAI/Anthropic | Qualité maximale | Données envoyées dans le cloud |

