# База RunPod с CUDA 12.2 (совместимо с LTX docs)
FROM runpod/base:0.6.2-cuda12.2.0

# Системные пакеты
RUN apt-get update && apt-get install -y git ffmpeg && rm -rf /var/lib/apt/lists/*

# Ускоренная загрузка весов с HF
ENV HF_HUB_ENABLE_HF_TRANSFER=1 \
    PIP_NO_CACHE_DIR=1

# PyTorch с CUDA 12.1 (подходит для 12.x рантайма)
RUN pip install --upgrade pip \
 && pip install --index-url https://download.pytorch.org/whl/cu121 \
      torch==2.3.1 torchvision==0.18.1

# Библиотеки для LTX Video через Diffusers
RUN pip install \
      runpod \
      "imageio[ffmpeg]" pillow numpy requests \
      accelerate transformers huggingface_hub hf-transfer \
 && pip install -U git+https://github.com/huggingface/diffusers

# Код воркера
WORKDIR /src
COPY handler.py /src/handler.py

# Запуск serverless-воркера
CMD ["python", "rp_handler.py"]
