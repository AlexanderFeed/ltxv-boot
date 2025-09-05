from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import uvicorn
from pathlib import Path
import os
import uuid
import shutil
from datetime import datetime, timezone
import glob

# Импорты для работы с базой данных и Prefect
from sqlalchemy import text
from autovid.backend.models.db import get_db_session, Project, Stage, create_database
from autovid.backend.models.db_utils import create_project, get_project, get_stages, get_all_projects, update_stage
from autovid.backend.flows.main_flow import add_to_queue

# Импорты для задач
from autovid.backend.flows.tasks.generate_script import generate_script
from autovid.backend.flows.tasks.generate_metadata import generate_metadata
from autovid.backend.flows.tasks.generate_chunks import generate_chunks
from autovid.backend.flows.tasks.generate_prompts import generate_prompts
from autovid.backend.flows.tasks.generate_images import generate_images
from autovid.backend.flows.tasks.generate_voiceover import generate_voiceover
from autovid.backend.flows.tasks.generate_video import generate_video
from autovid.backend.flows.tasks.send_to_playprofi import send_to_cdn
from autovid.backend.flows.tasks.generate_thumbnail import generate_thumbnail

app = FastAPI(title="Video Generation API", version="1.0.0")

# Разрешаем CORS для фронта
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Обработчик ошибок валидации с подробным логированием"""
    print(f"❌ Ошибка валидации запроса:")
    print(f"   URL: {request.url}")
    print(f"   Метод: {request.method}")
    print(f"   Ошибки: {exc.errors()}")
    
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Ошибка валидации данных",
            "errors": exc.errors(),
            "received_data": str(request.body()) if hasattr(request, 'body') else "Не удалось получить данные"
        }
    )

# Модели Pydantic
class Task(BaseModel):
    topic: str
    chapters: int
    channel_id: str
    thumbnail_path: Optional[str] = None

class ProjectCreate(BaseModel):
    topic: str
    chapters: int = 1
    channel_id: str = ""
    video_format: str = "long"
    thumbnail_path: Optional[str] = None
    queue_id: str = "medium_priority"  # Фронтенд отправляет queue_id вместо priority
    status: bool = False
    prefix_code: str = "RU"
    task_id: Optional[str] = None  # Сделаем опциональным, так как фронтенд его не отправляет
    
class ProjectResponse(BaseModel):
    id: int
    topic: str
    title: Optional[str]
    priority: str
    status: bool
    description: Optional[str]
    chapters: int
    channel_id: str
    video_format: str
    thumbnail_path: Optional[str]
    created_at: datetime
    updated_at: datetime
    stages: List[Dict[str, Any]]
    paused: bool
    runpod_id: str
    prefix_code: str
    task_id: str

class RestartStageRequest(BaseModel):
    stage_name: str

class DownloadStageRequest(BaseModel):
    stage_name: str
    file_type: Optional[str] = None  # Для этапов с несколькими файлами
# Пути для файлов
ASSETS_DIR = Path(os.getenv("ASSETS_DIR", "assets"))
THUMB_TMP = ASSETS_DIR / "thumbnail" / "tmp"
THUMB_TMP.mkdir(parents=True, exist_ok=True)

# Путь к директории с логами
LOGS_DIR = Path("/logs")

def get_stage_files(project_id: int, stage_name: str) -> Dict[str, Any]:
    """Возвращает информацию о файлах, связанных с этапом"""
    base_path = ASSETS_DIR
    
    stage_files = {
        "script": {
            "files": [
                {
                    "name": "script.txt",
                    "path": base_path / "scripts" / str(project_id) / "script.txt",
                    "description": "Сгенерированный сценарий",
                    "mime_type": "text/plain"
                }
            ]
        },
        "metadata": {
            "files": [
                {
                    "name": "metadata.json",
                    "path": base_path / "scripts" / str(project_id) / "metadata.json",
                    "description": "Метаданные проекта (заголовок, описание, теги)",
                    "mime_type": "application/json"
                }
            ]
        },
        "chunks": {
            "files": [
                {
                    "name": "chunks.json",
                    "path": base_path / "chunks" / str(project_id) / "chunks.json",
                    "description": "Разбитый на чанки сценарий",
                    "mime_type": "application/json"
                }
            ]
        },
        "prompts": {
            "files": [
                {
                    "name": "image_prompts.json",
                    "path": base_path / "prompts" / str(project_id) / "image_prompts.json",
                    "description": "Промпты для генерации изображений",
                    "mime_type": "application/json"
                }
            ]
        },
        "images": {
            "files": [
                {
                    "name": "scenes.zip",
                    "path": base_path / "scenes" / str(project_id),
                    "description": "Все сгенерированные изображения сцен",
                    "mime_type": "application/zip",
                    "is_directory": True
                }
            ]
        },
        "thumbnail": {
            "files": [
                {
                    "name": f"thumbnail_{project_id}.jpg",
                    "path": base_path / "thumbnail" / f"thumbnail_{project_id}.jpg",
                    "description": "Превью видео",
                    "mime_type": "image/jpeg"
                }
            ]
        },
        "voiceover": {
            "files": [
                {
                    "name": "merged_output.mp3",
                    "path": base_path / "audio" / str(project_id) / "merged_output.mp3",
                    "description": "Объединенная озвучка",
                    "mime_type": "audio/mpeg"
                },
                {
                    "name": "audio_files.zip",
                    "path": base_path / "audio" / str(project_id),
                    "description": "Все аудиофайлы по чанкам",
                    "mime_type": "application/zip",
                    "is_directory": True
                }
            ]
        },
        "video": {
            "files": [
                {
                    "name": "final_video.mp4",
                    "path": base_path / "video" / str(project_id) / "final_video.mp4",
                    "description": "Финальное видео",
                    "mime_type": "video/mp4"
                },
                {
                    "name": "video_files.zip",
                    "path": base_path / "video" / str(project_id),
                    "description": "Все файлы видео (сцены + финальное)",
                    "mime_type": "application/zip",
                    "is_directory": True
                }
            ]
        },
        "send_to_cdn": {
            "files": [
                {
                    "name": "upload_status.json",
                    "path": base_path / "uploads" / str(project_id) / "upload_status.json",
                    "description": "Статус загрузки на CDN",
                    "mime_type": "application/json"
                }
            ]
        }
    }
    
    return stage_files.get(stage_name, {"files": []})

def create_zip_from_directory(directory_path: Path, zip_name: str) -> Path:
    """Создает ZIP архив из директории"""
    import zipfile
    import tempfile
    
    temp_dir = Path(tempfile.gettempdir())
    zip_path = temp_dir / f"{zip_name}_{uuid.uuid4().hex}.zip"
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in directory_path.rglob('*'):
            if file_path.is_file():
                arcname = file_path.relative_to(directory_path)
                zipf.write(file_path, arcname)
    
    return zip_path

def calculate_project_progress(stages: List[Stage]) -> dict:
    """Вычисляет прогресс проекта на основе этапов"""
    completed_stages = len([s for s in stages if s["completed"]])
    total_expected_stages = len(stages)
    
    progress_percentage = (completed_stages / total_expected_stages * 100) if total_expected_stages > 0 else 0
    
    return {
        "completed_stages": completed_stages,
        "total_expected_stages": total_expected_stages,
        "percentage": round(progress_percentage, 1)
    }

# ===== ПРОЕКТЫ =====

@app.get("/api/projects")
async def get_projects():
    """Получить список всех проектов"""
    projects = get_all_projects()
    print(projects)
    result = []
    for project in projects:
        stages = get_stages(project["id"])
        stages_data = [
                {
                    "id": stage["id"],
                    "name": stage["name"],
                    "completed": stage["completed"],
                    "started_at": stage["started_at"],
                    "completed_at": stage["completed_at"],
                    "duration_seconds": stage["duration_seconds"],
                    "error_message": stage["error_message"],
                    "paused": stage["paused"]
                }
                for stage in stages
        ]
            
            # Вычисляем прогресс проекта
        progress = calculate_project_progress(stages)
            
        project_response = ProjectResponse(
                id=project["id"],
                topic=project["topic"],
                title=project["title"],
                priority=project["priority"],
                status=project["status"],
                description=project["description"],
                chapters=project["chapters"],
                channel_id=project["channel_id"],
                video_format=project["video_format"],
                thumbnail_path=project["thumbnail_path"],
                created_at=project["created_at"],
                updated_at=project["updated_at"],
                stages=stages_data,
                paused=project["paused"],
                runpod_id=project["runpod_id"],
                prefix_code=project["prefix_code"],
                task_id=project["task_id"]
        )
            
            # Добавляем информацию о прогрессе
        project_dict = project_response.dict()
        project_dict["progress"] = progress
            
        result.append(project_dict)
    return result

@app.get("/api/projects/{project_id}", response_model=ProjectResponse)
async def get_project_api(project_id: int):
    """Получить проект по ID"""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
        
    stages = get_stages(project_id)
    stages_data = [
            {
                "id": stage["id"],
                "name": stage["name"],
                "completed": stage["completed"],
                "started_at": stage["started_at"],
                "completed_at": stage["completed_at"],
                "duration_seconds": stage["duration_seconds"],
                "error_message": stage["error_message"],
                "paused": stage["paused"]
            }
            for stage in stages
    ]
        
        # Вычисляем прогресс проекта
    progress = calculate_project_progress(stages)
        
    project_response = ProjectResponse(
            id=project.id,
            topic=project.topic,
            title=project.title,
            priority=project.priority,
            status=project.status,
            description=project.description,
            chapters=project.chapters,
            channel_id=project.channel_id,
            video_format=project.video_format,
            thumbnail_path=project.thumbnail_path,
            created_at=project.created_at,
            updated_at=project.updated_at,
            stages=stages_data,
            paused=project.paused,
            runpod_id=project.runpod_id,
            prefix_code=project.prefix_code,
            task_id=project.task_id
    )
        
        # Добавляем информацию о прогрессе
    project_dict = project_response.dict()
    project_dict["progress"] = progress
        
    return project_dict

@app.post("/api/projects", response_model=ProjectResponse)
async def create_project_api(project_data: ProjectCreate):
    """Создать новый проект с приоритетом"""
    print(f"🔍 Получен запрос на создание проекта:")
    print(f"   topic: {project_data.topic}")
    print(f"   chapters: {project_data.chapters}")
    print(f"   channel_id: {project_data.channel_id}")
    print(f"   video_format: {project_data.video_format}")
    print(f"   queue_id: {project_data.queue_id}")
    print(f"   task_id: {project_data.task_id}")
    print(f"   thumbnail_path: {project_data.thumbnail_path}")
    
    # Преобразуем queue_id в priority
    priority_map = {
        "low_priority": "low",
        "medium_priority": "medium", 
        "high_priority": "high"
    }
    priority = priority_map.get(project_data.queue_id, "medium")
    
    if priority not in ["low", "medium", "high"]:
        raise HTTPException(status_code=400, detail="Invalid priority level")

    project = create_project(project_data.topic, project_data.chapters, project_data.channel_id, project_data.video_format, project_data.thumbnail_path, priority, project_data.prefix_code, project_data.task_id or "")
    project_id = project.id
    topic = project.topic
    chapters = project.chapters
    video_format = project.video_format
    
    queue_name = f"{priority}_priority"
    add_to_queue.apply_async(args=[project_id, topic, chapters, video_format], queue=queue_name)

    return project

@app.delete("/api/projects/{project_id}")
async def delete_project_api(project_id: int):
    """Удалить проект"""
    with get_db_session() as session:
        project = session.query(Project).filter_by(id=project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Проект не найден")
        
        session.delete(project)
        session.commit()
        return {"status": "ok"}
    

@app.put("/api/projects/{project_id}/priority")
async def update_project_priority(project_id: int, new_priority: str = Body(..., embed=True)):
    """Изменить приоритет проекта"""
    if new_priority not in ["low", "medium", "high"]:
        raise HTTPException(status_code=400, detail="Invalid priority level")

    with get_db_session() as session:
        project = session.query(Project).filter_by(id=project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Проект не найден")
        
        project.priority = new_priority
        session.commit()
        
        return {"status": "ok", "new_priority": new_priority}

@app.post("/api/projects/{project_id}/start")
async def start_project(project_id: int):
    """Запустить проект"""
    with get_db_session() as session:
        project = session.query(Project).filter_by(id=project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Проект не найден")
        
        # Логика для запуска проекта
        # Например, изменение статуса проекта или добавление в очередь
        project.paused = False  # Пример изменения статуса
        session.commit()
        
        return {"status": "ok", "message": "Проект запущен"}

@app.post("/api/projects/{project_id}/stop")
async def stop_project(project_id: int):
    """Остановить проект"""
    with get_db_session() as session:
        project = session.query(Project).filter_by(id=project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Проект не найден")
        
        # Логика для остановки проекта
        # Например, изменение статуса проекта
        project.paused = True  # Пример изменения статуса
        session.commit()
        
        return {"status": "ok", "message": "Проект остановлен"}
    

@app.get("/api/projects/{project_id}/status")
async def get_project_status_api(project_id: int):
    """Получить статус выполнения проекта"""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
        
    stages = get_stages(project_id)
        
    return {
            "project": {
                "id": project.id,
                "topic": project.topic,
                "title": project.title,
                "description": project.description,
                "chapters": project.chapters,
                "channel_id": project.channel_id,
                "video_format": project.video_format,
                "thumbnail_path": project.thumbnail_path,
                "created_at": project.created_at,
                "updated_at": project.updated_at,
                "paused": project.paused,
                "runpod_id": project.runpod_id,
                "prefix_code": project.prefix_code,
                "task_id": project.task_id
            },
            "stages": [
                {
                    "id": stage["id"],
                    "name": stage["name"],
                    "completed": stage["completed"],
                    "started_at": stage["started_at"],
                    "completed_at": stage["completed_at"],
                    "duration_seconds": stage["duration_seconds"],
                    "error_message": stage["error_message"],
                    "paused": stage["paused"]
                }
                for stage in stages
            ]
    }


# ===== СИСТЕМНАЯ ИНФОРМАЦИЯ =====

@app.get("/api/queues")
async def get_queues_api():
    """Получить список доступных очередей"""
    queues = [
        {"id": "low_priority", "name": "Низкий приоритет", "description": "Очередь для задач с низким приоритетом"},
        {"id": "medium_priority", "name": "Средний приоритет", "description": "Очередь для задач со средним приоритетом"},
        {"id": "high_priority", "name": "Высокий приоритет", "description": "Очередь для задач с высоким приоритетом"}
    ]
    return queues

@app.get("/api/health")
async def health_check_api():
    """Проверка здоровья системы"""
    try:
        with get_db_session() as session:
            # Проверяем подключение к БД
            session.execute(text("SELECT 1"))
            
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

@app.get("/api/stats")
async def get_system_stats_api ():
    """Получить статистику системы"""
    with get_db_session() as session:
        total_projects = session.query(Project).count()
        
        # Более точный подсчет завершенных проектов
        # Проект считается завершенным, если завершен этап video_generation
        completed_projects = session.query(Project).join(Stage).filter(
            Stage.name == "video_generation", 
            Stage.completed == True
        ).count()
        
        # Проекты в процессе (есть хотя бы один начатый этап)
        in_progress_projects = session.query(Project).join(Stage).filter(
            Stage.started_at.isnot(None)
        ).distinct().count()
        
        # Проекты с ошибками (есть хотя бы один этап с ошибкой)
        failed_projects = session.query(Project).join(Stage).filter(
            Stage.error_message.isnot(None)
        ).distinct().count()
        
        # Детальная статистика по этапам
        stages_stats = session.query(Stage.name, Stage.completed, Stage.error_message).all()
        stages_summary = {}
        for stage_name, completed, error_message in stages_stats:
            if stage_name not in stages_summary:
                stages_summary[stage_name] = {"total": 0, "completed": 0, "failed": 0, "in_progress": 0}
            stages_summary[stage_name]["total"] += 1
            if completed:
                stages_summary[stage_name]["completed"] += 1
            elif error_message:
                stages_summary[stage_name]["failed"] += 1
            else:
                stages_summary[stage_name]["in_progress"] += 1
        
        # Статистика по форматам видео
        format_stats = session.query(Project.video_format).all()
        format_summary = {}
        for (video_format,) in format_stats:
            format_summary[video_format] = format_summary.get(video_format, 0) + 1
        
        # Преобразуем stages_summary в массив для фронтенда
        stages_array = []
        for stage_name, stats in stages_summary.items():
            stages_array.append({
                "name": stage_name,
                "total": stats["total"],
                "completed": stats["completed"],
                "failed": stats["failed"],
                "in_progress": stats["in_progress"]
            })
        
        return {
            "projects": {
                "total": total_projects,
                "completed": completed_projects,
                "in_progress": in_progress_projects,
                "failed": failed_projects,
                "pending": total_projects - completed_projects - in_progress_projects - failed_projects
            },
            "stages": stages_array,
            "video_formats": format_summary,
            "completion_rate": round((completed_projects / total_projects * 100), 1) if total_projects > 0 else 0
        }

# ===== ЗАГРУЗКА ФАЙЛОВ =====

@app.post("/upload_thumbnail")
async def upload_thumbnail(
    topic: str = Form(...),
    chapters: int = Form(...),
    channel_id: str = Form(...),
    thumbnail: UploadFile = File(None)
):
    """Загрузить превью и создать проект"""
    thumb_path = None
    if thumbnail:
        ext = Path(thumbnail.filename).suffix or ".jpg"
        fname = f"{uuid.uuid4().hex}{ext}"
        out_path = THUMB_TMP / fname
        with out_path.open("wb") as f:
            shutil.copyfileobj(thumbnail.file, f)
        thumb_path = str(out_path)
    
    # Создаем проект в БД
    with get_db_session() as session:
        project = Project(
            topic=topic,
            chapters=chapters,
            channel_id=channel_id,
            video_format="long",
            thumbnail_path=thumb_path
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        
        return {"status": "ok", "project_id": project.id, "thumbnail_path": thumb_path}

@app.get("/api/logs/")
async def get_logs():
    """Получить содержимое всех логов"""
    log_files = glob.glob(str(LOGS_DIR / "*.log"))
    if not log_files:
        raise HTTPException(status_code=404, detail="Логи не найдены")

    logs_content = {}
    for log_file in log_files:
        with open(log_file, 'r', encoding='utf-8') as file:
            logs_content[Path(log_file).name] = file.read()
    print(logs_content)
    return logs_content

@app.post("/api/projects/{project_id}/stages/{stage_name}/pause")
async def pause_stage(project_id: int, stage_name: str):
    """Поставить этап на паузу"""
    with get_db_session() as session:
        stage = session.query(Stage).filter_by(project_id=project_id, name=stage_name).first()
        if not stage:
            raise HTTPException(status_code=404, detail="Этап не найден")
        
        if stage.completed:
            raise HTTPException(status_code=400, detail="Этап уже завершен и не может быть поставлен на паузу")
        
        stage.paused = True
        session.commit()
        
        return {"status": "ok", "stage": stage_name, "action": "paused"}

@app.post("/api/projects/{project_id}/stages/{stage_name}/resume")
async def resume_stage(project_id: int, stage_name: str):
    """Снять этап с паузы"""
    with get_db_session() as session:
        stage = session.query(Stage).filter_by(project_id=project_id, name=stage_name).first()
        if not stage:
            raise HTTPException(status_code=404, detail="Этап не найден")
        
        if stage.completed:
            raise HTTPException(status_code=400, detail="Этап уже завершен и не может быть возобновлен")
        
        stage.paused = False
        session.commit()
        
        return {"status": "ok", "stage": stage_name, "action": "resumed"}

@app.get("/api/projects/{project_id}/stages/{stage_name}/files")
async def get_stage_files_api(project_id: int, stage_name: str):
    """Получить список файлов, доступных для скачивания с этапа"""
    # Проверяем, существует ли проект
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    
    # Получаем информацию о файлах этапа
    stage_info = get_stage_files(project_id, stage_name)
    
    if not stage_info["files"]:
        raise HTTPException(status_code=404, detail=f"Файлы для этапа '{stage_name}' не найдены")
    
    # Проверяем существование файлов и добавляем информацию о размере
    available_files = []
    for file_info in stage_info["files"]:
        file_path = file_info["path"]
        
        if file_info.get("is_directory", False):
            # Для директорий проверяем, что директория существует и содержит файлы
            if file_path.exists() and any(file_path.iterdir()):
                available_files.append({
                    **file_info,
                    "exists": True,
                    "size": None  # Размер ZIP будет вычислен при создании
                })
        else:
            # Для файлов проверяем существование и размер
            if file_path.exists():
                available_files.append({
                    **file_info,
                    "exists": True,
                    "size": file_path.stat().st_size
                })
    
    if not available_files:
        raise HTTPException(status_code=404, detail=f"Файлы для этапа '{stage_name}' не найдены или пусты")
    
    return {
        "project_id": project_id,
        "stage_name": stage_name,
        "files": available_files
    }

@app.get("/api/projects/{project_id}/stages/{stage_name}/download")
async def download_stage_file(project_id: int, stage_name: str, file_type: Optional[str] = None):
    """Скачать файл с этапа"""
    # Проверяем, существует ли проект
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    
    # Получаем информацию о файлах этапа
    stage_info = get_stage_files(project_id, stage_name)
    
    if not stage_info["files"]:
        raise HTTPException(status_code=404, detail=f"Файлы для этапа '{stage_name}' не найдены")
    
    # Определяем, какой файл скачивать
    target_file = None
    if file_type and len(stage_info["files"]) > 1:
        # Если указан тип файла и есть несколько файлов, ищем по имени
        for file_info in stage_info["files"]:
            if file_info["name"] == file_type or file_info["name"].startswith(file_type):
                target_file = file_info
                break
        if not target_file:
            raise HTTPException(status_code=400, detail=f"Файл типа '{file_type}' не найден для этапа '{stage_name}'")
    else:
        # Берем первый доступный файл
        target_file = stage_info["files"][0]
    
    file_path = target_file["path"]
    
    # Проверяем существование файла
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Файл '{target_file['name']}' не найден")
    
    # Если это директория, создаем ZIP архив
    if target_file.get("is_directory", False):
        try:
            zip_path = create_zip_from_directory(file_path, f"{stage_name}_{project_id}")
            return FileResponse(
                path=zip_path,
                filename=f"{stage_name}_{project_id}.zip",
                media_type="application/zip"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка при создании ZIP архива: {str(e)}")
    else:
        # Возвращаем обычный файл
        return FileResponse(
            path=file_path,
            filename=target_file["name"],
            media_type=target_file["mime_type"]
        )

@app.get("/api/projects/{project_id}/download-all")
async def download_all_project_files(project_id: int):
    """Скачать все файлы проекта в одном ZIP архиве"""
    # Проверяем, существует ли проект
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    
    try:
        import zipfile
        import tempfile
        
        temp_dir = Path(tempfile.gettempdir())
        zip_path = temp_dir / f"project_{project_id}_files_{uuid.uuid4().hex}.zip"
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Добавляем файлы всех этапов
            stages = ["script", "metadata", "chunks", "prompts", "images", "thumbnail", "voiceover", "video"]
            
            for stage_name in stages:
                stage_info = get_stage_files(project_id, stage_name)
                
                for file_info in stage_info["files"]:
                    file_path = file_info["path"]
                    
                    if file_path.exists():
                        if file_info.get("is_directory", False):
                            # Для директорий добавляем все файлы с префиксом этапа
                            for sub_file in file_path.rglob('*'):
                                if sub_file.is_file():
                                    arcname = f"{stage_name}/{sub_file.relative_to(file_path)}"
                                    zipf.write(sub_file, arcname)
                        else:
                            # Для файлов добавляем с префиксом этапа
                            arcname = f"{stage_name}/{file_info['name']}"
                            zipf.write(file_path, arcname)
        
        return FileResponse(
            path=zip_path,
            filename=f"project_{project_id}_all_files.zip",
            media_type="application/zip"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при создании архива: {str(e)}")

@app.post("/api/projects/{project_id}/stages/restart")
async def restart_stage(project_id: int, request: RestartStageRequest):
    """Перезапустить конкретный этап проекта"""
    stage_name = request.stage_name
    
    # Проверяем, существует ли проект
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    
    # Проверяем, существует ли этап
    with get_db_session() as session:
        stage = session.query(Stage).filter_by(project_id=project_id, name=stage_name).first()
        if not stage:
            raise HTTPException(status_code=404, detail=f"Этап '{stage_name}' не найден для проекта {project_id}")
    
    # Сбрасываем статус этапа
    update_stage(project_id, stage_name, completed=False, error_message=None)
    
    # Определяем, какую задачу запускать в зависимости от названия этапа
    task_mapping = {
        "script": generate_script,
        "metadata": generate_metadata,
        "chunks": generate_chunks,
        "prompts": generate_prompts,
        "images": generate_images,
        "voiceover": generate_voiceover,
        "video": generate_video,
        "send_to_cdn": send_to_cdn,
        "thumbnail": generate_thumbnail
    }
    
    if stage_name not in task_mapping:
        raise HTTPException(status_code=400, detail=f"Неизвестный этап: {stage_name}")
    
    # Запускаем соответствующую задачу
    task = task_mapping[stage_name]
    
    try:
        if stage_name == "script":
            task.delay(project_id, project.topic, project.chapters, project.video_format)
        elif stage_name == "voiceover":
            task.delay(project_id, specific_chunk_id=None, merge_audio=True)
        elif stage_name == "images":
            task.delay(project_id, project.video_format)
        elif stage_name == "video":
            task.delay(project_id, project.video_format)
        elif stage_name == "thumbnail":
            task.delay(project_id, project.video_format)
        elif stage_name == "send_to_cdn":
            task.delay(project_id)
        else:
            task.delay(project_id)
        
        return {
            "status": "ok", 
            "message": f"Этап '{stage_name}' перезапущен",
            "project_id": project_id,
            "stage_name": stage_name
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при перезапуске этапа: {str(e)}")

@app.get("/api/ltx")
async def get_pod_id():
    pod_id = os.getenv("RUNPOD_LTX_ID")
    if not pod_id:
        raise HTTPException(status_code=404, detail="RUNPOD_LTX_ID не найден в .env")
    return {"RUNPOD_LTX_ID": pod_id}

dist_dir = Path(__file__).parent.parent / "frontend" / "dist"

app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

@app.get("/{full_path:path}")
async def frontend_fallback(request: Request, full_path: str):
    if full_path.startswith("api") or full_path.startswith("assets") or '.' in full_path:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(dist_dir / "index.html")

if __name__ == "__main__":
    create_database()
    uvicorn.run(app, host="0.0.0.0", port=3000) 
