"""
generate_secret_key.py — Génère une clé secrète sécurisée pour JWT
"""
import secrets

def generate_secret_key():
    """Génère une clé secrète cryptographiquement sécurisée."""
    key = secrets.token_urlsafe(32)
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║         🔑 Clé Secrète Générée avec Succès                   ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    print()
    print("Copiez cette clé dans votre fichier .env :")
    print()
    print(f"SECRET_KEY={key}")
    print()
    print("⚠️  IMPORTANT :")
    print("   - Ne partagez JAMAIS cette clé")
    print("   - Ne la committez JAMAIS dans Git")
    print("   - Gardez-la confidentielle")
    print()
    print("✅ Cette clé est cryptographiquement sécurisée et unique.")
    print()

if __name__ == "__main__":
    generate_secret_key()
