# Образ мини-аппа: FastAPI-бэкенд + статика фронтенда в одном контейнере.
# Собирается из КОРНЯ репозитория (нужны общие lot_metrics.py и bidding_schedule.py):
#   docker compose -f miniapp/docker-compose.yml up -d --build
FROM python:3.13-slim

WORKDIR /app
COPY miniapp/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY lot_metrics.py bidding_schedule.py /app/
COPY miniapp/backend/app /app/app
COPY miniapp/frontend /app/frontend

ENV HONESTLOT_DB=/data/honestlot.db \
    HONESTLOT_FRONTEND_DIR=/app/frontend \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
