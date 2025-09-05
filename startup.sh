#!/bin/bash
set -euo pipefail

# Путь к каталогу, где лежит сам startup.sh (фикс до любых cd)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Корректное завершение по сигналам
trap 'echo "🛑 Получен сигнал остановки, завершаем..."; exit 0' SIGTERM SIGINT

echo "🔧 Активируем окружение..."
cd /workspace

export DEBIAN_FRONTEND=noninteractive
export HF_HOME=/workspace/.cache/huggingface
export HUGGINGFACE_HUB_CACHE=/workspace/.cache/huggingface
export TRANSFORMERS_CACHE=/workspace/.cache/huggingface
export DIFFUSERS_CACHE=/workspace/.cache/huggingface
mkdir -p "$HF_HOME"

# Базовые пакеты (git/rsync/venv)
apt-get update -y
apt-get install -y --no-install-recommends git rsync python3-venv

# ── 1) Чистый LTX-Video ─────────────────────────────────────────────────────
LTX_DIR="/workspace/LTX-Video"
LTX_REPO_URL="${LTX_REPO_URL:-https://github.com/Lightricks/LTX-Video.git}"
LTX_BRANCH="${LTX_BRANCH:-main}"

if [ -d "$LTX_DIR" ]; then
  echo "[LTX] Удаляю старый LTX-Video и клонирую заново"
  rm -rf "$LTX_DIR"
fi

echo "[LTX] Клонируем LTX-Video из $LTX_REPO_URL (branch=$LTX_BRANCH)"
git clone --depth 1 --branch "$LTX_BRANCH" "$LTX_REPO_URL" "$LTX_DIR"
echo "[LTX] Готово: $LTX_DIR"

# ── 2) Накладываем overlay ───────────────────────────────────────────────────
MY_OVERLAY="$SCRIPT_DIR/overlay"
echo "[Overlay] SCRIPT_DIR=$SCRIPT_DIR"
echo "[Overlay] Ожидаю появление папки: $MY_OVERLAY"

for i in $(seq 1 30); do
  if [ -d "$MY_OVERLAY" ]; then
    echo "[Overlay] Найдена overlay (через $((i*2))с)"
    break
  fi
  echo "[Overlay] overlay ещё нет, пробую снова... ($i/30)"
  sleep 2
done

if [ -d "$MY_OVERLAY" ]; then
  echo "[Overlay] Копирую файлы из $MY_OVERLAY -> $LTX_DIR"
  rsync -a --exclude '.git' "$MY_OVERLAY"/ "$LTX_DIR"/
else
  echo "[Overlay] ВНИМАНИЕ: overlay так и не появилась, пропускаю копирование"
fi

# ── 3) venv + зависимости проекта ────────────────────────────────────────────
VENV_DIR="$LTX_DIR/env"

# Создадим venv, если нет
if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "🌱 Создаём виртуальное окружение..."
  python3 -m venv "$VENV_DIR"
fi

# Активируем venv (для удобного использования "pip")
# и одновременно будем всегда использовать абсолютные пути к бинарям
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

# Проверим, что это Python-проект
cd "$LTX_DIR"
if [ ! -f "pyproject.toml" ] && [ ! -f "setup.py" ]; then
  echo "❌ Нет pyproject.toml/setup.py в $LTX_DIR"
  echo "PWD=$(pwd)"; ls -la
  exit 1
fi

if ! "$VENV_DIR/bin/pip" show ltx-video > /dev/null 2>&1; then
  echo "📦 Устанавливаем зависимости LTX-Video (PWD=$(pwd))..."
  "$VENV_DIR/bin/python" -m pip install --upgrade pip
  "$VENV_DIR/bin/python" -m pip install -e '.[inference-script]'
else
  echo "✅ LTX-Video уже установлен, пропускаем установку"
fi

# ── 4) Системные зависимости ─────────────────────────────────────────────────
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "📦 Устанавливаем ffmpeg..."
  apt-get update -y
  apt-get install -y --no-install-recommends ffmpeg
else
  echo "✅ ffmpeg уже установлен, пропускаем"
fi

# ── 5) Python-библиотеки для видео ───────────────────────────────────────────
if ! "$VENV_DIR/bin/pip" show av > /dev/null 2>&1; then
  "$VENV_DIR/bin/pip" install -U av
else
  echo "✅ av уже установлен"
fi
if ! "$VENV_DIR/bin/pip" show imageio > /dev/null 2>&1; then
  "$VENV_DIR/bin/pip" install -U imageio
else
  echo "✅ imageio уже установлен"
fi
if ! "$VENV_DIR/bin/pip" show imageio-ffmpeg > /dev/null 2>&1; then
  "$VENV_DIR/bin/pip" install -U imageio-ffmpeg
else
  echo "✅ imageio-ffmpeg уже установлен"
fi

# ── 6) diffusers + huggingface_hub ───────────────────────────────────────────
if ! ( "$VENV_DIR/bin/pip" show diffusers >/dev/null 2>&1 && "$VENV_DIR/bin/pip" show huggingface_hub >/dev/null 2>&1 ); then
  echo "📦 Устанавливаем diffusers и huggingface_hub..."
  "$VENV_DIR/bin/pip" install -U git+https://github.com/huggingface/diffusers
  "$VENV_DIR/bin/pip" install -U huggingface_hub
else
  echo "✅ diffusers и huggingface_hub уже установлены"
fi

# ── 7) Логин в Hugging Face (мягкий) ─────────────────────────────────────────
echo "🔐 Проверяю токен Hugging Face..."
if [ -n "${HF_TOKEN:-}" ]; then
  echo "🔐 HF: логинюсь по HF_TOKEN..."
  "$VENV_DIR/bin/huggingface-cli" login --token "$HF_TOKEN" || echo "⚠️ HF: токен невалиден, продолжаю без логина"
else
  echo "ℹ️ HF: токен не задан, пропускаю логин"
fi

# ── 8) Зависимости для API/Celery/Redis (pip) ────────────────────────────────
if ! ( "$VENV_DIR/bin/pip" show fastapi >/dev/null 2>&1 && "$VENV_DIR/bin/pip" show celery >/dev/null 2>&1 && "$VENV_DIR/bin/pip" show redis >/dev/null 2>&1 ); then
  echo "📦 Устанавливаем зависимости для API, Celery и Redis..."
  "$VENV_DIR/bin/pip" install "fastapi[all]" celery redis
else
  echo "✅ FastAPI, Celery и Redis (pip) уже установлены"
fi

# Redis-сервер (системный)
apt-get update -y
apt-get install -y --no-install-recommends redis-server

# ── 9) Весы модели ──────────────────────────────────────────────────────────
cd "$LTX_DIR"
if [ ! -f "models/ltxv-13b-0.9.8-distilled/model.safetensors" ]; then
  echo "🎬 Загружаем весы модели..."
  "$VENV_DIR/bin/python" download_weights.py
else
  echo "✅ Веса модели уже загружены, пропускаем"
fi

# ── 10) Запуск сервисов ──────────────────────────────────────────────────────
echo "🚦 Запускаем Redis..."
redis-server --daemonize yes
sleep 2

# Ожидание готовности демона
wait_for_daemon() {
  local max_wait=300
  local elapsed=0
  local check_interval=10
  echo "⏳ Ожидаем готовности inference демона (максимум ${max_wait}с)..."
  while [ $elapsed -lt $max_wait ]; do
    if [ -f "/workspace/LTX-Video/daemon_ready.flag" ]; then
      echo "✅ Демон готов! Время загрузки: ${elapsed}с"
      return 0
    fi
    if ! pgrep -f "run_inference_daemon_official.py" > /dev/null; then
      echo "❌ Процесс демона завершился! Проверьте логи."
      return 1
    fi
    echo "⌛ Демон загружается... ${elapsed}с (осталось: $((max_wait - elapsed))с)"
    sleep $check_interval
    elapsed=$((elapsed + check_interval))
  done
  echo "❌ Таймаут ожидания демона (${max_wait}с)!"
  echo "📋 Логи: tail -f /workspace/LTX-Video/inference_daemon_official.log"
  return 1
}

# Проверка процесса
check_process() {
  local process_name=$1
  local log_file=$2
  local pid
  pid=$(pgrep -f "$process_name" | head -1 || true)
  if [ -n "${pid:-}" ]; then
    echo "✅ $process_name запущен (PID: $pid)"
    return 0
  else
    echo "❌ $process_name не запущен!"
    echo "📋 Проверьте логи: tail -f $log_file"
    return 1
  fi
}

echo "🚦 Запускаем inference демон (логи в inference_daemon_official.log)..."
cd "$LTX_DIR"
nohup "$VENV_DIR/bin/python" run_inference_daemon_official.py > inference_daemon_official.log 2>&1 &
DAEMON_PID=$!
echo "📋 Демон запущен с PID: $DAEMON_PID"

sleep 5
if ! kill -0 $DAEMON_PID 2>/dev/null; then
  echo "❌ Демон завершился сразу после запуска! Последние строки лога:"
  tail -n 20 inference_daemon_official.log || true
  exit 1
fi
echo "✅ Демон успешно запущен, ждём загрузки моделей..."

if wait_for_daemon; then
  echo "🎉 Демон готов, запускаем остальные сервисы..."
else
  echo "💀 Критическая ошибка: демон не запустился"
  echo "🔍 Последние строки лога:"
  tail -n 10 inference_daemon_official.log || true
  exit 1
fi

echo "🚦 Запускаем Celery воркер (логи в celery_worker.log)..."
cd "$LTX_DIR"
nohup "$VENV_DIR/bin/celery" -A my_celery worker --loglevel=info --concurrency=1 > celery_worker.log 2>&1 &
sleep 3

echo "🚦 Запускаем API сервер (логи в api_server.log)..."
nohup "$VENV_DIR/bin/python" run_api_server.py > api_server.log 2>&1 &
sleep 2

echo "🚦 Запускаем сервер для фронтенда (логи в frontend_server.log)..."
nohup "$VENV_DIR/bin/python" run_frontend_server.py > frontend_server.log 2>&1 &

echo -e "\n\n🔍 Проверяем статус всех сервисов..."
sleep 3

echo "📊 Статус сервисов:"
check_process "run_inference_daemon_official.py" "inference_daemon_official.log"
check_process "celery.*my_celery" "celery_worker.log"
check_process "run_api_server.py" "api_server.log"
check_process "run_frontend_server.py" "frontend_server.log"

# Проверяем готовность демона
if [ -f "/workspace/LTX-Video/daemon_ready.flag" ]; then
  READY_TIME=$(cut -d: -f2 < /workspace/LTX-Video/daemon_ready.flag)
  echo "🏁 Inference демон готов (время: $(date -d @"$READY_TIME" 2>/dev/null || echo "$READY_TIME"))"
else
  echo "⚠️ Файл готовности демона не найден!"
fi

# Финальная проверка портов
echo "🌐 Проверяем порты:"
if ss -tlnp | grep -q ":8000"; then
  echo "✅ API сервер (порт 8000)"
else
  echo "❌ API сервер не отвечает на порту 8000"
fi
if ss -tlnp | grep -q ":8002"; then
  echo "✅ Фронтенд сервер (порт 8002)"
else
  echo "❌ Фронтенд сервер не отвечает на порту 8002"
fi

echo "--------------------------------------------------------"
echo "➡️  Фронтенд: http://<ВАШ_IP>:8002/frontend.html"
echo "➡️  API docs: http://<ВАШ_IP>:8000/docs"
echo "--------------------------------------------------------"
echo "👀 Логи:"
echo "   tail -f /workspace/LTX-Video/inference_daemon_official.log"
echo "   tail -f /workspace/LTX-Video/celery_worker.log"
echo "   tail -f /workspace/LTX-Video/api_server.log"
echo "   tail -f /workspace/LTX-Video/frontend_server.log"
echo "--------------------------------------------------------"
echo "🛡️ Держим процессы живыми..."

# ── Страж: перезапуски при падениях ─────────────────────────────────────────
while true; do
  sleep 30

  if ! pgrep -f "run_inference_daemon_official.py" >/dev/null; then
    echo "⚠️ Inference демон упал! Перезапускаем..."
    cd "$LTX_DIR"
    nohup "$VENV_DIR/bin/python" run_inference_daemon_official.py > inference_daemon_restart.log 2>&1 &
  fi

  if ! pgrep -f "celery.*my_celery" >/dev/null; then
    echo "⚠️ Celery воркер упал! Перезапускаем..."
    cd "$LTX_DIR"
    nohup "$VENV_DIR/bin/celery" -A my_celery worker --loglevel=info --concurrency=1 > celery_worker_restart.log 2>&1 &
  fi

  if ! pgrep -f "run_api_server.py" >/dev/null; then
    echo "⚠️ API сервер упал! Перезапускаем..."
    cd "$LTX_DIR"
    nohup "$VENV_DIR/bin/python" run_api_server.py > api_server_restart.log 2>&1 &
  fi
done