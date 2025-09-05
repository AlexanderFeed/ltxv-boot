import json
import os
from pathlib import Path
from typing import List, Dict, Any
from autovid.backend.flows.config.celery_app import app

from autovid.backend.flows.steps.flux_image_gen import FluxImageManager
from autovid.backend.flows.utils.logging import with_stage_logging

class FileManager:
    """Класс для работы с файлами промптов"""
    
    def __init__(self, project_id: int, prompts_path: Path):
        self.project_id = project_id
        self.prompts_path = prompts_path
    
    def get_prompts(self) -> List[Dict[str, Any]]:
        """Получает промпты проекта из файла prompts/*.json"""
        try:
            if not self.prompts_path.exists():
                raise FileNotFoundError(f"Файл промптов не найден: {self.prompts_path}")
            
            with open(self.prompts_path, 'r', encoding='utf-8') as f:
                prompts_data = json.load(f)
            
            if not isinstance(prompts_data, list):
                raise ValueError(f"Неверный формат файла промптов: ожидается список")
            
            return prompts_data
            
        except Exception as e:
            print(f"❌ Ошибка при получении промптов из файла: {e}")
            return []

@app.task(queue="images")
@with_stage_logging("images")
def generate_images(project_id: int, video_format: str = "long"):
    try:
        assets_dir = Path(os.getenv("ASSETS_DIR", "assets"))
        prompts_path = assets_dir / "prompts" / str(project_id) / "image_prompts.json"
        scenes_dir = assets_dir / "scenes" / str(project_id)
        scenes_dir.mkdir(parents=True, exist_ok=True)
        
        prompts = FileManager(project_id, prompts_path).get_prompts()
        result = FluxImageManager(project_id, video_format, prompts, scenes_dir).generate()
        
        return result
    except Exception as e:
        print(f"❌ Ошибка при генерации изображений: {e}")
        raise
