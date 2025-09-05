import json
import os
from pathlib import Path
from typing import List, Dict, Any
from autovid.backend.flows.config.celery_app import app

from autovid.backend.flows.steps.subtitle import SubtitleGenerator 
from autovid.backend.flows.utils.logging import with_stage_logging

class FileManager:
    """Класс для управления аудио файлами"""
    
    def __init__(self, project_id: str, audio_dir: Path, chunks_file: Path):
        self.project_id = project_id
        self.audio_dir = audio_dir
        self.chunks_file = chunks_file

    
    def validate_paths(self) -> bool:
        """Проверяет существование необходимых путей"""
        if not self.audio_dir.exists():
            print(f"❌ Директория с аудио не найдена: {self.audio_dir}")
            raise FileNotFoundError(f"Директория с аудио не найдена: {self.audio_dir}")
        
        if not self.chunks_file.exists():
            print(f"❌ Файл с чанками не найден: {self.chunks_file}")
            raise FileNotFoundError(f"Файл с чанками не найден: {self.chunks_file}")
        
        return True
    
    def load_chunks(self) -> List[Dict[str, Any]]:
        """Загружает чанки из файла"""
        with open(self.chunks_file, 'r', encoding='utf-8') as f:
            return json.load(f)

@app.task(queue="subtitles")
@with_stage_logging("subtitles")
def generate_subtitles(project_id: int):
    try:
        assets_dir = Path(os.getenv("ASSETS_DIR", "assets"))
        audio_dir = assets_dir / "audio" / str(project_id)
        chunks_file = assets_dir / "chunks" / str(project_id) / "chunks.json"
        subtitles_dir = assets_dir / "subtitles" / str(project_id)
        subtitles_dir.mkdir(parents=True, exist_ok=True)
        
        file_manager = FileManager(project_id, audio_dir, chunks_file)
        file_manager.validate_paths()
        chunks = file_manager.load_chunks() 

        result = SubtitleGenerator(chunks, subtitles_dir, audio_dir).generate()
        return result
    except Exception as e:
        print(f"❌ Ошибка при генерации субтитров: {e}")
        raise