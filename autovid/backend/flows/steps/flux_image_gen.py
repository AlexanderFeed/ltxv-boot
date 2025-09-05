"""
flux_image_gen.py
-----------------
Модуль для генерации изображений через Flux API.
Объектно-ориентированная версия.
"""
import time
import requests
import random
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass

from autovid.backend.config import FLUX_API_URL, FLUX_CONFIG
from autovid.backend.models.db import get_session


@dataclass
class FluxConfig:
    """Конфигурация для Flux API"""
    api_url: str = FLUX_API_URL
    timeout: int = FLUX_CONFIG["timeout"]
    max_retries: int = FLUX_CONFIG["max_retries"]
    api_key: str = FLUX_CONFIG["api_key"]
    model: str = FLUX_CONFIG["model"]


class FluxAPIClient:
    """Класс для работы с Flux API"""
    
    def __init__(self, config: Optional[FluxConfig] = None):
        self.config = config or FluxConfig()
    
    def generate_image_local(self, prompt, filename, video_format="long", priority: str = "low"):
        seed = random.randint(1, 100000)
        print(f"🖼️ Генерация изображения по промту: '{prompt}' (seed: {seed}, format: {video_format}, priority: {priority})")

        try:
            # Синхронная постановка задачи с ожиданием результата
            payload = {"prompt": prompt, "seed": seed, "format": video_format, "priority": priority, "wait": True}
            resp = requests.post(
                f"{self.config.api_url}/enqueue",
                json=payload,
                timeout=None  # ждём до готовности результата, без клиентского таймаута
            )
            resp.raise_for_status()

            data = resp.json()
            if data.get("status") != "completed":
                raise RuntimeError(f"Flux вернул неуспех: {data}")

            # Предпочитаем url, иначе строим по file
            url = data.get("url") or data.get("file")
            if not url:
                raise RuntimeError("Flux не вернул путь к изображению")

            # Собираем абсолютный URL
            if url.startswith("http://") or url.startswith("https://"):
                img_url = url
            else:
                base = self.config.api_url.rstrip("/")
                path = url if url.startswith("/") else f"/{url}"
                img_url = f"{base}{path}"

            img_resp = requests.get(img_url, timeout=30)
            img_resp.raise_for_status()
            img_bytes = img_resp.content
            print(f"🔗 Получен URL: {img_url} | размер={len(img_bytes)} байт")
            
            # Удаляем файл с сервера Flux после успешного получения
            try:
                # Получаем ID задачи для удаления
                task_id = data.get("id")
                if task_id:
                    delete_url = f"{self.config.api_url}/file/{task_id}"
                    delete_resp = requests.delete(delete_url, timeout=10)
                    if delete_resp.status_code == 200:
                        print(f"🗑️ Файл успешно удален с сервера Flux (task_id: {task_id})")
                    else:
                        print(f"⚠️ Не удалось удалить файл с сервера Flux: {delete_resp.status_code}")
                else:
                    print("⚠️ Не удалось получить task_id для удаления файла")
            except Exception as delete_error:
                print(f"⚠️ Ошибка при удалении файла с сервера Flux: {delete_error}")
            
            return img_bytes

        except Exception as e:
            print(f"❌ Ошибка при генерации изображения: {e}")
        
    def generate_image(self, prompt: str, aspect_ratio: str = "16:9", polling_delay: int = 2, max_retries: int = 60) -> bytes:
        import time
        """Асинхронная генерация изображения через Flux API (c polling)"""

        headers = {
            "x-key": "9010f035-4f97-42a5-a650-2ffdcd1c4cce",
            "accept": "application/json",
            "Content-Type": "application/json"
        }

        data = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio
        }

        print("🚀 Отправляем запрос на генерацию...")
        response = requests.post(
            "https://api.bfl.ai/v1/flux-dev",
            headers=headers,
            json=data,
            timeout=self.config.timeout
        )
        response.raise_for_status()
        result = response.json()

        polling_url = result.get("polling_url")
        request_id = result.get("id")
        if not polling_url:
            raise ValueError("❌ polling_url отсутствует в ответе API")

        print(f"📡 Получен polling_url: {polling_url}")

        # Polling loop
        start_time = time.time()
        while True:
            if time.time() - start_time > max_retries * polling_delay:
                raise Exception(f"Превышено время ожидания генерации изображения ({max_retries * polling_delay} секунд)")
                
            time.sleep(polling_delay)
            result = requests.get(
                polling_url,
                headers={
                    'accept': 'application/json',
                    'x-key': "9010f035-4f97-42a5-a650-2ffdcd1c4cce",
                },
                params={
                    'id': request_id,
                },
            ).json()
            
            status = result["status"]
            print(f"Status: {status}")
            
            if status == "Ready":
                image_url = result['result']['sample']
                print(f"📥 Загружаем изображение по URL: {image_url}")
                
                # Загружаем изображение по URL
                img_response = requests.get(image_url, timeout=self.config.timeout)
                img_response.raise_for_status()
                
                return img_response.content
            elif status in ["Error", "Failed"]:
                print(f"Generation failed: {result}")
                raise Exception(f"Генерация изображения не удалась: {result}")
            
        raise Exception("Превышено время ожидания генерации изображения")

class FileManager:
    """Класс для управления файлами изображений"""
    
    def __init__(self, project_id: int, scenes_dir: Path):
        self.project_id = project_id
        self.scenes_dir = scenes_dir
    
    def get_existing_scenes(self) -> Set[int]:
        """Возвращает множество ID уже существующих сцен"""
        existing = sorted(
            self.scenes_dir.glob("scene_*.jpg"), 
            key=lambda p: int(p.stem.split("_")[-1])
        )
        return {int(p.stem.split("_")[-1]) for p in existing}
    
    def save_image(self, image_data: bytes, filename: str) -> Path:
        """Сохраняет изображение в файл"""
        save_path = self.scenes_dir / filename
        with open(save_path, "wb") as f:
            f.write(image_data)
        return save_path
    
    def get_scene_filename(self, scene_id: int) -> str:
        """Возвращает имя файла для сцены"""
        return f"scene_{scene_id:02}.jpg"


class ImageGenerator:
    """Класс для генерации изображений"""
    
    def __init__(self, config: Optional[FluxConfig] = None):
        self.config = config or FluxConfig()
        self.api_client = FluxAPIClient(config)
    
    def generate_single_image(self, prompt: str, filename: str, video_format: str = "long", priority: str = "low") -> Optional[Path]:
        """Генерирует одно изображение"""
        seed = random.randint(1, 100000)
        print(f"🖼️ Генерация изображения по промту: '{prompt}' (seed: {seed}, format: {video_format})")

        try:
            image_data = self.api_client.generate_image_local(prompt, filename, video_format, priority=priority)
            save_path = Path(filename)
            # Создаем директорию, если она не существует
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(image_data)
            print(f"✅ Сохранено: {save_path}")
            return save_path
            
        except Exception as e:
            print(f"❌ FLUX_IMAGE_EXCEPTION: {e} | filename={filename}")
            import traceback
            print(f"🔍 Подробности ошибки: {traceback.format_exc()}")
            return None


class MissingSceneDetector:
    """Класс для обнаружения пропущенных сцен"""
    
    @staticmethod
    def find_missing_scenes(prompts: List[Dict[str, Any]], existing_ids: Set[int]) -> List[int]:
        """Находит пропущенные сцены"""
        missing_scenes = []
        for item in prompts:
            idx = item["id"]
            if idx not in existing_ids:
                missing_scenes.append(idx)
        return missing_scenes


class FluxImageManager:
    """Основной класс для управления генерацией изображений"""
    
    def __init__(self, project_id: int, video_format: str = "long", prompts: List[Dict[str, Any]] = None, scenes_dir: Path = None, config: Optional[FluxConfig] = None):
        self.project_id = project_id
        self.video_format = video_format
        self.config = config or FluxConfig()
        
        self.prompts = prompts
        self.file_manager = FileManager(project_id, scenes_dir)
        self.image_generator = ImageGenerator(config)
        self.scene_detector = MissingSceneDetector()
    
    def generate(self) -> Dict[str, Any]:
        """Генерирует все недостающие изображения"""
        
        if not self.prompts:
            print(f"❌ Промпты не найдены для проекта {self.project_id}")
            return False
        
        # Находим существующие сцены
        existing_ids = self.file_manager.get_existing_scenes()
        
        # Находим пропущенные сцены
        missing_scenes = self.scene_detector.find_missing_scenes(self.prompts, existing_ids)
        
        if missing_scenes:
            print(f"🔍 Обнаружены пропущенные сцены: {missing_scenes}")
            
            # Генерируем только пропущенные сцены
            generated_count = 0
            failed_count = 0
            
            for idx in missing_scenes:
                prompt = next(item["image_prompt"] for item in self.prompts if item["id"] == idx)
                filename = self.file_manager.get_scene_filename(idx)
                print(f"🖼️ Генерация пропущенной сцены {idx}")
                
                result = self.image_generator.generate_single_image(
                    prompt, 
                    str(self.file_manager.scenes_dir / filename), 
                    self.video_format
                )
                
                if result:
                    generated_count += 1
                else:
                    failed_count += 1
        else:
            print("✅ Все сцены уже сгенерированы")
            generated_count = 0
            failed_count = 0
        
        return {
            "project_id": self.project_id,
            "video_format": self.video_format,
            "total_prompts": len(self.prompts),
            "existing_scenes": len(existing_ids),
            "missing_scenes": len(missing_scenes),
            "generated": generated_count,
            "failed": failed_count
        }
        
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Генерация изображений через Flux API")
    parser.add_argument("--project_id", type=int, default=1, help="ID проекта")
    parser.add_argument("--scene_id", type=int, default=0, help="ID сцены")
    parser.add_argument("--prompt", type=str, required=True, help="Промпт для генерации")
    parser.add_argument("--scenes_dir", type=str, default="assets/scenes", help="Папка для сохранения изображений")
    parser.add_argument("--video_format", type=str, default="long", help="Формат видео (long / short)")

    args = parser.parse_args()

    scenes_path = Path(args.scenes_dir) / str(args.project_id)
    scenes_path.mkdir(parents=True, exist_ok=True)

    # Создаём генератор
    image_generator = ImageGenerator()
    filename = scenes_path / f"scene_{args.scene_id:02}.jpg"

    result_path = image_generator.generate_single_image(
        prompt=args.prompt,
        filename=str(filename),
        video_format=args.video_format
    )

    if result_path:
        print(f"✅ Успешно сохранено: {result_path}")
    else:
        print("❌ Не удалось сгенерировать изображение")