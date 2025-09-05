"""
metadata_generator.py
-------------------
Модуль для генерации метаданных (название, описание, теги) для YouTube видео.
Объектно-ориентированная версия.
"""

import json
import re
from pathlib import Path
from datetime import datetime
from openai import OpenAI
from autovid.backend.config import OPENAI_API_KEY, METADATA_CONFIG
from autovid.backend.models.db import get_session
from autovid.backend.models.db_utils import get_project_by_id
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class MetadataConfig:
    """Конфигурация для генерации метаданных"""
    model_name: str = METADATA_CONFIG["model_name"]
    temperature: float = METADATA_CONFIG["temperature"]
    max_title_length: int = METADATA_CONFIG["max_title_length"]
    max_description_sentences: int = METADATA_CONFIG["max_description_sentences"]
    max_tags_count: int = METADATA_CONFIG["max_tags_count"]
    max_script_words_for_gpt: int = METADATA_CONFIG["max_script_words_for_gpt"]


class JSONExtractor:
    """Класс для извлечения JSON из ответа GPT"""
    
    @staticmethod
    def extract_json_from_gpt(raw_response: str) -> str:
        """Извлекает JSON из ответа GPT"""
        # Ищем JSON в ответе
        json_start = raw_response.find('{')
        json_end = raw_response.rfind('}') + 1
        
        if json_start != -1 and json_end != 0:
            return raw_response[json_start:json_end]
        
        return raw_response
    
    @staticmethod
    def parse_json_safely(json_string: str) -> Dict[str, Any]:
        """Безопасно парсит JSON"""
        try:
            return json.loads(json_string)
        except json.JSONDecodeError as e:
            raise ValueError(f"GPT вернул некорректный JSON: {json_string}. Ошибка: {e}")


class TagCleaner:
    """Класс для очистки и валидации тегов"""
    
    @staticmethod
    def clean_tag(tag: str) -> str:
        """Очищает тег от лишних символов"""
        if not isinstance(tag, str):
            return ""
        
        # Удаляем все управляющие символы, кроме обычного пробела
        cleaned = re.sub(r"[\s\u200b-\u200d\uFEFF\u00A0\u2028\u2029\r\n\t]+", " ", tag).strip()
        return cleaned
    
    @staticmethod
    def clean_tags(tags: List[str]) -> List[str]:
        """Очищает список тегов"""
        cleaned_tags = [TagCleaner.clean_tag(tag) for tag in tags]
        # Убираем пустые теги
        return [tag for tag in cleaned_tags if tag]


class ScriptProcessor:
    """Класс для обработки сценария"""
    
    @staticmethod
    def truncate_script(script_text: str, max_words: int) -> str:
        """Обрезает сценарий до указанного количества слов"""
        words = script_text.split()
        return " ".join(words[:max_words])


class GPTMetadataGenerator:
    """Класс для генерации метаданных с помощью GPT"""
    
    def __init__(self, config: Optional[MetadataConfig] = None):
        self.config = config or MetadataConfig()
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.json_extractor = JSONExtractor()
    
    def _build_prompt(self, topic: str, script_text: str) -> str:
        """Строит промпт для GPT"""
        return f"""Вот тема и текст сценария для ролика на YouTube. На их основе сгенерируй:
1. Короткое и интригующее название для ютуб ролика (не более {self.config.max_title_length} символов) по следующей инструкции: Ты мастер названий ютуб роликов. твоя задача на основе темы и куска сценария предложить кликбейтное название на заданную тему. Не используй высокопарный язык и сильное красноречие. Выдавай результат простым и понятным языком. Самая главная задача при написании названия - удивить зрителя и заинтересовать его на просмотр ролика. Название должно быть кричащим, ярким и захватывающим, но без преувеличений. Предупреждение: выдавай только названия. Пиши каждое слово в названии с большой буквы!
2. Описание ролика — не более {self.config.max_description_sentences} предложений, обязательно с использованием ключевых слов и поисковых запросов по этой теме, SEO-оптимизированное описание должно включать предположительно подходящие под эту тему поисковые запросы пользователей ютуб, которые будут смотреть это видео.
3. Список из {self.config.max_tags_count} тематических тегов, каждый тег — одно-два слова. Теги также должны попадать в поисковые запросы которые могут искать пользователи ютуб.

ВНИМАНИЕ! Выводи всё строго в JSON формате с ключами: title, description, tags

Тема ролика:
{topic}

Текст сценария:
{script_text}
"""
    
    def generate_metadata(self, topic: str, script_text: str) -> Dict[str, Any]:
        """Генерирует метаданные с помощью GPT"""
        prompt = self._build_prompt(topic, script_text)
        
        response = self.client.chat.completions.create(
            model=self.config.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.config.temperature,
        )
        
        raw_response = response.choices[0].message.content.strip()
        clean_json = self.json_extractor.extract_json_from_gpt(raw_response)
        
        return self.json_extractor.parse_json_safely(clean_json)


class DatabaseManager:
    """Класс для работы с базой данных"""
    
    def __init__(self):
        pass
    
    def get_project_data(self, project_id: int) -> Dict[str, Any]:
        """Получает данные проекта из базы данных"""
        try:
            project = get_project_by_id(project_id)
            if not project:
                raise ValueError(f"Проект {project_id} не найден в базе данных")
            
            # Обрабатываем метаданные - могут быть строкой или JSON объектом
            metadata = project.project_metadata or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (json.JSONDecodeError, TypeError):
                    metadata = {}
            
            return {
                "topic": project.topic,
                "title": project.title,
                "description": project.description,
                "metadata": metadata
            }
            
        except Exception as e:
            print(f"❌ Ошибка при получении данных проекта из БД: {e}")
            raise
    
    def update_project_metadata(self, project_id: int, metadata: Dict[str, Any]) -> None:
        """Обновляет метаданные проекта в базе данных"""
        try:
            project = get_project_by_id(project_id)
            if not project:
                raise ValueError(f"Проект {project_id} не найден в базе данных")
            
            # Обновляем поля проекта
            project.title = metadata.get("title", "")
            project.description = metadata.get("description", "")
            
            # Обновляем метаданные - теперь это JSON объект
            existing_metadata = project.project_metadata or {}
            if isinstance(existing_metadata, str):
                try:
                    existing_metadata = json.loads(existing_metadata)
                except (json.JSONDecodeError, TypeError):
                    existing_metadata = {}
            
            existing_metadata.update(metadata)
            project.project_metadata = existing_metadata
            
            # Сохраняем изменения
            with get_session() as session:
                session.merge(project)
                session.commit()
            
            print(f"✅ Метаданные проекта {project_id} обновлены в БД")
            
        except Exception as e:
            print(f"❌ Ошибка при обновлении метаданных проекта в БД: {e}")
            raise


class MetadataManager:
    """Основной класс для управления метаданными проекта"""
    
    def __init__(self, config: Optional[MetadataConfig] = None):
        self.config = config or MetadataConfig()
        self.gpt_generator = GPTMetadataGenerator(config)
        self.tag_cleaner = TagCleaner()
        self.script_processor = ScriptProcessor()
        self.db_manager = DatabaseManager()
        
        # Пути
        self.assets_path = Path("assets")
        self.scripts_path = self.assets_path / "scripts"
    
    def _load_script(self, project_id: int) -> str:
        """Загружает сценарий проекта"""
        script_path = self.scripts_path / f"{project_id}" / "script.txt"
        return script_path.read_text(encoding="utf-8")
    
    def _process_metadata(self, raw_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Обрабатывает и очищает метаданные"""
        # Очищаем теги
        cleaned_tags = self.tag_cleaner.clean_tags(raw_metadata.get("tags", []))
        
        return {
            "title": raw_metadata.get("title", ""),
            "description": raw_metadata.get("description", ""),
            "tags": cleaned_tags
        }
    
    def generate_and_update_metadata(self, project_id: int) -> Dict[str, Any]:
        """Генерирует и обновляет метаданные для проекта"""
        try:
            # Загружаем данные проекта из БД
            project_data = self.db_manager.get_project_data(project_id)
            topic = project_data.get("topic", "")
            
            # Загружаем и обрабатываем сценарий
            script_text = self._load_script(project_id)
            truncated_script = self.script_processor.truncate_script(
                script_text, 
                self.config.max_script_words_for_gpt
            )
            
            # Генерируем метаданные
            raw_metadata = self.gpt_generator.generate_metadata(topic, truncated_script)
            
            # Обрабатываем и очищаем метаданные
            processed_metadata = self._process_metadata(raw_metadata)
            
            # Обновляем базу данных
            self.db_manager.update_project_metadata(project_id, processed_metadata)
            
            return processed_metadata
            
        except Exception as e:
            raise

