#!/bin/bash

echo "Running database migration for SentimentReturns table..."

# Run migration inside the backend Docker container
docker compose exec backend alembic upgrade head

echo "Migration completed!"

echo "Re-enabling SentimentReturns model and returns router..."

# Uncomment the SentimentReturns model
sed -i 's/^# class SentimentReturns/class SentimentReturns/' backend/models.py
sed -i 's/^#     /    /g' backend/models.py

# Uncomment the returns router import
sed -i 's/^    # returns as returns_router/    returns as returns_router/' backend/main.py

# Uncomment the returns router inclusion
sed -i 's/^# app.include_router(/app.include_router(/' backend/main.py
sed -i 's/^#     returns_router.router,/    returns_router.router,/' backend/main.py
sed -i 's/^#     prefix="\/api\/returns",/    prefix="\/api\/returns",/' backend/main.py
sed -i 's/^#     tags=\["returns"\]/    tags=["returns"]/' backend/main.py
sed -i 's/^# )/)/' backend/main.py

echo "Done! Please restart your Docker containers:"
echo "docker compose down"
echo "docker compose up --build"
