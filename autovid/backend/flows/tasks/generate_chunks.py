import json
import os
from pathlib import Path
from typing import List, Dict, Any
from autovid.backend.flows.config.celery_app import app

from autovid.backend.models.db_utils import get_project
from autovid.backend.flows.steps.chunker import ChunkingManager
from autovid.backend.flows.utils.logging import with_stage_logging

class FileManager:
    """Класс для работы с файлами"""
    
    def __init__(self, project_id: int, input_path: Path, output_path: Path):
        self.project_id = project_id
        self.input_path = input_path
        self.output_path = output_path
    
    def load_script(self) -> str:
        """Загружает сценарий из файла"""
        if not self.input_path.exists():
            raise FileNotFoundError(f"Файл сценария не найден: {self.input_path}")
        
        with self.input_path.open("r", encoding="utf-8") as f:
            return f.read()
    
    def save_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        """Сохраняет чанки в файл"""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with self.output_path.open("w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)

@app.task(queue="chunks")
@with_stage_logging("chunks")
def generate_chunks(project_id: int):
    project = get_project(project_id=project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found in database")
        
    video_format = project.video_format

    assets_dir = Path(os.getenv("ASSETS_DIR", "assets"))
    input_path = assets_dir / "scripts" / str(project_id) / "script.txt"
    output_path = assets_dir / "chunks" / str(project_id) / "chunks.json"
    
    file_manager = FileManager(project_id, input_path, output_path)
    script = file_manager.load_script()

    manager = ChunkingManager(project_id, video_format, script)
    chunks = manager.generate()
    
    file_manager.save_chunks(chunks)
    
    return chunks
