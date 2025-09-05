"""
script.py
----------------
Унифицированный модуль для генерации сценариев различных форматов.
Заменяет script.py и script_shorts.py
"""
import re
import openai
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
import os

from autovid.backend.config import OPENAI_API_KEY, MODEL_NAME, SCRIPT_CONFIG
from autovid.backend.flows.constants.script_instructions import (
    LONG_VIDEO_INSTRUCTIONS, 
    SHORTS_VIDEO_INSTRUCTIONS,
    DEFAULT_NUM_CHAPTERS,
    DEFAULT_TEMPERATURE,
    DEFAULT_MIN_WORDS_PER_CHAPTER,
    DEFAULT_SHORTS_MAX_WORDS
)

@dataclass
class ScriptConfig:
    """Конфигурация для генерации сценария"""
    default_instructions: str = LONG_VIDEO_INSTRUCTIONS
    default_num_chapters: int = DEFAULT_NUM_CHAPTERS
    temperature: float = SCRIPT_CONFIG["temperature"]
    min_words_per_chapter: int = DEFAULT_MIN_WORDS_PER_CHAPTER


class Logger:
    """Класс для логирования взаимодействия с GPT"""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
    
    def log(self, log_path: Path, role: str, text: str) -> None:
        """Логирует взаимодействие с GPT"""
        if not self.enabled:
            return
            
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- {role.upper()} ---\n{text}\n")


class GPTHandler:
    """Класс для работы с OpenAI API"""
    
    def __init__(self, api_key: str, model_name: str):
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY не найден. Добавьте ключ в .env")
        
        self.client = openai.OpenAI(api_key=api_key)
        self.model_name = model_name
    
    def generate_response(self, prompt: str, temperature: float = 0.9) -> str:
        """Генерирует ответ от GPT"""
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return response.choices[0].message.content.strip()


class ScriptGenerator:
    """Основной класс для генерации сценариев"""
    
    def __init__(self, config: Optional[ScriptConfig] = None):
        self.config = config or ScriptConfig()
        self.gpt_handler = GPTHandler(OPENAI_API_KEY, MODEL_NAME)
        self.logger = Logger()
    
    def generate_plan(self, topic: str, num_chapters: Optional[int] = None, log_path: Optional[Path] = None) -> List[str]:
        """Генерирует план сценария с названиями глав"""
        num_chapters = num_chapters or self.config.default_num_chapters
        
        plan_prompt = (
            self.config.default_instructions
            + f"\n\nТема ролика: {topic}\n\n"
            + f"Дай структуру сценария в виде списка из ровно {num_chapters} названий глав без нумерации и без лишних символов."
        )
        
        if log_path:
            self.logger.log(log_path, "prompt", plan_prompt)
        
        plan_text = self.gpt_handler.generate_response(plan_prompt, self.config.temperature)
        
        if log_path:
            self.logger.log(log_path, "gpt", plan_text)
        
        lines = [line.strip() for line in re.split(r'[\r\n]+', plan_text) if line.strip()]
        chapters = [re.sub(r'^\d+[\).\-\s]*', '', line) for line in lines]
        
        return chapters
    
    def build_prompt(self, topic: str, extra_instructions: Optional[str] = None) -> str:
        """Строит промпт для генерации сценария"""
        instructions = extra_instructions or self.config.default_instructions
        return f"{instructions}\n\nТема ролика: {topic}\n\nСценарий:"
    
    def generate_script_by_chapter(
        self,
        topic: str,
        num_chapters: Optional[int] = None,
        extra_instructions: Optional[str] = None,
        use_plan: bool = True,
        log_path: Optional[Path] = None,
    ) -> str:
        """Генерирует сценарий по главам"""
        num_chapters = num_chapters or self.config.default_num_chapters
        
        if use_plan:
            plan = self.generate_plan(topic, num_chapters, log_path=log_path)
            num_chapters = len(plan)
        else:
            plan = [None] * num_chapters
        
        full_text = []
        previous = []
        
        for i, title in enumerate(plan, start=1):
            chapter_prompt = (
                (extra_instructions or self.config.default_instructions)
                + f"\n\nТема ролика: {topic}\n\n"
                + ("Структура: " + "; ".join(plan) + "\n\n" if use_plan else "")
                + (f"Пиши текст главы {i}: {title}.\n" if title else f"Пиши текст главы {i}.\n")
                + ("Предыдущие главы:\n" + "\n".join(previous) + "\n\n" if previous else "")
                + f"Выводи ТОЛЬКО текст главы без лишних символов. Обязательно используй инструкцию и выдавай не меньше {self.config.min_words_per_chapter} слов в одной главе. Также не забывай, что в главе должно быть минимум воды и рассуждений. Текст должен быть динамичным и насыщенным фактами и событиями. Мы не рассуждаем о том, о чем заставляет задуматься это событие и подобное. Только события и действия."
            )
            
            if log_path:
                self.logger.log(log_path, "prompt", chapter_prompt)
            
            chapter = self.gpt_handler.generate_response(chapter_prompt, self.config.temperature)
            
            if log_path:
                self.logger.log(log_path, "gpt", chapter)
            
            full_text.append(chapter)
            previous.append(chapter)
        
        return "\n\n".join(full_text)
    
    def generate(
        self,
        topic: str,
        script_file: Path,
        num_chapters: Optional[int] = None,
        use_plan: bool = True,
        extra_instructions: Optional[str] = None,
    ) -> str:
        """Генерирует и сохраняет сценарий"""
        log_path = script_file.parent / (script_file.stem + "_log.txt")
        os.makedirs(script_file.parent, exist_ok=True)
        try:
            script = self.generate_script_by_chapter(
                topic=topic,
                num_chapters=num_chapters,
                extra_instructions=extra_instructions,
                use_plan=use_plan,
                log_path=log_path,
            )
            
            return script
        except Exception as e:
            return f"Ошибка при генерации сценария: {str(e)}"


class ShortsScriptGenerator:
    """Класс для генерации сценариев коротких видео (shorts)"""
    
    def __init__(self):
        self.client = openai.OpenAI(api_key=OPENAI_API_KEY)
        self.logger = Logger()
    
    def generate_script_shorts(
        self,
        topic: str,
        log_path: Optional[Path] = None,
    ) -> str:
        """Генерирует сценарий для короткого видео"""
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY не найден. Добавьте ключ в .env")
        
        # System message - роль и инструкции для модели
        system_message = SHORTS_VIDEO_INSTRUCTIONS
        
        # User message - конкретный запрос
        user_message = f"Тема ролика: {topic}\n\nНапиши единый сценарий для короткого ролика НЕ БОЛЕЕ {DEFAULT_SHORTS_MAX_WORDS} СЛОВ с логичным завершением."
        
        if log_path: 
            self.logger.log(log_path, "system", system_message)
            self.logger.log(log_path, "user", user_message)
        
        response = self.client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            temperature=DEFAULT_TEMPERATURE,
        )
        script = response.choices[0].message.content.strip()
        if log_path: 
            self.logger.log(log_path, "gpt", script)
        return script
    
    def generate(
        self,
        topic: str,
        script_file: Path,
    ) -> str:
        """Генерирует и сохраняет сценарий для shorts"""
        log_path = script_file.parent / (script_file.stem + "_log.txt")
        os.makedirs(script_file.parent, exist_ok=True)
        try:
            script = self.generate_script_shorts(topic, log_path=log_path)
            return script
        except Exception as e:
            return f"Ошибка при генерации сценария: {str(e)}"
