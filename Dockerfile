# GPU-база от PyTorch
FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /workspace

# Базовые системные пакеты, которые использует startup.sh
RUN apt-get update && apt-get install -y --no-install-recommends \
    git rsync python3-venv ffmpeg redis-server curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Python-зависимости, нужные только обёртке serverless
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Кладём твой код и оверлей
COPY startup.sh /workspace/startup.sh
COPY overlay /workspace/overlay
COPY handler.py /workspace/handler.py

RUN chmod +x /workspace/startup.sh

# В serverless главным процессом должен быть воркер runpod
CMD ["python", "-u", "/workspace/handler.py"]
