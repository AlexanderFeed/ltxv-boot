#!/bin/bash

# Завершаем все Celery воркеры
pkill -f "celery -A backend.flows.main_flow"

# Завершаем FastAPI (uvicorn)
pkill -f "uvicorn backend.api_server:app"

# Завершаем фронтенд-сервер
pkill -f "serve -s frontend/dist"

echo "🛑 Все процессы остановлены."