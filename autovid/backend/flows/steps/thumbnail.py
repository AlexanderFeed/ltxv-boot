"""
thumbnail_generator.py
--------------------
Модуль для генерации превью (thumbnail) для YouTube видео.
Объектно-ориентированная версия.
"""

# import random
from pathlib import Path
import os
from openai import OpenAI
from autovid.backend.config import OPENAI_API_KEY, MODEL_NAME, THUMBNAIL_CONFIG
from autovid.backend.models.db import get_session
from autovid.backend.models.db_utils import get_project_by_id
from typing import Optional, Dict, Any
from dataclasses import dataclass
import requests
import asyncio
import aiohttp
import re
import json
from PIL import Image
import io

@dataclass
class ThumbnailConfig:
    """Конфигурация для генерации превью"""
    model_name: str = MODEL_NAME
    temperature: float = THUMBNAIL_CONFIG["temperature"]
    max_prompt_words: int = THUMBNAIL_CONFIG["max_prompt_words"]

class MidjourneyGenerator:
    """Генератор изображений через Midjourney API"""
    
    def __init__(self, title: str, format: str = "long"):
        self.title = title
        self.format = format
        # Midjourney API endpoints
        self.midjourney_api_url = "http://62.109.1.147:8062/v1/api"
        self.midjourney_cdn_url = "https://small-sea-52ae.pancakebasic.workers.dev"
        
    def generate_prompt(self, title: str) -> str:
        """Генерирует промпт для Midjourney через ChatGPT"""
        client = OpenAI(api_key=OPENAI_API_KEY)
        messages = [
            {"role": "system", "content": "You are an expert at creating highly engaging, clickbait-style image generation prompts for AI. Your prompts must produce photorealistic images that instantly grab attention and create irresistible curiosity. You adapt the style and tone based on the topic: if the theme is realistic (e.g., archaeology, discoveries, news), prefer a documentary or authentic photographic feel; if the theme is abstract, futuristic, or scientific, you can introduce moderate dramatic lighting, artistic composition, or a touch of surrealism for intrigue. Always balance realism and visual impact, avoiding cartoonish exaggeration. Focus on maximum clarity, emotional engagement, and a believable atmosphere appropriate to the subject."},
            {"role": "user", "content": f"""Create a detailed visual prompt for AI image generation that will be used as a YouTube thumbnail. The image must be designed to maximize clicks through extreme visual intrigue and a compelling subject.

            CRITICAL REQUIREMENTS:
            - PHOTOREALISTIC STYLE: The image should look as close to a real photograph as possible, unless the topic is abstract or conceptual, in which case slight artistic enhancement is acceptable.
            - ADAPTIVE TONE: If the topic is real-world and investigative, prefer a documentary or serious style. If the topic is scientific, futuristic, or conceptual, allow moderate creative elements to increase engagement.
            - STRONG VISUAL HOOK: Include a main subject or scenario that feels extraordinary, mysterious, or shocking, appropriate to the topic.
            - CONTROLLED EMOTION: People can look focused, amazed, or intrigued, but avoid cartoonish overacting.
            - CLEAR FOCAL POINT: One main subject that immediately draws attention.
            - BRIGHT, WELL-LIT COMPOSITION: Use natural daylight or strong clean lighting to make the scene vivid, clear, and bright—avoid dark, gloomy, or heavily shadowed imagery.
            - BELIEVABLE CONTEXT: Even surreal or conceptual scenes must feel grounded in some reality, avoiding overt fantasy.
            - VISUAL IMPACT: Composition should evoke strong curiosity and the desire to understand the story behind the image.

            The prompt should describe a specific, high-impact moment that feels realistic and visually striking, tailored to the theme: \n\nVideo title:\n{title}\n

            Respond ONLY with the image prompt text, no additional commentary."""}
        ]
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0.8
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ Ошибка при генерации промпта: {e}")
            return None

    async def generate_image(self, prompt: str) -> bytes:
        """Генерирует изображение через Midjourney API"""
        aspect_ratio = "--ar 9:19 --v 6.1 --style raw --stylize 100" if self.format == "shorts" else "--ar 16:9 --v 6.1 --style raw --stylize 100"
        midjourney_prompt = f"{prompt} {aspect_ratio}"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.midjourney_api_url}/trigger/imagine",
                json={"prompt": midjourney_prompt, "picurl": "string"},
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status != 200:
                    print(f"❌ Midjourney API вернул статус: {response.status}")
                    return None
                result = await response.json()
                request_id = result.get("trigger_id") or result.get("id") or result.get("request_id") or result.get("task_id")
                if not request_id:
                    print(f"❌ Не получен ID задачи от Midjourney: {result}")
                    return None
                
                print(f"🎯 Запрос отправлен: {request_id}")

        return await self._wait_for_result(request_id)

    async def _wait_for_result(self, request_id: str) -> bytes:
        """Ожидает результат генерации от Midjourney"""
        total_time = 0
        retries = 0
        max_retries = 15

        async with aiohttp.ClientSession() as session:
            while total_time < 120:
                await asyncio.sleep(5 if total_time < 30 else 10)
                total_time += 5 if total_time < 30 else 10

                try:
                    async with session.get(
                        f"{self.midjourney_api_url}/trigger/results/{request_id}",
                        headers={"accept": "application/json"}
                    ) as response:
                        if response.status != 200:
                            print(f"⚠️ Сервер вернул статус {response.status}, повтор запроса...")
                            retries += 1
                            if retries >= max_retries:
                                print("❌ Превышено количество попыток после ошибки статуса.")
                                return None
                            continue

                        try:
                            result_data = await response.json()
                        except Exception as e:
                            print(f"⚠️ Ошибка при чтении JSON: {e}, пробуем снова...")
                            retries += 1
                            if retries >= max_retries:
                                print("❌ Превышено количество попыток после ошибки JSON.")
                                return None
                            continue

                        if isinstance(result_data, str) and "server disconnected" in result_data.lower():
                            print("⚠️ Ответ: 'Server disconnected'. Повторяем запрос...")
                            retries += 1
                            if retries >= max_retries:
                                print("❌ Слишком много попыток после 'server disconnected'.")
                                return None
                            continue

                        attachments = result_data.get("attachments", [])
                        print(f"📎 Получено вложений: {len(attachments)}")
                        if attachments:
                            url = attachments[0].get("url")
                            print(f"🔗 URL вложения: {url}")
                            if url:
                                # Пробуем извлечь task_id из разных форматов URL
                                task_id_match = re.search(r'_([a-f0-9\-]{36})\.(png|webp|jpg|jpeg)', url)
                                if task_id_match:
                                    task_id = task_id_match.group(1)
                                    # Пробуем использовать Midjourney CDN
                                    single_image_url = f"{self.midjourney_cdn_url}/{task_id}/0_0.png"
                                    print(f"🖼️ Пробуем Midjourney CDN: {single_image_url}")
                                    image_bytes = await self._download_image(session, single_image_url)
                                    if image_bytes:
                                        return image_bytes
                                    else:
                                        print(f"⚠️ Midjourney CDN недоступен, используем оригинальный URL")
                                        return await self._download_image(session, url)
                                else:
                                    print(f"❌ Не удалось найти task_id в URL: {url}")
                                    # Пробуем загрузить изображение напрямую
                                    return await self._download_image(session, url)

                except aiohttp.ClientError as e:
                    print(f"⚠️ Ошибка соединения: {e}")
                    retries += 1
                    if retries >= max_retries:
                        print("❌ Слишком много попыток после ошибок соединения.")
                        return None

        print("❌ Превышено время ожидания результата.")
        return None

    async def _download_image(self, session: aiohttp.ClientSession, url: str) -> bytes:
        """Загружает изображение по URL"""
        # Определяем тип CDN по URL
        if "cdn.discordapp.com" in url:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://discord.com/",
                "Origin": "https://discord.com/",
                "Sec-Fetch-Dest": "image",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "cross-site"
            }
        else:
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://cdn.midjourney.com/",
                "Origin": "https://cdn.midjourney.com/"
            }
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                return await response.read()
            print(f"❌ Ошибка загрузки изображения: {response.status}")
            return None

class FluxImageGenerator:
    """Генератор изображений через внутренний Flux API"""
    
    def __init__(self, format: str = "long"):
        self.format = format
        # Используем внутренний Flux API
        self.flux_api_url = "http://localhost:8000"
        
    def get_resolution(self) -> tuple:
        """Возвращает разрешение в зависимости от формата"""
        if self.format == "shorts":
            return (720, 1280)  # Вертикальный формат для shorts
        else:
            return (1280, 720)  # Горизонтальный формат для long
            
    async def generate_image(self, prompt: str) -> bytes:
        """Генерирует изображение через внутренний Flux API"""
        try:
            # Используем GET endpoint с query параметрами (как в существующем Flux сервисе)
            params = {
                "prompt": prompt,
                "format": self.format,
                "seed": 42
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.flux_api_url}/generate",
                    params=params
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        file_path = result.get("file")
                        if file_path:
                            # Формируем полный URL для загрузки изображения
                            image_url = f"{self.flux_api_url}/flux_service/static/{file_path.split('/')[-1]}"
                            print(f"🖼️ Загружаем изображение: {image_url}")
                            
                            # Загружаем изображение
                            async with session.get(image_url) as img_response:
                                if img_response.status == 200:
                                    return await img_response.read()
                                else:
                                    print(f"❌ Ошибка загрузки изображения: {img_response.status}")
                                    return None
                        else:
                            print(f"❌ Не получен путь к файлу в ответе: {result}")
                            return None
                    else:
                        print(f"❌ Flux API вернул статус: {response.status}")
                        return None
                    
        except Exception as e:
            print(f"❌ Ошибка при вызове Flux API: {e}")
            return None

class DatabaseManager:
    """Класс для работы с базой данных"""
    
    def __init__(self):
        pass
    
    def get_project_title(self, project_id: int) -> Optional[str]:
        """Получает заголовок проекта из базы данных"""
        try:
            project = get_project_by_id(project_id)
            if not project:
                print(f"❌ Проект {project_id} не найден в базе данных")
                return None
            
            return project.title
            
        except Exception as e:
            print(f"❌ Ошибка при получении заголовка из БД: {e}")
            return None


class ThumbnailManager:
    """Менеджер генерации превью с fallback логикой"""
    
    def __init__(self):
        self.config = ThumbnailConfig()
        
    async def generate_thumbnail(self, project_id: int, video_format: str = "long") -> bool:
        """Генерирует превью для проекта с приоритетом Midjourney"""
        try:
            # Получаем проект
            project = get_project_by_id(project_id)
            if not project:
                print(f"❌ Проект {project_id} не найден")
                return False
                
            title = project.title
            print(f"🎯 Генерация превью для проекта {project_id}: {title}")
            
            # Сначала пробуем Midjourney
            print("🎨 Пробуем Midjourney...")
            midjourney_gen = MidjourneyGenerator(title, video_format)
            prompt = midjourney_gen.generate_prompt(title)
            
            if prompt:
                print(f"📝 Сгенерированный промпт: {prompt}")
                image_bytes = await midjourney_gen.generate_image(prompt)
                
                if image_bytes:
                    # Сохраняем изображение
                    await self._save_thumbnail(image_bytes, project_id, video_format)
                    print("✅ Превью успешно сгенерировано через Midjourney")
                    return True
                else:
                    print("⚠️ Midjourney не смог сгенерировать изображение, пробуем Flux...")
            else:
                print("⚠️ Не удалось сгенерировать промпт, пробуем Flux...")
            
            # Fallback на Flux
            print("🔄 Fallback на Flux API...")
            flux_gen = FluxImageGenerator(video_format)
            image_bytes = await flux_gen.generate_image(prompt or title)
            
            if image_bytes:
                await self._save_thumbnail(image_bytes, project_id, video_format)
                print("✅ Превью успешно сгенерировано через Flux")
                return True
            else:
                print("❌ Не удалось сгенерировать превью ни через Midjourney, ни через Flux")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка при генерации превью: {e}")
            return False
            
    async def _save_thumbnail(self, image_bytes: bytes, project_id: int, video_format: str):
        """Сохраняет превью с оптимизацией качества"""
        try:
            # Создаем директорию для превью
            thumbnail_dir = Path(f"assets/thumbnail")
            thumbnail_dir.mkdir(parents=True, exist_ok=True)
            
            # Путь к файлу
            thumbnail_path = thumbnail_dir / f"thumbnail_{project_id}.jpg"
            
            # Открываем изображение и оптимизируем
            img = Image.open(io.BytesIO(image_bytes))
            quality = 95
            
            while True:
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=quality, optimize=True)
                size = output.tell()
                if size <= 2000000 or quality < 30:  # Максимум 2MB
                    break
                quality -= 5
            
            # Сохраняем файл
            with thumbnail_path.open("wb") as f:
                f.write(output.getvalue())
                
            print(f"💾 Превью сохранено: {thumbnail_path} ({size} bytes, качество: {quality}%)")
            
        except Exception as e:
            print(f"❌ Ошибка при сохранении превью: {e}")
            raise