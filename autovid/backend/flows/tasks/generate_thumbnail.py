from autovid.backend.flows.config.celery_app import app
from autovid.backend.flows.steps.thumbnail import ThumbnailManager
from autovid.backend.flows.utils.logging import with_stage_logging
import asyncio

@app.task(queue="thumbnails")
@with_stage_logging("thumbnail")
def generate_thumbnail(project_id: int, video_format: str = "long"):
    try:
        # Создаем event loop для асинхронного вызова
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                ThumbnailManager().generate_thumbnail(project_id, video_format)
            )
            return result
        finally:
            loop.close()
            
    except Exception as e:
        print(f"❌ Ошибка при генерации превью: {e}")
        return False