from pathlib import Path
import os
from autovid.backend.flows.config.celery_app import app

from autovid.backend.flows.steps.script import ScriptGenerator, ShortsScriptGenerator
from autovid.backend.flows.utils.logging import with_stage_logging

class SaveResult:
    def __init__(self, project_id: int, topic: str, chapters: int, video_format: str = "long"):
        self.project_id = project_id
        self.topic = topic
        self.chapters = chapters
        self.video_format = video_format
        
    def save_script(self, script: str, script_file: Path) -> None:
        """Сохраняет сценарий в файл"""
        script_file.parent.mkdir(parents=True, exist_ok=True)
        script_file.write_text(script, encoding="utf-8")

@app.task(queue="script")
@with_stage_logging("script")
def generate_script(project_id: int, topic: str, chapters: int, video_format: str = "long"):
    try:
        assets_dir = Path(os.getenv("ASSETS_DIR", "assets"))
        script_path = assets_dir / "scripts" / str(project_id) / "script.txt"

        if video_format == "shorts":
            script_content = ShortsScriptGenerator().generate(topic=topic, script_file=script_path)
        else:
            script_content = ScriptGenerator().generate(topic=topic, num_chapters=chapters, script_file=script_path)

        SaveResult(project_id, topic, chapters, video_format).save_script(script_content, script_path)
        
        return script_content
    except Exception as e:
        print(f"❌ Ошибка при генерации сценария: {e}")
        raise
