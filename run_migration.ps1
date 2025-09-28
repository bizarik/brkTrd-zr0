# PowerShell script to run database migration and re-enable SentimentReturns

Write-Host "Running database migration for SentimentReturns table..."

# Run migration inside the backend Docker container
docker compose exec backend alembic upgrade head

Write-Host "Migration completed!"

Write-Host "Re-enabling SentimentReturns model and returns router..."

# Uncomment the SentimentReturns model
(Get-Content backend/models.py) -replace '^# class SentimentReturns', 'class SentimentReturns' | Set-Content backend/models.py
(Get-Content backend/models.py) -replace '^#     ', '    ' | Set-Content backend/models.py

# Uncomment the returns router import
(Get-Content backend/main.py) -replace '^    # returns as returns_router', '    returns as returns_router' | Set-Content backend/main.py

# Uncomment the returns router inclusion
(Get-Content backend/main.py) -replace '^# app.include_router\(', 'app.include_router(' | Set-Content backend/main.py
(Get-Content backend/main.py) -replace '^#     returns_router.router,', '    returns_router.router,' | Set-Content backend/main.py
(Get-Content backend/main.py) -replace '^#     prefix="/api/returns",', '    prefix="/api/returns",' | Set-Content backend/main.py
(Get-Content backend/main.py) -replace '^#     tags=\["returns"\]', '    tags=["returns"]' | Set-Content backend/main.py
(Get-Content backend/main.py) -replace '^# \)', ')' | Set-Content backend/main.py

Write-Host "Done! Please restart your Docker containers:"
Write-Host "docker compose down"
Write-Host "docker compose up --build"
