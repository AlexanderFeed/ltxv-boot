import json
import os
from pathlib import Path
from typing import List, Dict, Any
from autovid.backend.flows.config.celery_app import app

from autovid.backend.flows.steps.prompt import PromptManager
from autovid.backend.flows.utils.logging import with_stage_logging

class FileManager:
    """Класс для обработки текстовых фрагментов"""
    
    def __init__(self, input_path: Path, output_path: Path):
        self.input_path = input_path
        self.output_path = output_path
    
    def load_chunks(self) -> List[Dict[str, Any]]:
        """Загружает чанки из файла"""
        chunks_path = self.input_path
        
        if not chunks_path.exists():
            raise FileNotFoundError(f"Файл чанков не найден: {chunks_path}")
        
        with chunks_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    
    def save_prompts(self, prompts: List[Dict[str, Any]]) -> None:
        """Сохраняет промпты в файл"""
        prompts_path = self.output_path
        prompts_path.parent.mkdir(parents=True, exist_ok=True)
        
        with prompts_path.open("w", encoding="utf-8") as f:
            json.dump(prompts, f, ensure_ascii=False, indent=2)

@app.task(queue="prompts")
@with_stage_logging("prompts")
def generate_prompts(project_id: int):
    try:
        assets_dir = Path(os.getenv("ASSETS_DIR", "assets"))
        input_path = assets_dir / "chunks" / str(project_id) / "chunks.json"
        output_path = assets_dir / "prompts" / str(project_id) / "image_prompts.json"
        
        chunks = FileManager(input_path, output_path).load_chunks()
        
        result = PromptManager(chunks).generate()
    
        FileManager(input_path, output_path).save_prompts(result)
        
        return result
    except Exception as e:
        print(f"❌ Ошибка при генерации промптов: {e}")
        raise
