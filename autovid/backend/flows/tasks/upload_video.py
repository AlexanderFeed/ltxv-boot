from autovid.backend.flows.config.celery_app import app
from autovid.backend.flows.steps.upload_video import ProjectUploader
from autovid.backend.flows.utils.logging import with_stage_logging

@app.task(queue="upload_video")
@with_stage_logging("upload_video")
def upload_video(project_id: int):
    try:
        result = ProjectUploader(project_id).upload_project()
        return result
    except Exception as e:
        print(f"❌ Ошибка при загрузке видео на YouTube: {e}")
        raise