# Базовый образ RunPod с CUDA 12.2
FROM runpod/base:0.6.2-cuda12.2.0

# Установим Python3, pip и утилиты
RUN apt-get update && apt-get install -y \
    python3 python3-pip git ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Логи без буфера + кэш HF в volume
ENV PYTHONUNBUFFERED=1 \
    HUGGINGFACE_HUB_CACHE=/runpod-volume/hf-cache

# Обновим pip именно для того python3, что будем запускать
RUN python3 -m pip install --upgrade pip

# Скопируем зависимости
COPY requirements.txt /workspace/requirements.txt

# Установим зависимости (+ PyTorch index)
RUN python3 -m pip install --no-cache-dir -r /workspace/requirements.txt \
      --extra-index-url https://download.pytorch.org/whl/cu121 \
 && python3 -m pip install runpod requests

# Рабочая папка
WORKDIR /workspace

# --- Клонируем LTX-Video
RUN git clone --depth 1 https://github.com/Lightricks/LTX-Video.git /workspace/LTX-Video

# --- Копируем overlay поверх
COPY overlay/ /workspace/LTX-Video/

# --- Устанавливаем LTX-Video (editable mode)
WORKDIR /workspace/LTX-Video
RUN python3 -m pip install -e '.[inference-script]'

# Вернёмся в /workspace для handler
WORKDIR /workspace

# Скопируем handler
COPY handler.py /workspace/handler.py

# Запуск serverless-воркера
CMD ["python3", "handler.py"]
