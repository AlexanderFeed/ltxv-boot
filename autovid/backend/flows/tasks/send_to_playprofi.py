from typing import Dict, Any
from pathlib import Path
import os
import shutil
from autovid.backend.flows.config.celery_app import app
from autovid.backend.flows.steps.send_to_playprofi import PlayProfiUploader
from autovid.backend.flows.utils.logging import with_stage_logging
from autovid.backend.models.db_utils import get_project_by_id, get_db_session

class DatabaseManager:
    """Класс для работы с базой данных"""
    
    def __init__(self, project_id: int):
        self.project_id = project_id
    
    def load_project_data(self) -> Dict[str, Any]:
        """Загружает данные проекта из базы данных"""
        try:
            project = get_project_by_id(self.project_id)
            if not project:
                raise ValueError(f"Проект {self.project_id} не найден в базе данных")
            
            # Формируем данные для отправки
            project_data = {
                "project_id": self.project_id,
                "title": project.title,
                "description": project.description,
                "channel_id": project.channel_id,
                "prefix_code": project.prefix_code,
                "task_id": project.task_id,
                "video_format": project.video_format,
                "project_metadata": project.project_metadata,
                "metadata": project.project_metadata or {}
            }
            
            return project_data
            
        except Exception as e:
            print(f"❌ Ошибка при загрузке данных проекта из БД: {e}")
            raise
        
    def update_playprofi_status(self, uploaded: bool = True) -> None:
        """Обновляет статус загрузки на PlayProfi в базе данных"""
        try:
            project = get_project_by_id(self.project_id)
            if not project:
                raise ValueError(f"Проект {self.project_id} не найден в базе данных")
            
            # Обновляем метаданные
            if not project.project_metadata:
                project.project_metadata = {}
            
            project.project_metadata["playprofi_uploaded"] = uploaded
                
                # Сохраняем изменения
            with get_db_session() as session:
                session.merge(project)
                session.commit()
                
            print(f"✅ Статус PlayProfi обновлен в БД: uploaded={uploaded}")
                
        except Exception as e:
            print(f"❌ Ошибка при обновлении статуса PlayProfi в БД: {e}")
            raise
    
    def cleanup_project_files(self) -> None:
        """Удаляет все файлы проекта из папки assets после успешной отправки"""
        try:
            assets_dir = Path(os.getenv("ASSETS_DIR", "assets"))
            project_id_str = str(self.project_id)
            
            # Список папок и файлов для удаления
            paths_to_remove = [
                assets_dir / "video" / project_id_str,
                assets_dir / "scripts" / project_id_str,
                assets_dir / "chunks" / project_id_str,
                assets_dir / "prompts" / project_id_str,
                assets_dir / "audio" / project_id_str,
                assets_dir / "scripts" / project_id_str,
                assets_dir / "thumbnail" / f"thumbnail_{self.project_id}.jpg",
            ]
            
            for path in paths_to_remove:
                if path.exists():
                    if path.is_file():
                        path.unlink()
                        print(f"🗑️ Удален файл: {path}")
                    elif path.is_dir():
                        shutil.rmtree(path)
                        print(f"🗑️ Удалена папка: {path}")
            
            print(f"✅ Все файлы проекта {self.project_id} удалены из папки assets")
            
        except Exception as e:
            print(f"❌ Ошибка при удалении файлов проекта: {e}")
            # Не прерываем выполнение при ошибке удаления файлов
            print("⚠️ Продолжаем выполнение несмотря на ошибку удаления файлов")

@app.task(queue="send_to_cdn")
@with_stage_logging("send_to_cdn")
def send_to_cdn(project_id: int):
    db_manager = DatabaseManager(project_id)
    
    assets_dir = Path(os.getenv("ASSETS_DIR", "assets"))
    required_files = {
        "video": assets_dir / "video" / str(project_id) / "final_video.mp4",
        "script": assets_dir / "scripts" / str(project_id) / "script.txt",
        "thumbnail": assets_dir / "thumbnail" / f"thumbnail_{project_id}.jpg",
        "chunks": assets_dir / "chunks" / str(project_id) / "chunks.json",
        "prompts": assets_dir / "prompts" / str(project_id) / "image_prompts.json",
        "voiceover": assets_dir / "audio" / str(project_id) / "merged_output.mp3",
    }

    try:
        project_data = db_manager.load_project_data()
        if not project_data:
            print(f"❌ Проект {project_id} не найден в базе данных")
            return
        
        result = PlayProfiUploader(project_data, required_files).upload_files()
        db_manager.update_playprofi_status(result["success"])
        
        # Если отправка прошла успешно, удаляем файлы проекта
        if result.get("success", False):
            db_manager.cleanup_project_files()
        
        return result
    except Exception as e:
        print(f"❌ Ошибка при отправке проекта на PlayProfi: {e}")
        raise