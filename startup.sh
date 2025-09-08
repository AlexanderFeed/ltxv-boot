#!/bin/bash
set -e

echo "📂 Готовлю рабочие директории..."
mkdir -p /workspace/auto_vid/assets/{scripts,chunks,prompts,scenes,thumbnail,audio,video,uploads}
mkdir -p /logs

if [ -n "$HF_TOKEN" ]; then
    echo "🔐 Авторизуюсь в HuggingFace..."
    huggingface-cli login --token $HF_TOKEN || true
fi

echo "🚀 Запускаю Redis..."
redis-server &

echo "🚀 Запускаю FastAPI API сервер (порт 3000)..."
python3 /workspace/auto_vid/autovid/backend/api_server.py &

echo "🚀 Запускаю Celery воркеров..."
python3 -m celery -A autovid.backend.flows.main_flow.app worker \
    --loglevel=info --concurrency=4 \
    -Q high_priority,medium_priority,low_priority \
    --hostname autovid_main@%h > /logs/main.log 2>&1 &

python3 -m celery -A autovid.backend.flows.main_flow worker \
    --loglevel=info --concurrency=1 -Q script \
    --hostname autovid_script@%h > /logs/script.log 2>&1 &

python3 -m celery -A autovid.backend.flows.main_flow worker \
    --loglevel=info --concurrency=1 -Q metadata \
    --hostname autovid_metadata@%h > /logs/metadata.log 2>&1 &

python3 -m celery -A autovid.backend.flows.main_flow worker \
    --loglevel=info --concurrency=1 -Q video \
    --hostname autovid_video@%h > /logs/video.log 2>&1 &

# ⚠️ добавь сюда остальные очереди (images, voiceover, thumbnails, prompts и т.д.)

echo "🚀 Запускаю flux_service (порт 8001)..."
uvicorn flux_service.app.main:app --host 0.0.0.0 --port 8001 --workers=1 &

echo "📦 Проверяю модель LTX-Video..."
mkdir -p /workspace/auto_vid/models/ltxv-13b-0.9.8-distilled
if [ ! -f "/workspace/auto_vid/models/ltxv-13b-0.9.8-distilled/pytorch_model.bin" ]; then
  echo "⏳ Загружаю модель..."
  git lfs install
  pip install diffusers  # если нужно
  python3 - << 'EOF'
from diffusers import DiffusionPipeline
DiffusionPipeline.from_pretrained("Lightricks/LTX-Video", 
                                  variant="ltxv-13b-0.9.8-distilled",
                                  cache_dir="/workspace/auto_vid/models/ltxv-13b-0.9.8-distilled")
EOF
else
  echo "✅ Модель уже есть, пропускаем загрузку"
fi


echo "✅ Все сервисы запущены"
wait
