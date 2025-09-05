FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

WORKDIR /workspace

# системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ffmpeg redis-server && \
    rm -rf /var/lib/apt/lists/*

# копируем код
COPY autovid /workspace/auto_vid/
COPY flux_service /workspace/flux_service/
COPY startup.sh /workspace/startup.sh
COPY handler.py /workspace/handler.py
COPY requirements.txt /workspace/requirements.txt

# права на скрипт
RUN chmod +x /workspace/startup.sh

# python-зависимости
RUN pip install --no-cache-dir -r /workspace/requirements.txt
RUN pip install runpod requests

# точка входа — handler для serverless
CMD ["python3", "/workspace/handler.py"]
