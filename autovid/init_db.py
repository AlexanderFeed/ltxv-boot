#!/usr/bin/env python3
"""
Скрипт для инициализации базы данных
"""

import sys
from pathlib import Path

# Добавляем backend в путь
sys.path.append(str(Path(__file__).parent / "backend"))

from backend.models.db import create_database, cleanup_database_locks, get_db_session, Channel

def init_database():
    """Инициализирует базу данных и создает базовые данные"""
    print("Создание базы данных...")
    
    # Очищаем возможные блокировки
    cleanup_database_locks()
    
    # Создаем базу данных и таблицы
    create_database()
    
    # Создаем базовый канал если его нет
    with get_db_session() as session:
        existing_channel = session.query(Channel).filter_by(id=1).first()
        if not existing_channel:
            default_channel = Channel(
                id=1,
                name="Основной канал",
                youtube_id="default",
                prefix_code="MAIN",
                token_file="default_token.json"
            )
            session.add(default_channel)
            session.commit()
            print("Создан базовый канал")
        else:
            print("Базовый канал уже существует")
    
    print("База данных успешно инициализирована!")

if __name__ == "__main__":
    init_database() 