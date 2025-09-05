#!/bin/bash
set -e

echo "📦 Устанавливаю зависимости Python..."
pip install -r /workspace/auto_vid/requirements.txt

echo "🚀 Запускаю Redis..."
redis-server &

echo "🚀 Запускаю FastAPI API сервер..."
python3 /workspace/auto_vid/autovid/backend/api_server.py &

echo "🚀 Запускаю Celery воркеров..."
python3 -m celery -A autovid.backend.flows.main_flow.app worker --loglevel=info --concurrency=4 -Q high_priority,medium_priority,low_priority --hostname autovid_main@%h &
# (добавь остальные воркеры по списку, как в твоём start.sh)

echo "🚀 Запускаю flux_service..."
uvicorn flux_service.app.main:app --host 0.0.0.0 --port 8000 --workers=1 &

wait
