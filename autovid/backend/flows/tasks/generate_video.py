from autovid.backend.flows.config.celery_app import app
from autovid.backend.flows.utils.logging import with_stage_logging
import subprocess
import os
from pathlib import Path
try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

@app.task(queue="video")
@with_stage_logging("video")
def generate_video(project_id: int, video_format: str = "long"):
    try:
        # Готовим детерминированное окружение для сабпроцесса
        env = os.environ.copy()
        # Пробуем подгрузить переменные из правильного .env, если не заданы в окружении
        if (not env.get("RUNPOD_LTX_ID") or env.get("RUNPOD_LTX_ID") == "unknown") and load_dotenv is not None:
            # autovid/.env — источник истины
            env_path = Path(__file__).resolve().parents[4] / "autovid" / ".env"
            if env_path.exists():
                load_dotenv(env_path)
                env["RUNPOD_LTX_ID"] = os.getenv("RUNPOD_LTX_ID", env.get("RUNPOD_LTX_ID", "unknown"))
        # Всегда обеспечиваем корректный ASSETS_DIR по умолчанию
        env.setdefault("ASSETS_DIR", "/workspace/auto_vid/assets")

        subprocess.run(
            ["python3", "-m", "autovid.backend.flows.steps.animate_scene", str(project_id), video_format],
            check=True,
            env=env
        )
    except Exception as e:
        print(f"❌ Ошибка при генерации видео: {e}")
        raise