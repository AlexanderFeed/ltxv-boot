"""
voiceover_generator.py
---------------------
Модуль для генерации озвучки через ElevenLabs API.
Объектно-ориентированная версия.
"""
import os
from dotenv import load_dotenv
load_dotenv()
import json
import requests
from pathlib import Path
from pydub import AudioSegment
import sys
import time
from mutagen.mp3 import MP3, HeaderNotFoundError
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from autovid.backend.config import VOICEOVER_CONFIG, ELEVENLABS_API_KEY


@dataclass
class VoiceoverConfig:
    """Конфигурация для генерации озвучки"""
    api_key: str = ELEVENLABS_API_KEY
    voice_id: str = VOICEOVER_CONFIG["voice_id"]
    model_id: str = VOICEOVER_CONFIG["model_id"]
    stability: float = VOICEOVER_CONFIG["stability"]
    similarity_boost: float = VOICEOVER_CONFIG["similarity_boost"]
    max_retries: int = VOICEOVER_CONFIG["max_retries"]
    retry_delay: int = VOICEOVER_CONFIG["retry_delay"]
    target_dbfs: float = VOICEOVER_CONFIG["target_dbfs"]
    proxies: Optional[Dict[str, str]] = None
    
    def __post_init__(self):
        if self.proxies is None:
            self.proxies = VOICEOVER_CONFIG["proxies"]


class ElevenLabsAPIClient:
    """Класс для работы с ElevenLabs API"""
    
    def __init__(self, config: Optional[VoiceoverConfig] = None):
        self.config = config or VoiceoverConfig()
        self.api_url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.config.voice_id}"
        self.headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.config.api_key
        }
    
    def get_voice_id_by_name(self, name: str = "vYEa0poxgOWoLcB1c9Vz") -> Optional[str]:
        """Получает ID голоса по имени"""
        url = "https://api.elevenlabs.io/v1/voices"
        response = requests.get(
            url, 
            headers=self.headers, 
            proxies=self.config.proxies
        )
        response.raise_for_status()
        voices = response.json()["voices"]
        
        for voice in voices:
            if voice["name"].lower() == name.lower():
                return voice["voice_id"]
        
        return voices[0]["voice_id"] if voices else None
    
    def generate_audio(self, text: str) -> bytes:
        """Генерирует аудио через API"""
        data = {
            "text": text,
            "model_id": self.config.model_id,
            "voice_settings": {
                "stability": self.config.stability, 
                "similarity_boost": self.config.similarity_boost
            }
        }
        
        for attempt in range(self.config.max_retries):
            try:
                response = requests.post(
                    self.api_url, 
                    json=data, 
                    headers=self.headers, 
                    proxies=self.config.proxies
                )
                response.raise_for_status()
                return response.content
                
            except requests.exceptions.ConnectionError as e:
                print(f"[!] Ошибка соединения: {e}. Попытка {attempt+1}/{self.config.max_retries}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay)
                else:
                    raise


class AudioProcessor:
    """Класс для обработки аудио файлов"""
    
    def __init__(self, config: Optional[VoiceoverConfig] = None):
        self.config = config or VoiceoverConfig()
    
    def normalize_audio(self, audio_path: Path) -> None:
        """Нормализует громкость аудио файла"""
        audio = AudioSegment.from_file(audio_path)
        change_in_dbfs = self.config.target_dbfs - audio.dBFS
        normalized_audio = audio.apply_gain(change_in_dbfs)
        normalized_audio.export(audio_path, format="mp3")
    
    def is_mp3_valid(self, mp3_path: Path) -> bool:
        """Проверяет валидность MP3 файла"""
        try:
            audio = MP3(mp3_path)
            return audio.info.length > 0
        except (HeaderNotFoundError, Exception):
            return False


class VoiceoverGenerator:
    """Класс для генерации озвучки"""
    
    def __init__(self, config: Optional[VoiceoverConfig] = None):
        self.config = config or VoiceoverConfig()
        self.api_client = ElevenLabsAPIClient(config)
        self.audio_processor = AudioProcessor(config)
    
    def generate_voiceover(self, text: str, output_path: Path) -> bool:
        """Генерирует озвучку для текста"""
        try:
            # Генерируем аудио через API
            audio_data = self.api_client.generate_audio(text)
            
            # Сохраняем аудио
            with open(output_path, "wb") as f:
                f.write(audio_data)
            
            # Нормализуем громкость
            self.audio_processor.normalize_audio(output_path)
            
            print(f"✅ Озвучено: {output_path.name}")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка при генерации озвучки: {e}")
            return False


class AudioFileManager:
    """Класс для управления аудио файлами"""
    
    def __init__(self, project_id: int, audio_dir: Path):
        self.project_id = project_id
        self.audio_dir = audio_dir
    
    def get_audio_path(self, chunk_id: int) -> Path:
        """Возвращает путь к аудио файлу для чанка"""
        return self.audio_dir / f"scene_{chunk_id:02}.mp3"
    
    def is_audio_valid(self, audio_path: Path) -> bool:
        """Проверяет, существует ли и валиден ли аудио файл"""
        audio_processor = AudioProcessor()
        return audio_path.exists() and audio_processor.is_mp3_valid(audio_path)


class VoiceoverManager:
    """Основной класс для управления генерацией озвучки"""
    
    def __init__(self, project_id: int, chunks: List[Dict[str, Any]], audio_dir: Path, config: Optional[VoiceoverConfig] = None):
        self.project_id = project_id
        self.config = config or VoiceoverConfig()
        self.chunks = chunks
        self.audio_dir = audio_dir
        self.voiceover_generator = VoiceoverGenerator(config)
        self.file_manager = AudioFileManager(project_id, audio_dir)
    
    def generate_all_voiceovers(self, specific_chunk_id: Optional[int] = None) -> Dict[str, Any]:
        """Генерирует озвучку для всех чанков или конкретного чанка"""

        generated_count = 0
        skipped_count = 0
        failed_count = 0
        
        for chunk in self.chunks:
            chunk_id = chunk["id"]
            text = chunk["text"]
            
            # Пропускаем, если запрошен конкретный ID
            if specific_chunk_id is not None and int(chunk_id) != int(specific_chunk_id):
                continue
            
            output_path = self.file_manager.get_audio_path(chunk_id)
            
            # Проверяем, есть ли уже валидный файл
            if self.file_manager.is_audio_valid(output_path):
                print(f"✅ Уже есть: {output_path.name}")
                skipped_count += 1
                continue
            
            # Генерируем озвучку
            if self.voiceover_generator.generate_voiceover(text, output_path):
                generated_count += 1
            else:
                failed_count += 1
        
        return {
            "project_id": self.project_id,
            "total_chunks": len(self.chunks),
            "generated": generated_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "specific_chunk_id": specific_chunk_id
        }