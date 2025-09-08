# Базовый образ RunPod с CUDA 12.2
FROM runpod/base:0.6.2-cuda12.2.0

# Установим Python3, pip и утилиты
RUN apt-get update && apt-get install -y \
    python3 python3-pip git ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/python3 /usr/bin/python

# Обновим pip
RUN pip install --upgrade pip

# Установим зависимости
RUN pip install \
    runpod \
    torch==2.3.1+cu121 torchvision==0.18.1+cu121 --extra-index-url https://download.pytorch.org/whl/cu121 \
    transformers accelerate \
    diffusers[torch] \
    imageio[ffmpeg] \
    huggingface_hub hf-transfer

COPY requirements.txt .
RUN pip install -r requirements.txt

# Рабочая папка
WORKDIR /src

# Скопируем handler
COPY handler.py /src/handler.py

# По умолчанию запускаем handler
CMD ["python", "handler.py"]
