# Базовый образ RunPod с CUDA 12.2
FROM runpod/base:0.6.2-cuda12.2.0

# Установим Python3, pip и утилиты
RUN apt-get update && apt-get install -y \
    python3 python3-pip git ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/python3 /usr/bin/python

# Обновим pip
RUN pip install --upgrade pip

# Скопируем зависимости
COPY requirements.txt /src/requirements.txt

# Установим зависимости (torch и torchvision тянем из PyTorch index)
RUN pip install --no-cache-dir -r /src/requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cu121 \
    && pip show requests
    
RUN pip install runpod requests

# Рабочая папка
WORKDIR /src

# Скопируем handler
COPY handler.py /src/handler.py

# Запуск serverless-воркера
CMD ["python3", "handler.py"]
