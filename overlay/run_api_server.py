#!/usr/bin/env python3
"""
Скрипт для запуска API сервера
Запускать: python run_api_server.py
"""

import uvicorn
from server import app

if __name__ == '__main__':
    print("Запускаем API сервер...")
    print("Модели НЕ загружаются в API сервере - они загружаются только в Celery воркерах")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    ) 