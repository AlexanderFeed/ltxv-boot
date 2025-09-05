"""
send_to_playprofi.py
-------------------
Модуль для отправки файлов проекта на PlayProfi.
Объектно-ориентированная версия.
"""
import requests
from pathlib import Path
import time
import json
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, Optional
from dataclasses import dataclass

from autovid.backend.config import PLAYPROFI_CONFIG

# Отключаем предупреждения о небезопасных запросах
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass
class PlayProfiConfig:
    """Конфигурация для отправки на PlayProfi"""
    api_url: str = PLAYPROFI_CONFIG["api_url"]
    timeout: int = PLAYPROFI_CONFIG["timeout"]
    max_retries: int = PLAYPROFI_CONFIG["max_retries"]
    backoff_factor: int = PLAYPROFI_CONFIG["backoff_factor"]
    pool_connections: int = PLAYPROFI_CONFIG["pool_connections"]
    pool_maxsize: int = PLAYPROFI_CONFIG["pool_maxsize"]
    verify_ssl: bool = PLAYPROFI_CONFIG["verify_ssl"]  

class FileValidator:
    """Класс для валидации файлов проекта"""
    
    def __init__(self, project_id: int, required_files: Dict[str, Path]):
        self.project_id = project_id
        self.required_files = required_files
    
    def validate_files(self) -> None:
        """Проверяет наличие всех необходимых файлов"""
        missing_files = []
        for name, path in self.required_files.items():
            if not path.exists():
                missing_files.append(f"{name} ({path})")
        
        if missing_files:
            raise FileNotFoundError(f"Отсутствуют необходимые файлы: {', '.join(missing_files)}")
    
    def validate_project_data(self, project_data: Dict[str, Any]) -> None:
        """Проверяет наличие обязательных полей в данных проекта"""
        required_fields = ["prefix_code"]
        missing_fields = []
        for field in required_fields:
            if field not in project_data or not project_data[field]:
                missing_fields.append(field)
        
        if missing_fields:
            raise ValueError(f"В данных проекта отсутствуют обязательные поля: {', '.join(missing_fields)}")
    
    def get_file_paths(self) -> Dict[str, Path]:
        """Возвращает пути к файлам"""
        return self.required_files.copy()


class UploadSessionManager:
    """Класс для управления сессией загрузки"""
    
    def __init__(self, config: Optional[PlayProfiConfig] = None):
        self.config = config or PlayProfiConfig()
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """Создает оптимизированную сессию"""
        session = requests.Session()
        
        # Настраиваем retry стратегию
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.backoff_factor,
            status_forcelist=[500, 502, 503, 504]
        )
        
        # Настраиваем адаптер
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=self.config.pool_connections,
            pool_maxsize=self.config.pool_maxsize
        )
        
        # Применяем адаптер к сессии
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        return session


class ProgressCallback:
    """Класс для отслеживания прогресса загрузки"""
    
    def __init__(self, total_size: int):
        self.total_size = total_size
        self.start_time = time.time()
    
    def __call__(self, monitor: MultipartEncoderMonitor) -> None:
        """Callback для отслеживания прогресса"""
        percent = monitor.bytes_read / self.total_size * 100
        speed = monitor.bytes_read / 1024 / 1024 / (time.time() - self.start_time)
        current_time = time.time()
        
        # Обновляем прогресс каждые 5% или каждые 5 секунд
        if percent - getattr(self, '_last_percent', 0) >= 5 or current_time - getattr(self, '_last_time', 0) >= 5:
            print(f"\rЗагрузка: {percent:.1f}% ({monitor.bytes_read/1024/1024:.2f} МБ / {self.total_size/1024/1024:.2f} МБ) | {speed:.2f} МБ/сек", end="")
            self._last_percent = percent
            self._last_time = current_time


class PlayProfiUploader:
    """Основной класс для загрузки на PlayProfi"""
    
    def __init__(self, project_data: Dict[str, Any], required_files: Dict[str, Path], config: Optional[PlayProfiConfig] = None):
        self.config = config or PlayProfiConfig()
        self.project_data = project_data
        self.file_validator = FileValidator(project_data["project_id"], required_files)
        self.session_manager = UploadSessionManager(config)
    
    def prepare_upload_data(self, project_data: Dict[str, Any]) -> Dict[str, Any]:
        """Подготавливает данные для загрузки"""
        file_paths = self.file_validator.get_file_paths()
        
        # Сериализуем metadata в JSON строку, если это словарь
        metadata = project_data.get("project_metadata", {})
        if isinstance(metadata, dict):
            metadata = json.dumps(metadata, ensure_ascii=False)
        elif metadata is None:
            metadata = "{}"
        
        return {
            "channel_id": str(project_data["channel_id"]),
            "prefix_code": str(project_data["prefix_code"]),
            "task_id": str(project_data["task_id"]),
            "project_metadata": metadata,
            "montage_file": ("video", file_paths["video"].open("rb"), "video/mp4"),
            "scenario_file": ("script.txt", file_paths["script"].open("rb"), "text/plain"),
            "preview_file": ("thumbnail.jpg", file_paths["thumbnail"].open("rb"), "image/jpeg"),
            "chunks_file": ("chunks.json", file_paths["chunks"].open("rb"), "application/json"),
            "image_prompts_file": ("prompts.json", file_paths["prompts"].open("rb"), "application/json"),
            "voiceover_file": ("voiceover.mp3", file_paths["voiceover"].open("rb"), "audio/mpeg")
        }
    
    def upload_files(self) -> Dict[str, Any]:
        """Выполняет загрузку файлов на PlayProfi"""
        
        # Проверяем файлы и данные
        self.file_validator.validate_files()
        self.file_validator.validate_project_data(self.project_data)
        
        print(f"🚀 Отправка проекта {self.project_data['project_id']} на PlayProfi...")
        print(f"📺 Канал ID: {self.project_data['channel_id']}")
        print(f"🎬 Префикс: {self.project_data['prefix_code']}")
        
        # Подготавливаем данные для загрузки
        upload_data = self.prepare_upload_data(self.project_data)
        
        # Диагностическое логирование project_metadata перед отправкой
        try:
            metadata_str = upload_data.get("project_metadata", "")
            meta_keys = []
            title = None
            desc_len = 0
            tags_count = 0
            try:
                meta_obj = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
                if isinstance(meta_obj, dict):
                    meta_keys = list(meta_obj.keys())
                    title = meta_obj.get("title")
                    desc_len = len(meta_obj.get("description", ""))
                    tags = meta_obj.get("tags", [])
                    tags_count = len(tags) if isinstance(tags, list) else 0
            except Exception as e:
                print(f"⚠️ project_metadata JSON parse error: {e}")
            print(
                f"🧾 project_metadata: len={len(metadata_str) if isinstance(metadata_str, str) else 'n/a'}",
                f"keys={meta_keys}",
                f"title={title!r}",
                f"description_len={desc_len}",
                f"tags_count={tags_count}",
            )
        except Exception as e:
            print(f"⚠️ Logging project_metadata failed: {e}")
        
        # Создаем multipart encoder
        encoder = MultipartEncoder(fields=upload_data)
        
        # Диагностика сетевых параметров перед POST
        try:
            print(f"🌐 PlayProfi URL: {self.config.api_url}")
            print(f"🔐 verify_ssl={self.config.verify_ssl} | timeout={self.config.timeout}s | content_length={encoder.len} | content_type={encoder.content_type}")
        except Exception as e:
            print(f"⚠️ Logging network params failed: {e}")
        
        # Создаем callback для отслеживания прогресса
        callback = ProgressCallback(encoder.len)
        monitor = MultipartEncoderMonitor(encoder, callback)
        
        # Выполняем загрузку
        try:
            response = self.session_manager.session.post(
                self.config.api_url,
                data=monitor,
                headers={
                    "Content-Type": monitor.content_type,
                    "Accept": "application/json",
                    "Connection": "close",
                },
                timeout=self.config.timeout,
                verify=self.config.verify_ssl
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Файлы успешно отправлены на PlayProfi")
                print(f"📋 Ответ сервера: {result}")
                
                return {
                    "success": True,
                    "project_id": self.project_data["project_id"],
                    "response": result
                }
            else:
                print(f"❌ Ошибка при отправке на PlayProfi: {response.status_code}")
                print(f"📋 Ответ сервера: {response.text}")
                
                return {
                    "success": False,
                    "project_id": self.project_data["project_id"],
                    "error": f"HTTP {response.status_code}: {response.text}"
                }
                
        except Exception as e:
            print(f"❌ Ошибка при отправке на PlayProfi: {e}")
            
            return {
                "success": False,
                "project_id": self.project_data["project_id"],
                "error": str(e)
            }
