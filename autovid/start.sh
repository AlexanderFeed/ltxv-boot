#!/bin/bash

set -e

# 🧪 Создание виртуального окружения, если не существует
#if [ ! -d ".venv" ]; then
#  echo "Создаю виртуальное окружение..."
#  python3 -m venv .venv
#fi

# ✅ Активация окружения
#source .venv/bin/activate

# 📦 Установка зависимостей
#echo "Устанавливаю зависимости..."
#pip install --upgrade pip
#pip install -r requirements.txt

# 🚀 Запуск Redis
echo "Запуск Redis..."
redis-server &

# 🚀 Запуск FastAPI
echo "Запуск FastAPI..."
python3 -m backend.api_server &

# ⚙️ Запуск Celery воркеров
echo "Запуск Celery воркеров..."
python3 -m celery -A backend.flows.main_flow.app worker --loglevel=info --concurrency=4 -Q high_priority,medium_priority,low_priority --hostname autovid_main@%h > logs/main.log 2>&1 &
python3 -m celery -A backend.flows.main_flow worker --loglevel=info --concurrency=1 -Q script --hostname autovid_script@%h > logs/script.log 2>&1 &
python3 -m celery -A backend.flows.main_flow worker --loglevel=info --concurrency=1 -Q metadata --hostname autovid_metadata@%h > logs/metadata.log 2>&1 &
python3 -m celery -A backend.flows.main_flow worker --loglevel=info --concurrency=1 -Q chunks --hostname autovid_chunks@%h > logs/chunks.log 2>&1 &
python3 -m celery -A backend.flows.main_flow worker --loglevel=info --concurrency=1 -Q prompts --hostname autovid_prompts@%h > logs/prompts.log 2>&1 &
python3 -m celery -A backend.flows.main_flow worker --loglevel=info --concurrency=1 -Q autovid_voiceover --hostname autovid_voiceover@%h > logs/voiceover.log 2>&1 &
python3 -m celery -A backend.flows.main_flow worker --loglevel=info --concurrency=1 -Q images --hostname autovid_images@%h > logs/images.log 2>&1 &
python3 -m celery -A backend.flows.main_flow worker --loglevel=info --concurrency=1 -Q video --hostname autovid_video@%h > logs/video.log 2>&1 &
python3 -m celery -A backend.flows.main_flow worker --loglevel=info --concurrency=1 -Q send_to_cdn --hostname autovid_send_to_cdn@%h > logs/send_to_cdn.log 2>&1 &

# ⏳ Ожидаем завершения всех фоновых процессов
wait
