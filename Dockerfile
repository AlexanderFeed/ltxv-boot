FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

WORKDIR /workspace

# системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ffmpeg redis-server && \
    rm -rf /var/lib/apt/lists/*

COPY auto_vid /workspace/auto_vid
COPY startup.sh /workspace/start.sh
COPY requirements.txt /workspace/requirements.txt

RUN chmod +x /workspace/start.sh
RUN pip install --no-cache-dir -r /workspace/requirements.txt

CMD ["bash", "/workspace/start.sh"]
