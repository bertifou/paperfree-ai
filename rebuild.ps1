# rebuild.ps1 — Force un rebuild complet sans cache
Write-Host "🛑 Arrêt des containers..." -ForegroundColor Yellow
docker-compose down

Write-Host "🔨 Rebuild sans cache..." -ForegroundColor Cyan
docker-compose build --no-cache

Write-Host "🚀 Démarrage..." -ForegroundColor Green
docker-compose up -d

Write-Host "✅ Fait ! Backend : http://localhost:8000 | Frontend : http://localhost:8080" -ForegroundColor Green
