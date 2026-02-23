# PaperFree-AI 📄🚀

Une solution open-source pour la gestion intelligente de documents, inspirée par Immich.
Tout tourne en local : OCR, LLM, stockage.

## 🌟 Vision
- **Confidentialité Totale** : Aucune donnée n'quitte votre réseau.
- **Capture Mobile** : Scan depuis le navigateur ou l'app compagnon.
- **IA Flexible** : Compatible LM Studio, Ollama, OpenAI ou tout backend OpenAI-compatible.
- **Accès Universel** : Réseau local + accès distant sécurisé.

## 🏗️ Stack
- **Backend** : FastAPI (Python 3.11)
- **OCR** : Tesseract (local)
- **LLM** : OpenAI-compatible (LM Studio / Ollama / OpenAI)
- **DB** : SQLite
- **Frontend** : HTML/JS vanilla (Tailwind CSS)
- **Déploiement** : Docker Compose

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

Modifier `LLM_BASE_URL` dans `.env` :

| Backend    | URL                              |
|------------|----------------------------------|
| LM Studio  | `http://localhost:1234/v1`       |
| Ollama     | `http://localhost:11434/v1`      |
| OpenAI     | `https://api.openai.com/v1`      |

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
- [x] OCR local (Tesseract, francais + anglais)
- [x] Classification automatique par LLM (Facture, Impôts, Santé…)
- [x] Extraction structurée (date, montant, émetteur)
- [x] Recherche plein texte
- [x] Suppression de documents
- [x] Surveillance de dossier (watchdog)
- [x] Configuration LLM modifiable à chaud
- [x] CORS configuré
- [ ] Surveillance boîte mail (email_monitor.py — branché prochainement)
- [ ] Application mobile compagnon
- [ ] Authentification JWT
- [ ] Pagination
