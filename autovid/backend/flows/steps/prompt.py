"""
prompt_generator.py
------------------
Модуль для генерации промптов изображений на основе текстовых фрагментов.
Объектно-ориентированная версия.
"""

import time
from openai import OpenAI
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from autovid.backend.config import OPENAI_API_KEY, MODEL_NAME, PROMPT_CONFIG


@dataclass
class PromptConfig:
    """Конфигурация для генерации промптов"""
    model_name: str = MODEL_NAME
    temperature: float = PROMPT_CONFIG["temperature"]
    max_prompt_words: int = PROMPT_CONFIG["max_prompt_words"]
    max_retries: int = PROMPT_CONFIG["max_retries"]
    retry_delay: int = PROMPT_CONFIG["retry_delay"]
    max_workers: int = PROMPT_CONFIG["max_workers"]

class PromptGenerator:
    """Класс для генерации промптов с помощью GPT"""
    
    def __init__(self, config: Optional[PromptConfig] = None):
        self.config = config or PromptConfig()
        self.client = OpenAI(api_key=OPENAI_API_KEY)
    
    def _build_system_prompt(self) -> str:
        """Строит системный промпт для GPT"""
        return "You are an expert at creating photorealistic image generation prompts for AI image generators."
    
    def _build_user_prompt(self, text: str) -> str:
        """Строит пользовательский промпт для GPT"""
        return f"""Read this piece of text and write a short, detailed prompt for creating a photorealistic photograph that presents the main idea of ​​the text. Make sure the prompt is very descriptive and highlights the most important scene or concept. WARNING: The prompt MUST be no more than {self.config.max_prompt_words} words. Do not include titles or explanations, only the prompt. If your output exceeds {self.config.max_prompt_words} words, you will fail this task.

Text fragment:
{text}"""
    
    def generate_prompt_for_chunk(self, chunk: Dict[str, Any]) -> Dict[str, Any]:
        """Генерирует промпт для одного чанка с повторными попытками"""
        chunk_id = chunk["id"]
        text = chunk["text"]
        
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": self._build_user_prompt(text)}
        ]
        
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model_name,
                    messages=messages,
                    temperature=self.config.temperature
                )
                image_prompt = response.choices[0].message.content
                return {"id": chunk_id, "image_prompt": image_prompt}
                
            except Exception as e:
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_delay)
                else:
                    print(f"[!] Ошибка при генерации промпта для чанка {chunk_id}: {e}")
                    return {"id": chunk_id, "image_prompt": f"[ERROR] {e}"}


class ConcurrentPromptProcessor:
    """Класс для параллельной обработки промптов"""
    
    def __init__(self, config: Optional[PromptConfig] = None):
        self.config = config or PromptConfig()
        self.prompt_generator = PromptGenerator(config)
    
    def _process_chunk_with_fallback(self, chunk: Dict[str, Any], chunk_index: int) -> Dict[str, Any]:
        """Обрабатывает чанк с обработкой ошибок"""
        try:
            return self.prompt_generator.generate_prompt_for_chunk(chunk)
        except Exception as exc:
            print(f"[!] Ошибка в потоке для чанка {chunk_index}: {exc}")
            return {"id": chunk["id"], "image_prompt": f"[ERROR] {exc}"}
    
    def process_chunks_concurrently(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Обрабатывает чанки параллельно"""
        image_prompts = [None] * len(chunks)
        
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            future_to_idx = {
                executor.submit(self._process_chunk_with_fallback, chunk, idx): idx 
                for idx, chunk in enumerate(chunks)
            }
            
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    result = future.result()
                except Exception as exc:
                    print(f"[!] Ошибка в потоке: {exc}")
                    result = {"id": chunks[idx]["id"], "image_prompt": f"[ERROR] {exc}"}
                image_prompts[idx] = result
        
        return image_prompts


class PromptManager:
    """Основной класс для управления генерацией промптов"""
    
    def __init__(self, chunks: List[Dict[str, Any]], config: Optional[PromptConfig] = None):
        self.config = config or PromptConfig()
        self.chunks = chunks
        self.concurrent_processor = ConcurrentPromptProcessor(config)
    
    def generate(self) -> List[Dict[str, Any]]:
        """Генерирует промпты изображений для проекта"""
        try:
            image_prompts = self.concurrent_processor.process_chunks_concurrently(self.chunks)
            
            return image_prompts
            
        except Exception as e:
            print(f"❌ Ошибка при генерации промптов: {e}")
            raise