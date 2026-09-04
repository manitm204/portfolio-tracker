FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# In the container PROJECT_ROOT resolves to /, so seed CSVs and the SQLite DB
# are read from /data — mounted from ./data by docker-compose.
COPY backend/ .

ENV PYTHONUNBUFFERED=1

# Migrations run on container start; the DB lives on the mounted volume.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
