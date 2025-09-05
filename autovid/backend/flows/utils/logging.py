from functools import wraps
from datetime import datetime
from autovid.backend.models.db import get_session, Stage


def log_stage(project_id: int, name: str, status: str, error: str = None):
    """Логирует этап выполнения в базу данных"""
    now = datetime.utcnow()
    with get_session() as session:
        stage = session.query(Stage).filter_by(project_id=project_id, name=name).first()
        if not stage:
            stage = Stage(project_id=project_id, name=name)
            session.add(stage)

        if status == "started":
            # При старте этапа очищаем предыдущую ошибку и сбрасываем финальные метки
            stage.started_at = now
            stage.completed = False
            stage.completed_at = None
            stage.duration_seconds = None
            stage.error_message = None
        elif status == "finished":
            stage.completed = True
            stage.completed_at = now
            if stage.started_at:
                stage.duration_seconds = (now - stage.started_at).total_seconds()
        elif status == "failed":
            stage.error_message = error
            stage.completed = False
            stage.completed_at = now

        session.commit()


def with_stage_logging(stage_name: str):
    """Декоратор для автоматического логирования этапов выполнения task"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Предполагаем, что project_id всегда первый аргумент после self
            project_id = args[0] if args else kwargs.get('project_id')
            
            if not project_id:
                raise ValueError("project_id должен быть передан как первый аргумент")
            
            try:
                # Логируем начало этапа
                log_stage(project_id, stage_name, "started")
                
                # Выполняем функцию
                result = func(*args, **kwargs)
                
                # Логируем успешное завершение
                log_stage(project_id, stage_name, "finished")
                
                return result
                
            except Exception as e:
                # Логируем ошибку
                error_msg = str(e)
                log_stage(project_id, stage_name, "failed", error_msg)
                raise
                
        return wrapper
    return decorator