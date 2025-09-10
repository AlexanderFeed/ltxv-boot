#!/usr/bin/env python3
"""
Скрипт для запуска официального inference демона
Запускать: python run_inference_daemon_official.py
"""

import os
import sys

# Устанавливаем переменные окружения для GPU и кеша
os.environ['CUDA_VISIBLE_DEVICES'] = '0'
os.environ["HF_HOME"] = "/workspace/.cache/huggingface"  # Путь к кешу в workspace
os.environ["HUGGINGFACE_HUB_CACHE"] = os.environ["HF_HOME"]
os.environ["TRANSFORMERS_CACHE"] = os.environ["HF_HOME"]
os.environ["DIFFUSERS_CACHE"] = os.environ["HF_HOME"]
# Не форсируем hf_transfer: стандартная загрузка надёжнее в базовом окружении

from inference_daemon_official import main

if __name__ == '__main__':
    # Запускаем демон
    main() 