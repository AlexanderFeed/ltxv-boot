"""
ltx_video_animate.py
-------------------
Модуль для анимации сцен через LTX-Video API.
Отправляет готовые сцены на внешний сервер для image-to-video анимации.
"""
import time
import json
import requests
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from mutagen.mp3 import MP3
import os

from autovid.backend.config import LTX_VIDEO_CONFIG, VIDEO_FORMATS

# Базовая директория ассетов (из окружения), по умолчанию "assets"
ASSETS_DIR = Path(os.getenv("ASSETS_DIR", "assets"))


@dataclass
class ScenePart:
    """Часть сцены для анимации"""
    scene_id: int
    part_index: int
    start_time: float
    duration: float
    image_path: Path
    output_path: Path
    prompt: str
    seed: int


@dataclass
class LTXVideoRequest:
    """Запрос к LTX-Video API"""
    scene_id: str
    image_path: Path
    task_id: Optional[str] = None
    status: str = "pending"  # pending, started, success, failure
    result_path: Optional[str] = None
    retry_count: int = 0


class PromptManager:
    """Класс для работы с промптами изображений"""
    
    def __init__(self, project_id: int):
        self.project_id = project_id
        self.prompts_file = ASSETS_DIR / "prompts" / str(project_id) / "image_prompts.json"
        self.prompts_cache = None
    
    def load_prompts(self) -> Dict[int, str]:
        """Загружает промпты из файла и возвращает словарь {scene_id: prompt}"""
        if self.prompts_cache is not None:
            return self.prompts_cache
        
        try:
            if not self.prompts_file.exists():
                print(f"❌ Файл промптов не найден: {self.prompts_file}")
                return {}
            
            with open(self.prompts_file, 'r', encoding='utf-8') as f:
                prompts_data = json.load(f)
            
            # Преобразуем в словарь {scene_id: prompt}
            prompts_dict = {}
            for item in prompts_data:
                if isinstance(item, dict) and "id" in item and "image_prompt" in item:
                    prompts_dict[item["id"]] = item["image_prompt"]
            
            self.prompts_cache = prompts_dict
            print(f"✅ Загружено {len(prompts_dict)} промптов")
            return prompts_dict
            
        except Exception as e:
            print(f"❌ Ошибка загрузки промптов: {e}")
            return {}
    
    def get_scene_prompt(self, scene_id: int) -> str:
        """Возвращает промпт для конкретной сцены"""
        prompts = self.load_prompts()
        
        if LTX_VIDEO_CONFIG["prompt_settings"]["use_original_prompts"]:
            original_prompt = prompts.get(scene_id, "")
            if original_prompt and not original_prompt.startswith("[ERROR]"):
                # Добавляем суффикс для анимации
                animation_suffix = LTX_VIDEO_CONFIG["prompt_settings"]["animation_style_suffix"]
                return f"{original_prompt}{animation_suffix}"
        
        # Используем универсальный промпт
        return LTX_VIDEO_CONFIG["prompt_settings"]["universal_prompt"]


class SceneDurationAnalyzer:
    """Класс для анализа длительности сцен"""
    
    def __init__(self, project_id: int):
        self.project_id = project_id
        self.audio_dir = ASSETS_DIR / "audio" / str(project_id)
    
    def get_scene_duration(self, scene_id: int) -> float:
        """Возвращает длительность сцены в секундах"""
        # Пробуем разные форматы номера сцены
        scene_formats = [
            str(scene_id).zfill(2),  # 01, 02, 03...
            str(scene_id).zfill(3),  # 001, 002, 003...
            str(scene_id)             # 1, 2, 3...
        ]
        
        for scene_format in scene_formats:
            audio_path = self.audio_dir / f"scene_{scene_format}.mp3"
            if audio_path.exists():
                try:
                    audio = MP3(audio_path)
                    duration = audio.info.length
                    print(f"📊 Сцена {scene_id}: длительность {duration:.2f}с")
                    return duration
                except Exception as e:
                    print(f"❌ Ошибка получения длительности для сцены {scene_id}: {e}")
                    return 0.0
        
        print(f"❌ Аудио файл не найден для сцены {scene_id}")
        return 0.0
    
    def should_split_scene(self, scene_id: int) -> bool:
        """Проверяет, нужно ли разбивать сцену на части"""
        duration = self.get_scene_duration(scene_id)
        threshold = LTX_VIDEO_CONFIG["duration_settings"]["scene_split_threshold"]
        return duration > threshold
    
    def calculate_scene_parts(self, scene_id: int) -> List[Tuple[float, float]]:
        """Возвращает список (start_time, duration) для частей сцены"""
        total_duration = self.get_scene_duration(scene_id)
        if total_duration <= 0:
            return []
        
        target_duration = LTX_VIDEO_CONFIG["duration_settings"]["target_animation_duration"]
        max_duration = LTX_VIDEO_CONFIG["duration_settings"]["max_animation_duration"]
        overlap = LTX_VIDEO_CONFIG["duration_settings"]["overlap_duration"]
        
        # Если сцена короткая, анимируем целиком
        if total_duration <= max_duration:
            return [(0.0, total_duration)]
        
        # Разбиваем на части
        parts = []
        current_start = 0.0
        
        while current_start < total_duration:
            # Определяем длительность части
            remaining = total_duration - current_start
            part_duration = min(target_duration, remaining)
            
            # Если остается мало времени, объединяем с последней частью
            if remaining - part_duration < target_duration * 0.5:
                part_duration = remaining
            
            parts.append((current_start, part_duration))
            
            # Если это последняя часть, прерываем
            if current_start + part_duration >= total_duration:
                break
            
            # Переходим к следующей части с учетом перекрытия
            current_start += part_duration - overlap
        
        print(f"🔄 Сцена {scene_id} ({total_duration:.1f}с) разбита на {len(parts)} частей:")
        for i, (start, duration) in enumerate(parts):
            print(f"  Часть {i}: {start:.1f}s - {start + duration:.1f}s (длительность: {duration:.1f}s)")
        return parts


class AdditionalImageGenerator:
    """Класс для генерации дополнительных изображений для частей сцены"""
    
    def __init__(self, project_id: int, video_format: str):
        self.project_id = project_id
        self.video_format = video_format
        self.scenes_dir = ASSETS_DIR / "scenes" / str(project_id)
        
    def generate_part_image(self, scene_id: int, part_index: int, prompt: str) -> Optional[Path]:
        """Генерирует изображение для части сцены с уникальным seed"""
        try:
            # Импортируем Flux генератор
            from autovid.backend.flows.steps.flux_image_gen import ImageGenerator
            
            # Создаем уникальный seed для части
            base_seed = LTX_VIDEO_CONFIG["video_params"]["seed"]
            if LTX_VIDEO_CONFIG["prompt_settings"]["vary_seeds_for_parts"]:
                part_seed = base_seed + (scene_id * 1000) + (part_index * 100)
            else:
                part_seed = base_seed
            
            # Находим правильный формат номера сцены (как в get_or_create_part_image)
            scene_formats = [
                str(scene_id).zfill(2),  # 01, 02, 03...
                str(scene_id).zfill(3),  # 001, 002, 003...
                str(scene_id)             # 1, 2, 3...
            ]
            
            scene_format = None
            for fmt in scene_formats:
                test_image = self.scenes_dir / f"scene_{fmt}.jpg"
                if test_image.exists():
                    scene_format = fmt
                    break
            
            if not scene_format:
                print(f"❌ Не найден правильный формат номера для сцены {scene_id}")
                return None
            
            # Путь для сохранения изображения части (используем тот же формат)
            part_filename = f"scene_{scene_format}_part_{part_index:02d}.jpg"
            output_path = self.scenes_dir / part_filename
            
            print(f"🎨 Генерирую изображение для сцены {scene_id}, часть {part_index} (seed: {part_seed})")
            print(f"📁 Сохраняю в: {output_path}")
            
            # Генерируем изображение через Flux (используем правильный метод)
            image_generator = ImageGenerator()
            result_path = image_generator.generate_single_image(
                prompt=prompt,
                filename=str(output_path),
                video_format=self.video_format,
                priority="high"
            )
            
            if result_path and result_path.exists():
                print(f"✅ Изображение части создано: {result_path}")
                return result_path
            else:
                print(f"❌ Не удалось создать изображение для части {part_index} сцены {scene_id}")
                if output_path.exists():
                    print(f"📁 Файл существует, но размер: {output_path.stat().st_size} байт")
                    if output_path.stat().st_size == 0:
                        print(f"⚠️ Файл пустой - возможно Flux API вернул ошибку")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка генерации изображения для части: {e}")
            import traceback
            print(f"🔍 Подробности ошибки: {traceback.format_exc()}")
            return None
    
    def get_or_create_part_image(self, scene_id: int, part_index: int, prompt: str) -> Optional[Path]:
        """Возвращает существующее изображение части или создает новое"""
        # Пробуем разные форматы номера сцены
        scene_formats = [
            str(scene_id).zfill(2),  # 01, 02, 03...
            str(scene_id).zfill(3),  # 001, 002, 003...
            str(scene_id)             # 1, 2, 3...
        ]
        
        if part_index == 0:
            # Для первой части используем оригинальное изображение
            for scene_format in scene_formats:
                original_image = self.scenes_dir / f"scene_{scene_format}.jpg"
                if original_image.exists():
                    return original_image
        
        # Для остальных частей создаем новые изображения
        # Используем тот же формат что и для оригинального изображения
        for scene_format in scene_formats:
            original_image = self.scenes_dir / f"scene_{scene_format}.jpg"
            if original_image.exists():
                part_image = self.scenes_dir / f"scene_{scene_format}_part_{part_index:02d}.jpg"
                
                if part_image.exists():
                    print(f"📁 Используем существующее изображение части: {part_image}")
                    return part_image
                
                generated = self.generate_part_image(scene_id, part_index, prompt)
                if generated is not None:
                    return generated
                # Fallback: если не удалось сгенерировать изображение части — используем оригинал
                print(
                    f"⚠️ Fallback на оригинал: flux не сгенерировал scene_{scene_format}_part_{part_index:02d}.jpg; "
                    f"используем {original_image.name}"
                )
                return original_image
        
        return None


class ScenePartManager:
    """Класс для управления частями сцен"""
    
    def __init__(self, project_id: int, video_format: str):
        self.project_id = project_id
        self.video_format = video_format
        self.duration_analyzer = SceneDurationAnalyzer(project_id)
        self.prompt_manager = PromptManager(project_id)
        self.image_generator = AdditionalImageGenerator(project_id, video_format)
        self.output_dir = ASSETS_DIR / "video" / str(project_id)
    
    def create_scene_parts(self, scene_id: int) -> List[ScenePart]:
        """Создает список частей для анимации сцены"""
        parts_info = self.duration_analyzer.calculate_scene_parts(scene_id)
        if not parts_info:
            print(f"⚠️ Сцена {scene_id}: нет информации о частях")
            return []
        
        print(f"🔍 Сцена {scene_id}: создаем {len(parts_info)} частей:")
        for i, (start, duration) in enumerate(parts_info):
            print(f"  Часть {i}: {start:.1f}s - {start + duration:.1f}s (длительность: {duration:.1f}s)")
        
        prompt = self.prompt_manager.get_scene_prompt(scene_id)
        parts = []
        
        # Находим правильный формат номера сцены
        scene_formats = [
            str(scene_id).zfill(2),  # 01, 02, 03...
            str(scene_id).zfill(3),  # 001, 002, 003...
            str(scene_id)             # 1, 2, 3...
        ]
        
        scene_format = None
        for fmt in scene_formats:
            test_image = self.image_generator.scenes_dir / f"scene_{fmt}.jpg"
            if test_image.exists():
                scene_format = fmt
                break
        
        if not scene_format:
            print(f"❌ Не найден правильный формат номера для сцены {scene_id}")
            return []
        
        print(f"📸 Формат номера сцены {scene_id}: {scene_format}")
        
        for part_index, (start_time, duration) in enumerate(parts_info):
            print(f"🎬 Обрабатываем часть {part_index} сцены {scene_id}...")
            
            # Получаем или создаем изображение для части
            image_path = self.image_generator.get_or_create_part_image(scene_id, part_index, prompt)
            if not image_path:
                print(f"❌ Часть {part_index} сцены {scene_id}: не удалось получить изображение")
                continue
            
            # Путь для сохранения анимированной части
            scene_num_padded = str(scene_id).zfill(3)
            output_filename = f"scene_{scene_num_padded}_part_{part_index:02d}_animated.mp4"
            output_path = self.output_dir / output_filename
            
            # Создаем уникальный seed для части
            base_seed = LTX_VIDEO_CONFIG["video_params"]["seed"]
            part_seed = base_seed + (scene_id * 1000) + (part_index * 100)
            
            part = ScenePart(
                scene_id=scene_id,
                part_index=part_index,
                start_time=start_time,
                duration=duration,
                image_path=image_path,
                output_path=output_path,
                prompt=prompt,
                seed=part_seed
            )
            parts.append(part)
            print(f"✅ Часть {part_index} сцены {scene_id} создана: {output_filename}")
        
        print(f"📋 Создано {len(parts)} частей для сцены {scene_id}")
        return parts
    
    def merge_scene_parts(self, scene_id: int, parts: List[ScenePart]) -> bool:
        """Склеивает анимированные части в финальную сцену"""
        if not parts:
            return False
        
        try:
            # Единый финальный LTX-результат: scene_XXX_animated.mp4 (не перезаписывает базовый клип)
            scene_num_padded = str(scene_id).zfill(3)
            final_output = self.output_dir / f"scene_{scene_num_padded}_animated.mp4"
            
            if len(parts) == 1:
                # Если только одна часть, просто переименовываем
                parts[0].output_path.rename(final_output)
                print(f"✅ Сцена {scene_id}: одна часть перемещена в {final_output}")
                # Подмешиваем оригинальный звук
                self._mux_audio_into_video(final_output, scene_id)
                
                # Единая нормализация: FPS + целевое разрешение проекта
                print(f"🔄 Нормализуем сцену {scene_id} к целевому FPS/разрешению...")
                from autovid.backend.config import VIDEO_FORMATS
                target = VIDEO_FORMATS.get(self.video_format, VIDEO_FORMATS["long"])
                temp_normalized = final_output.with_suffix('.normalized.mp4')
                if normalize_video_to_target(final_output, temp_normalized, target["WIDTH"], target["HEIGHT"], target.get("FPS", 25)):
                    final_output.unlink()
                    temp_normalized.rename(final_output)
                    print(f"✅ Сцена {scene_id} нормализована: {final_output}")
                else:
                    print(f"⚠️ Сцена {scene_id} не была нормализована")
                
                return True
            
            # Создаем временный файл списка для ffmpeg
            concat_file = self.output_dir / f"concat_scene_{scene_num_padded}.txt"
            
            with open(concat_file, 'w', encoding='utf-8') as f:
                for part in sorted(parts, key=lambda p: p.part_index):
                    if part.output_path.exists():
                        f.write(f"file '{part.output_path.absolute()}'\n")
            
            # Склеиваем части через ffmpeg
            cmd = [
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', str(concat_file),
                '-c', 'copy',
                str(final_output)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✅ Сцена {scene_id}: {len(parts)} частей склеены в {final_output}")
                
                # Удаляем временные файлы
                concat_file.unlink(missing_ok=True)
                for part in parts:
                    part.output_path.unlink(missing_ok=True)
                
                # Подмешиваем оригинальный звук
                self._mux_audio_into_video(final_output, scene_id)
                
                # Единая нормализация: FPS + целевое разрешение проекта
                print(f"🔄 Нормализуем финальную сцену {scene_id} к целевому FPS/разрешению...")
                from autovid.backend.config import VIDEO_FORMATS
                target = VIDEO_FORMATS.get(self.video_format, VIDEO_FORMATS["long"])
                temp_normalized = final_output.with_suffix('.normalized.mp4')
                if normalize_video_to_target(final_output, temp_normalized, target["WIDTH"], target["HEIGHT"], target.get("FPS", 25)):
                    final_output.unlink()
                    temp_normalized.rename(final_output)
                    print(f"✅ Сцена {scene_id} нормализована: {final_output}")
                else:
                    print(f"⚠️ Сцена {scene_id} не была нормализована")
                
                return True
            else:
                print(f"❌ Ошибка склейки сцены {scene_id}: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка при склейке частей сцены {scene_id}: {e}")
            return False

    def _mux_audio_into_video(self, video_path: Path, scene_id: int) -> None:
        """Подмешивает оригинальную озвучку сцены в готовое LTX-видео (без перекодирования видео)."""
        try:
            # Ищем аудио в 3/2-значных форматах
            audio_dir = self.duration_analyzer.audio_dir
            audio_path = None
            for fmt in (str(scene_id).zfill(3), str(scene_id).zfill(2), str(scene_id)):
                candidate = audio_dir / f"scene_{fmt}.mp3"
                if candidate.exists():
                    audio_path = candidate
                    break
            if not audio_path:
                print(f"⚠️ Аудио для сцены {scene_id} не найдено, пропускаю микширование звука")
                return

            temp_with_audio = video_path.with_suffix(".with_audio.tmp.mp4")
            cmd = [
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-i', str(audio_path),
                '-map', '0:v:0', '-map', '1:a:0',
                '-c:v', 'copy', '-c:a', 'aac',
                '-shortest', str(temp_with_audio)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0 and temp_with_audio.exists():
                video_path.unlink(missing_ok=True)
                temp_with_audio.rename(video_path)
                print(f"🔊 Добавлен звук в сцену {scene_id}: {video_path}")
            else:
                print(f"❌ Ошибка микширования аудио для сцены {scene_id}: {res.stderr}")
        except Exception as e:
            print(f"❌ Исключение при микшировании аудио: {e}")


class SceneSelector:
    """Класс для выбора сцен для анимации"""
    
    @staticmethod
    def get_scenes_to_animate(project_id: int, video_format: str, total_scenes: int) -> List[int]:
        """Возвращает список номеров сцен для анимации"""
        config = LTX_VIDEO_CONFIG["scene_selection"]
        strategy = config["strategy"]
        
        if strategy == "first_n":
            count = config["count"]
            if video_format == "shorts":
                count = min(count, config["max_scenes_for_shorts"], total_scenes)
            else:
                count = min(count, total_scenes)
            return list(range(1, count + 1))
        
        elif strategy == "every_nth":
            step = config["step"]
            return [i for i in range(1, total_scenes + 1) if i % step == 0]
        
        elif strategy == "custom_list":
            custom_scenes = config["custom_scenes"]
            return [s for s in custom_scenes if s <= total_scenes]
        
        else:
            return []  # Неизвестная стратегия


class LTXVideoAPIClient:
    """Клиент для работы с LTX-Video API"""
    
    def __init__(self):
        # Берем актуальный RUNPOD_LTX_ID из окружения при создании клиента,
        # а не из статичной конфигурации, чтобы избежать рассинхронизации.
        ltx_id = os.getenv("RUNPOD_LTX_ID", "unknown")
        self.base_url = f"https://{ltx_id}-8000.proxy.runpod.net"
        self.timeout = LTX_VIDEO_CONFIG["timeout"]
        self.max_retries = LTX_VIDEO_CONFIG["max_retries"]
        try:
            print(f"🔧 LTX API: base_url={self.base_url} (RUNPOD_LTX_ID={ltx_id})")
        except Exception:
            pass
    
    def submit_video_request(self, image_path: Path, prompt: str, video_format: str, duration: float, seed: int = None) -> Optional[str]:
        """Отправляет запрос на создание видео и возвращает task_id"""
        format_config = VIDEO_FORMATS.get(video_format, VIDEO_FORMATS["long"])

        # Параметры вывода для LTX: переопределяем размеры только для LTX-запроса
        if video_format == "shorts":
            ltx_width, ltx_height = 720, 1280
        elif video_format == "long":
            ltx_width, ltx_height = 1280, 720
        else:
            ltx_width, ltx_height = format_config["WIDTH"], format_config["HEIGHT"]

        # Рассчитываем количество кадров на основе длительности
        fps = format_config.get("FPS", 25)
        # Точное количество кадров по длительности и FPS
        target_frames = max(1, round(duration * fps))
        
        try:
            with open(image_path, 'rb') as image_file:
                files = {'image': image_file}
                data = {
                    'prompt': prompt,
                    'negative_prompt': LTX_VIDEO_CONFIG["video_params"]["negative_prompt"],
                    'expected_width': ltx_width,
                    'expected_height': ltx_height,
                    'num_frames': target_frames,
                    'seed': seed or LTX_VIDEO_CONFIG["video_params"]["seed"]
                }
                
                response = requests.post(
                    f"{self.base_url}/generate",
                    files=files,
                    data=data,
                    timeout=self.timeout
                )
                response.raise_for_status()
                
                result = response.json()
                task_id = result.get("task_id")
                print(f"🎬 LTX-Video запрос отправлен: {task_id} (размер: {ltx_width}x{ltx_height}, кадров: {target_frames}, длительность: {duration:.1f}с)")
                return task_id
                
        except Exception as e:
            print(f"❌ Ошибка отправки LTX-Video запроса: {e}")
            return None
    
    def check_status(self, task_id: str) -> Tuple[str, Optional[str]]:
        """Проверяет статус задачи. Возвращает (status, result_path)"""
        try:
            response = requests.get(
                f"{self.base_url}/status/{task_id}",
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            status = result.get("status", "UNKNOWN")
            result_path = result.get("result") if status == "SUCCESS" else None
            
            return status, result_path
            
        except Exception as e:
            print(f"❌ Ошибка проверки статуса {task_id}: {e}")
            return "ERROR", None
    
    def download_video(self, result_path: str, output_path: Path) -> bool:
        """Скачивает готовое видео без постобработки (нормализация выполняется выше по уровню)."""
        try:
            # Построение корректного URL c учетом разных форматов result_path
            def build_url(base_url: str, rp: str) -> str:
                if rp.startswith("http://") or rp.startswith("https://"):
                    return rp
                path = rp.lstrip("/")
                if path.startswith("video/"):
                    return f"{base_url}/{path}"
                if path.startswith("task_results/"):
                    return f"{base_url}/video/{path}"
                # иначе считаем, что это просто имя файла
                return f"{base_url}/video/task_results/{path}"

            url = build_url(self.base_url, result_path)

            response = requests.get(url, stream=True, timeout=self.timeout)
            response.raise_for_status()
            
            # Сохраняем во временный файл, затем перемещаем
            temp_path = output_path.with_suffix('.tmp')
            with open(temp_path, 'wb') as f:
                shutil.copyfileobj(response.raw, f)
            
            # Атомарная замена файла
            temp_path.rename(output_path)
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка скачивания видео: {e}")
            return False


class LTXVideoManager:
    """Главный класс для управления image-to-video анимацией"""
    
    def __init__(self, project_id: int, video_format: str):
        self.project_id = project_id
        self.video_format = video_format
        self.api_client = LTXVideoAPIClient()
        self.part_manager = ScenePartManager(project_id, video_format)
        
        self.scenes_dir = ASSETS_DIR / "scenes" / str(project_id)
        self.video_dir = ASSETS_DIR / "video" / str(project_id)
        self.chunks_file = ASSETS_DIR / "chunks" / str(project_id) / "chunks.json"
        
        # Загружаем информацию о сценах
        with open(self.chunks_file, 'r', encoding='utf-8') as f:
            self.chunks = json.load(f)
        
        self.total_scenes = len(self.chunks)
        self.scenes_to_animate = SceneSelector.get_scenes_to_animate(
            project_id, video_format, self.total_scenes
        )
        
        print(f"🎯 LTX-Video: будет анимировано {len(self.scenes_to_animate)} сцен из {self.total_scenes}")
        print(f"📋 Сцены для анимации: {self.scenes_to_animate}")
    
    def should_animate_scene(self, scene_id: int) -> bool:
        """Проверяет, нужно ли анимировать данную сцену"""
        return scene_id in self.scenes_to_animate
    
    def find_scene_files(self, scene_id: int) -> Tuple[Optional[Path], Optional[Path]]:
        """Находит файлы изображения и видео для сцены.
        Учитывает варианты нумерации с 2 и 3 цифрами для согласованности с базовым рендером."""
        # Кандидаты форматов номера сцены
        scene_formats = [
            str(scene_id).zfill(2),  # 01, 02, 03...
            str(scene_id).zfill(3),  # 001, 002, 003...
            str(scene_id)             # 1, 2, 3...
        ]

        # Ищем изображение
        image_path: Optional[Path] = None
        discovered_format: Optional[str] = None
        for fmt in scene_formats:
            for ext in ["jpg", "jpeg", "png"]:
                potential_path = self.scenes_dir / f"scene_{fmt}.{ext}"
                if potential_path.exists():
                    image_path = potential_path
                    discovered_format = fmt
                    print(f"✅ Найдено изображение: {image_path}")
                    break
            if image_path:
                break

        # Ищем видео: пробуем оба варианта 2- и 3-значной нумерации
        video_path: Optional[Path] = None
        video_candidates: List[Path] = []

        if discovered_format:
            # Кандидат по формату изображения
            video_candidates.append(self.video_dir / f"scene_{discovered_format}.mp4")
            # Альтернативный формат той же сцены (2 <-> 3 цифры)
            if len(discovered_format) == 2:
                video_candidates.append(self.video_dir / f"scene_{str(scene_id).zfill(3)}.mp4")
            elif len(discovered_format) == 3:
                video_candidates.append(self.video_dir / f"scene_{str(scene_id).zfill(2)}.mp4")
        else:
            # Если не нашли изображение, попробуем оба основных формата видео
            video_candidates.extend([
                self.video_dir / f"scene_{str(scene_id).zfill(3)}.mp4",
                self.video_dir / f"scene_{str(scene_id).zfill(2)}.mp4",
            ])

        for candidate in video_candidates:
            if candidate.exists():
                video_path = candidate
                break

        return image_path, video_path
    
    def animate_scene_part(self, part: ScenePart) -> bool:
        """Анимирует одну часть сцены через LTX-Video API"""
        print(f"🎬 Анимируем часть {part.part_index} сцены {part.scene_id} ({part.duration:.1f}с)")
        
        # Отправляем запрос
        task_id = self.api_client.submit_video_request(
            part.image_path, 
            part.prompt, 
            self.video_format,
            part.duration,
            part.seed
        )
        
        if not task_id:
            return False
        
        # Ждем выполнения с polling
        polling_interval = LTX_VIDEO_CONFIG["polling_interval"]
        max_wait_time = 600  # 10 минут максимум
        elapsed = 0
        
        while elapsed < max_wait_time:
            time.sleep(polling_interval)
            elapsed += polling_interval
            
            status, result_path = self.api_client.check_status(task_id)
            print(f"📊 Часть {part.part_index} сцены {part.scene_id}: статус {status}")
            
            if status == "SUCCESS" and result_path:
                # Скачиваем анимированную часть
                success = self.api_client.download_video(result_path, part.output_path)
                if success:
                    print(f"✅ Часть {part.part_index} сцены {part.scene_id} успешно анимирована")
                    return True
                else:
                    print(f"❌ Не удалось скачать анимированную часть")
                    return False
                    
            elif status == "FAILURE":
                print(f"❌ LTX-Video ошибка для части {part.part_index} сцены {part.scene_id}")
                return False
        
        print(f"⏰ Таймаут ожидания для части {part.part_index} сцены {part.scene_id}")
        return False
    
    def animate_scene(self, scene_id: int) -> bool:
        """Анимирует сцену (возможно разбитую на части) через LTX-Video API"""
        print(f"🎬 Начинаем анимацию сцены {scene_id}")
        
        if not LTX_VIDEO_CONFIG["enabled"]:
            print(f"⏸️ LTX-Video отключен в конфигурации")
            return False
        
        if not self.should_animate_scene(scene_id):
            print(f"⏭️ Сцена {scene_id} не выбрана для анимации")
            return False
        
        image_path, video_path = self.find_scene_files(scene_id)
        
        if not image_path or not image_path.exists():
            print(f"❌ Изображение для сцены {scene_id} не найдено")
            return False
        
        if not video_path or not video_path.exists():
            print(f"⏳ Видео для сцены {scene_id} еще не готово")
            return False
        
        print(f"📁 Сцена {scene_id}: изображение {image_path.name}, видео {video_path.name}")
        
        # Создаем части сцены
        scene_parts = self.part_manager.create_scene_parts(scene_id)
        if not scene_parts:
            print(f"❌ Не удалось создать части для сцены {scene_id}")
            return False
        
        print(f"🎯 Сцена {scene_id}: будет анимировано {len(scene_parts)} частей")
        
        # Анимируем каждую часть
        animated_parts = []
        for part in scene_parts:
            print(f"🔄 Анимируем часть {part.part_index + 1}/{len(scene_parts)} сцены {scene_id}")
            success = self.animate_scene_part(part)
            if success:
                animated_parts.append(part)
                print(f"✅ Часть {part.part_index} сцены {scene_id} успешно анимирована")
            else:
                print(f"❌ Не удалось анимировать часть {part.part_index} сцены {scene_id}")
        
        print(f"📊 Сцена {scene_id}: анимировано {len(animated_parts)} из {len(scene_parts)} частей")
        
        # Если анимировали все части, склеиваем их
        if len(animated_parts) == len(scene_parts):
            print(f"🔗 Склеиваем {len(scene_parts)} частей сцены {scene_id}")
            success = self.part_manager.merge_scene_parts(scene_id, animated_parts)
            if success:
                print(f"✅ Сцена {scene_id} полностью анимирована ({len(scene_parts)} частей)")
                return True
            else:
                print(f"❌ Не удалось склеить части сцены {scene_id}")
                return False
        else:
            print(f"❌ Анимированы только {len(animated_parts)} из {len(scene_parts)} частей сцены {scene_id}")
            return False


def normalize_video_to_target(input_path: Path, output_path: Path, target_width: int, target_height: int, target_fps: int = 25) -> bool:
    """Нормализует видео к заданным FPS и разрешению (scale+pad) для финальной склейки."""
    try:
        cmd = [
            'ffmpeg', '-y',
            '-i', str(input_path),
            '-c:v', 'libx264', '-preset', 'superfast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '128k',
            '-pix_fmt', 'yuv420p',
            '-vf', f'scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2',
            '-r', str(target_fps),
            str(output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Нормализован под {target_width}x{target_height}@{target_fps}: {input_path.name}")
            return True
        else:
            print(f"❌ Ошибка нормализации {input_path.name}: {result.stderr}")
            return False

    except Exception as e:
        print(f"❌ Исключение при нормализации {input_path.name}: {e}")
        return False


def animate_scenes_for_project(project_id: int, video_format: str) -> Dict[str, Any]:
    """Основная функция для анимации сцен проекта"""
    manager = LTXVideoManager(project_id, video_format)
    
    results = {
        "total_scenes": manager.total_scenes,
        "scenes_to_animate": manager.scenes_to_animate,
        "animated_scenes": [],
        "failed_scenes": [],
        "skipped_scenes": []
    }
    
    for scene_id in manager.scenes_to_animate:
        print(f"🎬 Обрабатываем сцену {scene_id}")
        
        success = manager.animate_scene(scene_id)
        if success:
            results["animated_scenes"].append(scene_id)
        else:
            results["failed_scenes"].append(scene_id)
    
    # Все остальные сцены помечаем как пропущенные
    all_scene_ids = set(range(1, manager.total_scenes + 1))
    processed_scenes = set(manager.scenes_to_animate)
    results["skipped_scenes"] = list(all_scene_ids - processed_scenes)
    
    print(f"🎯 LTX-Video результат: анимировано {len(results['animated_scenes'])}, "
          f"ошибок {len(results['failed_scenes'])}, пропущено {len(results['skipped_scenes'])}")
    
    return results 