import json
import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydub import AudioSegment
from autovid.backend.flows.config.celery_app import app
    
from autovid.backend.flows.steps.voiceover import VoiceoverManager
from autovid.backend.flows.utils.logging import with_stage_logging

class AudioFileManager:
    """Класс для управления аудио файлами"""
    
    def __init__(self, project_id: int, chunks_path: Path):
        self.project_id = project_id
        self.chunks_path = chunks_path   
    
    def load_chunks(self) -> List[Dict[str, Any]]:
        """Загружает чанки из файла"""
        if not self.chunks_path.exists():
            raise FileNotFoundError(f"Файл чанков не найден: {self.chunks_path}")
        
        with open(self.chunks_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def merge_audio_files(self, audio_dir: Path, output_filename: str = "merged_output.mp3") -> str:
        """Объединяет все аудиофайлы в один файл"""
        if not audio_dir.exists():
            raise FileNotFoundError(f"Папка с аудиофайлами не найдена: {audio_dir}")
        
        # Функция для извлечения номера из имени файла
        def extract_number(filename):
            match = re.search(r"(\d+)", filename)
            return int(match.group(1)) if match else -1
        
        # Получаем и сортируем файлы по номеру
        files = sorted(
            [f for f in os.listdir(audio_dir) if f.endswith(".mp3")],
            key=extract_number
        )
        
        if not files:
            raise FileNotFoundError(f"Аудиофайлы не найдены в папке: {audio_dir}")
        
        # Объединение
        combined = AudioSegment.empty()
        for filename in files:
            file_path = audio_dir / filename
            audio = AudioSegment.from_file(str(file_path))
            combined += audio
        
        # Сохраняем объединенный файл
        output_path = audio_dir / output_filename
        combined.export(str(output_path), format="mp3", bitrate="192k")
        
        print(f"✅ Объединено {len(files)} файлов в {output_path}")
        return str(output_path)

@app.task(queue="autovid_voiceover")
@with_stage_logging("voiceover")
def generate_voiceover(project_id: int, specific_chunk_id: Optional[int] = None, merge_audio: bool = True):
    try:
        assets_dir = Path(os.getenv("ASSETS_DIR", "assets"))
        chunks_path = assets_dir / "chunks" / str(project_id) / "chunks.json"
        audio_dir = assets_dir / "audio" / str(project_id)
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        audio_manager = AudioFileManager(project_id, chunks_path)
        chunks = audio_manager.load_chunks()

        audio_files = VoiceoverManager(project_id, chunks, audio_dir).generate_all_voiceovers(specific_chunk_id)
        
        # Объединяем аудиофайлы в один, если это требуется
        merged_file_path = None
        if merge_audio and audio_files:
            try:
                merged_file_path = audio_manager.merge_audio_files(audio_dir)
                print(f"🎵 Аудиофайлы объединены: {merged_file_path}")
            except Exception as merge_error:
                print(f"⚠️ Ошибка при объединении аудиофайлов: {merge_error}")
        
        return audio_files
        
    except Exception as e:
        print(f"❌ Ошибка при генерации озвучки: {e}")
        raise