#!/usr/bin/env python3
"""
Скрипт для запуска Celery воркера
Запускать: python run_celery_worker.py
"""

import os
import sys
from my_celery import celery_app

if __name__ == '__main__':
    # Устанавливаем переменные окружения для GPU
    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    
    # Запускаем воркер
    celery_app.worker_main([
        'worker',
        '--loglevel=info',
        '--concurrency=1',  # Только один воркер для экономии GPU памяти
        '--pool=solo'  # Используем solo pool для лучшей работы с GPU
    ]) 