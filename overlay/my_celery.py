# my_celery.py
from celery import Celery
import os

# Настройка Celery
celery_app = Celery(
    'ltx_video',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0',
    include=['celery_task_inference']  # Используем новый task
)

# Настройки Celery
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

# 👇 Обязательно импортируем celery_task_inference, чтобы Celery увидел задачи!
import celery_task_inference