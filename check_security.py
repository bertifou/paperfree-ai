#!/usr/bin/env python3
"""
check_security.py — Script de vérification de la configuration de sécurité

Vérifie que toutes les mesures de sécurité sont correctement configurées
avant le déploiement en production.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Couleurs pour le terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

def print_header(text):
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{text:^60}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")

def print_check(status, message):
    symbol = f"{GREEN}✓{RESET}" if status else f"{RED}✗{RESET}"
    print(f"{symbol} {message}")

def print_warning(message):
    print(f"{YELLOW}⚠{RESET}  {message}")

def check_secret_key():
    """Vérifie que SECRET_KEY est définie et sécurisée."""
    load_dotenv()
    secret_key = os.getenv("SECRET_KEY", "")
    
    if not secret_key:
        print_check(False, "SECRET_KEY n'est pas définie")
        print_warning("Générez une clé avec: python backend/generate_secret_key.py")
        return False
    
    if secret_key == "changeme-please-generate-a-random-string":
        print_check(False, "SECRET_KEY utilise la valeur par défaut (DANGEREUX)")
        print_warning("Générez une clé sécurisée avec: python backend/generate_secret_key.py")
        return False
    
    if len(secret_key) < 32:
        print_check(False, "SECRET_KEY est trop courte (min 32 caractères)")
        return False
    
    print_check(True, f"SECRET_KEY définie et sécurisée ({len(secret_key)} caractères)")
    return True

def check_cors():
    """Vérifie la configuration CORS."""
    load_dotenv()
    allowed_origins = os.getenv("ALLOWED_ORIGINS", "")
    
    if not allowed_origins:
        print_check(False, "ALLOWED_ORIGINS n'est pas définie")
        print_warning("Définissez les origines autorisées dans .env")
        return False
    
    if "*" in allowed_origins:
        print_check(False, "ALLOWED_ORIGINS contient un wildcard (*) - DANGEREUX")
        return False
    
    origins = [o.strip() for o in allowed_origins.split(",")]
    print_check(True, f"CORS configuré avec {len(origins)} origine(s) autorisée(s)")
    for origin in origins:
        print(f"    - {origin}")
    return True

def check_env_file():
    """Vérifie l'existence du fichier .env."""
    env_path = Path(".env")
    
    if not env_path.exists():
        print_check(False, "Fichier .env introuvable")
        print_warning("Copiez .env.example vers .env et configurez-le")
        return False
    
    print_check(True, "Fichier .env trouvé")
    return True

def check_dependencies():
    """Vérifie que les dépendances de sécurité sont installées."""
    try:
        import jose
        print_check(True, "python-jose installé (JWT)")
    except ImportError:
        print_check(False, "python-jose manquant")
        return False
    
    try:
        import slowapi
        print_check(True, "slowapi installé (rate limiting)")
    except ImportError:
        print_check(False, "slowapi manquant")
        return False
    
    try:
        import magic
        print_check(True, "python-magic installé (validation MIME)")
    except ImportError:
        print_check(False, "python-magic manquant")
        return False
    
    return True

def check_database():
    """Vérifie l'existence de la base de données."""
    load_dotenv()
    db_dir = os.getenv("DB_DIR", "./storage")
    db_path = Path(db_dir) / "paperfree.db"
    
    if not db_path.exists():
        print_warning("Base de données non trouvée (normale au premier démarrage)")
        return True
    
    # Vérifier les permissions
    if os.name != 'nt':  # Unix-like
        stat = db_path.stat()
        mode = oct(stat.st_mode)[-3:]
        if mode != "600":
            print_check(False, f"Permissions DB incorrectes ({mode}), recommandé: 600")
            print_warning("chmod 600 storage/paperfree.db")
            return False
    
    print_check(True, "Base de données trouvée")
    return True

def check_upload_limits():
    """Vérifie les limites d'upload."""
    load_dotenv()
    max_size = os.getenv("MAX_UPLOAD_SIZE_MB", "50")
    
    try:
        size_mb = int(max_size)
        if size_mb > 100:
            print_warning(f"Limite d'upload très élevée ({size_mb} MB)")
        print_check(True, f"Limite d'upload: {size_mb} MB")
        return True
    except ValueError:
        print_check(False, "MAX_UPLOAD_SIZE_MB invalide")
        return False

def check_gitignore():
    """Vérifie que .env est bien dans .gitignore."""
    gitignore_path = Path(".gitignore")
    
    if not gitignore_path.exists():
        print_check(False, ".gitignore manquant")
        return False
    
    content = gitignore_path.read_text()
    if ".env" not in content:
        print_check(False, ".env n'est pas dans .gitignore - DANGEREUX")
        return False
    
    print_check(True, ".env est ignoré par Git")
    return True

def main():
    """Exécute tous les checks."""
    print_header("🔒 Vérification de Sécurité PaperFree-AI")
    
    checks = [
        ("Fichier .env", check_env_file),
        ("SECRET_KEY", check_secret_key),
        ("Configuration CORS", check_cors),
        ("Dépendances de sécurité", check_dependencies),
        ("Base de données", check_database),
        ("Limites d'upload", check_upload_limits),
        (".gitignore", check_gitignore),
    ]
    
    results = []
    for name, check_func in checks:
        print(f"\n{BLUE}[{name}]{RESET}")
        try:
            result = check_func()
            results.append(result)
        except Exception as e:
            print_check(False, f"Erreur: {e}")
            results.append(False)
    
    # Résumé
    print_header("Résumé")
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"{GREEN}✓ Tous les checks sont passés ({passed}/{total}){RESET}")
        print(f"\n{GREEN}🎉 Votre configuration est sécurisée !{RESET}")
        return 0
    else:
        print(f"{RED}✗ {total - passed} check(s) ont échoué{RESET}")
        print(f"\n{YELLOW}⚠  Corrigez les problèmes avant le déploiement{RESET}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
