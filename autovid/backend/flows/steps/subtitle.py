"""
subtitle_generator.py
--------------------
Модуль для генерации субтитров на основе аудио файлов.
Объектно-ориентированная версия.
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
import openai
import math
import time
import requests
from requests.exceptions import Timeout, RequestException
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from abc import ABC, abstractmethod

# Добавляем родительскую директорию в путь для импорта
sys.path.append(str(Path(__file__).parent.parent.parent))
from autovid.backend.config import SUBTITLE_STYLES, SUBTITLE_CONFIG, OPENAI_API_KEY

# Загрузка переменных окружения
load_dotenv()
openai.api_key = OPENAI_API_KEY


@dataclass
class SubtitleConfig:
    """Конфигурация для генерации субтитров"""
    whisper_timeout: int = SUBTITLE_CONFIG["whisper_timeout"]
    max_retries: int = SUBTITLE_CONFIG["max_retries"]
    retry_delay: int = SUBTITLE_CONFIG["retry_delay"]
    language: str = SUBTITLE_CONFIG["language"]
    model: str = SUBTITLE_CONFIG["model"]
    response_format: str = SUBTITLE_CONFIG["response_format"]
    timestamp_granularities: List[str] = None
    
    def __post_init__(self):
        if self.timestamp_granularities is None:
            self.timestamp_granularities = SUBTITLE_CONFIG["timestamp_granularities"]


class TimeFormatter:
    """Класс для форматирования времени в ASS формате"""
    
    @staticmethod
    def format_ass_time(seconds: float) -> str:
        """Форматирует время в ASS формат"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds - int(seconds)) * 100)
        return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


class WhisperClient:
    """Класс для работы с Whisper API"""
    
    def __init__(self, config: Optional[SubtitleConfig] = None):
        self.config = config or SubtitleConfig()
        self.client = openai
    
    def call_whisper_with_retry(self, audio_path: Path, max_retries: Optional[int] = None) -> Any:
        """Вызывает Whisper API с повторными попытками и таймаутом"""
        max_retries = max_retries or self.config.max_retries
        
        for attempt in range(1, max_retries + 1):
            try:
                print(f"DEBUG: Попытка {attempt}/{max_retries} для {audio_path.name}")
                with open(audio_path, "rb") as f:
                    transcript = self.client.audio.transcriptions.create(
                        model=self.config.model,
                        file=f,
                        response_format=self.config.response_format,
                        language=self.config.language,
                        timestamp_granularities=self.config.timestamp_granularities,
                        timeout=self.config.whisper_timeout
                    )
                print(f"DEBUG: Whisper API успешно обработал {audio_path.name}")
                return transcript
                
            except Timeout:
                print(f"⚠️ Таймаут при обращении к Whisper API (попытка {attempt}/{max_retries})")
                if attempt < max_retries:
                    print(f"DEBUG: Ждем {self.config.retry_delay} секунд перед повторной попыткой...")
                    time.sleep(self.config.retry_delay)
                else:
                    raise Exception(f"Превышен таймаут при обработке {audio_path.name} после {max_retries} попыток")
                    
            except openai.error.RateLimitError as e:
                print(f"⚠️ Превышен лимит запросов к OpenAI (попытка {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    wait_time = self.config.retry_delay * attempt
                    print(f"DEBUG: Ждем {wait_time} секунд перед повторной попыткой...")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"Превышен лимит запросов к OpenAI для {audio_path.name}")
                    
            except openai.error.APIError as e:
                print(f"⚠️ Ошибка API OpenAI (попытка {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    print(f"DEBUG: Ждем {self.config.retry_delay} секунд перед повторной попыткой...")
                    time.sleep(self.config.retry_delay)
                else:
                    raise Exception(f"Ошибка API OpenAI для {audio_path.name}: {e}")
                    
            except (RequestException, Exception) as e:
                print(f"⚠️ Сетевая ошибка при обращении к Whisper API (попытка {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    print(f"DEBUG: Ждем {self.config.retry_delay} секунд перед повторной попыткой...")
                    time.sleep(self.config.retry_delay)
                else:
                    raise Exception(f"Сетевая ошибка при обработке {audio_path.name}: {e}")


class WordProcessor:
    """Класс для обработки слов из транскрипта"""
    
    @staticmethod
    def extract_words_from_transcript(transcript: Any) -> List[Dict[str, Any]]:
        """Извлекает слова из транскрипта Whisper"""
        words = []
        
        if hasattr(transcript, 'segments') and transcript.segments:
            for seg in transcript.segments:
                for w in getattr(seg, 'words', []):
                    words.append({
                        'word': w.word,
                        'start': w.start,
                        'end': w.end
                    })
        
        if hasattr(transcript, 'words') and transcript.words:
            for w in transcript.words:
                words.append({
                    'word': w.word,
                    'start': w.start,
                    'end': w.end
                })
        
        return words
    
    @staticmethod
    def group_words_balanced(words: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """Группирует слова в строки по 4-6 слов для отображения двух строк в кадре"""
        lines = []
        current_line = []
        
        for word in words:
            current_line.append(word)
            if len(current_line) >= 6:
                lines.append(current_line)
                current_line = []
        
        if current_line:
            lines.append(current_line)
        
        return lines


class ASSStyleBase(ABC):
    """Базовый класс для стилей ASS субтитров"""
    
    def __init__(self, style_name: str):
        self.style = SUBTITLE_STYLES.get(style_name, SUBTITLE_STYLES["karaoke"])
        self.style_name = style_name
    
    @abstractmethod
    def create_subtitles(self, words: List[Dict[str, Any]], ass_path: Path) -> None:
        """Создает ASS субтитры"""
        pass
    
    def _get_style_template(self) -> str:
        """Возвращает базовый шаблон стиля"""
        font = self.style.get("font", "fonts/aa_badaboom_bb.ttf")
        font_size = self.style.get("font_size", 60)
        color_active = self.style.get("color_active", "&H00FFFF&")
        color_inactive = self.style.get("color_inactive", "&HFFFFFF&")
        outline_color = self.style.get("outline_color", "&H000000&")
        outline_width = self.style.get("outline_width", 2)
        shadow = self.style.get("shadow", 1)
        
        return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,{font},{font_size},{color_active},{color_inactive},{outline_color},&H00000000,-1,0,0,0,100,100,-8,0,1,{outline_width},{shadow},2,40,40,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""


class KaraokeStyle(ASSStyleBase):
    """Стиль караоке с подсветкой активного слова"""
    
    def create_subtitles(self, words: List[Dict[str, Any]], ass_path: Path) -> None:
        """Создает ASS субтитры в стиле караоке"""
        color_inactive = self.style.get("color_inactive", "&HFFFFFF&")
        color_active = self.style.get("color_active", "&H00FFFF&")
        font = self.style.get("font", "fonts/aa_badaboom_bb.ttf")
        font_size = self.style.get("font_size", 60)
        outline_color = self.style.get("outline_color", "&H000000&")
        outline_width = self.style.get("outline_width", 2)
        shadow = self.style.get("shadow", 1)
        fade_ms = self.style.get("fade_ms", 200)
        fade_curve = self.style.get("fade_curve", "linear")
        letter_spacing = self.style.get("letter_spacing", 0)
        
        line_gap = 60
        playres_x = 720
        playres_y = 1280
        center_x = playres_x // 2
        area_top = 700
        area_bottom = 1100
        area_center = (area_top + area_bottom) // 2
        
        # Кривая для \t: linear=1, ease-in>1, ease-out<1
        accel = 1
        if fade_curve == "ease-in":
            accel = 2
        elif fade_curve == "ease-out":
            accel = 0.5
        elif fade_curve == "ease-in-out":
            accel = 1.5
        
        style_template = self._get_style_template()
        lines = WordProcessor.group_words_balanced(words)
        events = []
        
        for line_idx, line in enumerate(lines):
            if not line:
                continue
            
            n_lines = 1
            pos_y = area_center
            line_start = line[0]['start']
            
            # Для "зависания" строки до следующей:
            if line_idx < len(lines) - 1:
                next_line_start = lines[line_idx + 1][0]['start']
                line_end = next_line_start
            else:
                line_end = line[-1]['end'] + 0.5  # последняя строка висит чуть дольше
            
            for word_idx, word in enumerate(line):
                start_time = max(word['start'], line_start)
                end_time = line_end
                text_parts = []
                
                for j, w in enumerate(line):
                    fsp = f"\\fsp{letter_spacing}" if letter_spacing else ""
                    if j == word_idx:
                        text_parts.append(f"{{\\c{color_active}{fsp}}}{w['word'].upper()}")
                    else:
                        text_parts.append(f"{{\\c{color_inactive}{fsp}}}{w['word'].upper()}")
                
                text = ' '.join(text_parts)
                ev = f"Dialogue: 0,{TimeFormatter.format_ass_time(start_time)},{TimeFormatter.format_ass_time(end_time)},Default,,0,0,0,,{{\\an5\\pos({center_x},{pos_y})}}{text}"
                events.append(ev)
            
            # Для паузы в начале строки — просто белый текст
            if line_idx == 0 and line_start > 0.01:
                text_parts = []
                for w in line:
                    fsp = f"\\fsp{letter_spacing}" if letter_spacing else ""
                    text_parts.append(f"{{\\c{color_inactive}{fsp}}}{w['word'].upper()}")
                text = ' '.join(text_parts)
                ev = f"Dialogue: 0,0.00,{TimeFormatter.format_ass_time(line_start)},Default,,0,0,0,,{{\\an5\\pos({center_x},{pos_y})}}{text}"
                events.append(ev)
        
        with open(ass_path, 'w', encoding='utf-8') as f:
            f.write(style_template)
            for ev in events:
                f.write(ev + "\n")


class HighlightStyle(ASSStyleBase):
    """Стиль с фиолетовой подложкой под активным словом"""
    
    def create_subtitles(self, words: List[Dict[str, Any]], ass_path: Path) -> None:
        """Создает ASS субтитры с фиолетовой подложкой под активным словом"""
        padding_percent = self.style.get("padding_percent", 10)
        fade_ms = self.style.get("fade_ms", 300)
        fade_curve = self.style.get("fade_curve", "ease-in-out")
        color_text = self.style.get("color_active", "&HFFFFFF&")  # Текст всегда белый
        highlight_color = self.style.get("highlight_color", "&H800080&")
        margin_v = self.style.get("margin_v", 320)
        font = self.style.get("font", "Montserrat")
        font_size = self.style.get("font_size", 60)
        outline_width = 0
        shadow = 0
        
        # Параметры подложки
        pad_x = 20  # горизонтальный отступ подложки (px)
        pad_y = 10  # вертикальный отступ подложки (px)
        blur = 2    # сглаживание краёв
        
        style_template = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,{font},{font_size},{color_text},{color_text},&H000000&, &H00000000,-1,0,0,0,100,100,0,0,1,{outline_width},{shadow},2,40,40,{margin_v},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
        
        lines = WordProcessor.group_words_balanced(words)
        events = []
        
        for line_idx, line in enumerate(lines):
            if not line:
                continue
            
            line_start = line[0]['start']
            line_end = line[-1]['end']
            
            if line_idx > 0 and lines[line_idx - 1]:
                prev_line_end = lines[line_idx - 1][-1]['end']
                if line_start < prev_line_end:
                    line_start = prev_line_end
            
            for word_idx, word in enumerate(line):
                start_time = max(word['start'], line_start)
                
                if word_idx < len(line) - 1:
                    end_time = line[word_idx + 1]['start']
                else:
                    if line_idx < len(lines) - 1 and lines[line_idx + 1]:
                        next_line_start = lines[line_idx + 1][0]['start']
                        end_time = min(word['end'] + 0.3, next_line_start)
                    else:
                        end_time = word['end'] + 1.0
                
                # Формируем строку текста
                text_parts = []
                for j, w in enumerate(line):
                    padding = " " * max(1, (len(w['word']) * padding_percent // 100))
                    text_parts.append(w['word'].upper() + padding)
                text = ' '.join(text_parts).strip()
                
                # Координаты подложки (примерно):
                # Для простоты считаем, что ширина символа ≈ font_size * 0.6
                x0 = 360  # центр экрана (PlayResX/2)
                total_len = sum(len(w['word']) + max(1, (len(w['word']) * padding_percent // 100)) for w in line)
                text_width = total_len * font_size * 0.6
                
                # Смещение для активного слова
                left_offset = sum(len(w['word']) + max(1, (len(w['word']) * padding_percent // 100)) for w in line[:word_idx]) * font_size * 0.6
                word_len = len(word['word']) * font_size * 0.6
                word_width = word_len + 2 * pad_x
                word_height = font_size + 2 * pad_y
                
                # Координаты прямоугольника подложки
                rect_x1 = int(x0 - text_width/2 + left_offset)
                rect_x2 = int(rect_x1 + word_width)
                rect_y1 = int(1280 - margin_v - word_height)
                rect_y2 = int(rect_y1 + word_height)
                
                # Подложка (отдельная строка, ниже текста)
                highlight_ev = f"Dialogue: 1,{TimeFormatter.format_ass_time(start_time)},{TimeFormatter.format_ass_time(end_time)},Default,,0,0,{margin_v},,{{\\an7\\pos({rect_x1},{rect_y1})\\clip({rect_x1},{rect_y1},{rect_x2},{rect_y2})\\be{blur}\\bord0\\shad0\\1c{highlight_color}\\alpha&HFF&\\t(0,{fade_ms},\\alpha&H00&)}}{word['word'].upper()}"
                
                # Текст (поверх подложки)
                text_ev = f"Dialogue: 0,{TimeFormatter.format_ass_time(start_time)},{TimeFormatter.format_ass_time(end_time)},Default,,0,0,{margin_v},,{{\\an7\\pos({rect_x1},{rect_y1})\\bord0\\shad0\\c{color_text}}}{word['word'].upper()}"
                
                # Добавляем подложку и текст
                events.append(highlight_ev)
                events.append(text_ev)
            
            # Для паузы в начале строки — просто белый текст
            if line_idx == 0 and line_start > 0.01:
                text_parts = []
                for w in line:
                    padding = " " * max(1, (len(w['word']) * padding_percent // 100))
                    text_parts.append(w['word'].upper() + padding)
                text = ' '.join(text_parts).strip()
                ev = f"Dialogue: 0,0.00,{TimeFormatter.format_ass_time(line_start)},Default,,0,0,{margin_v},,{{\\bord0\\shad0\\c{color_text}}}{text}"
                events.append(ev)
        
        with open(ass_path, 'w', encoding='utf-8') as f:
            f.write(style_template)
            for ev in events:
                f.write(ev + "\n")


class ASSStyleFactory:
    """Фабрика для создания стилей ASS субтитров"""
    
    @staticmethod
    def create_style(style_name: str) -> ASSStyleBase:
        """Создает экземпляр стиля по имени"""
        if style_name == "highlight":
            return HighlightStyle(style_name)
        else:
            return KaraokeStyle(style_name)


class AudioFileManager:
    """Класс для управления аудио файлами"""
    
    def __init__(self, audio_dir: Path, subtitles_dir: Path):
        self.audio_dir = audio_dir
        self.subtitles_dir = subtitles_dir
    
    def find_audio_file(self, scene_num: str) -> Optional[Path]:
        """Находит аудио файл для сцены"""
        audio_path = self.audio_dir / f"scene_{scene_num}.mp3"
        
        if audio_path.exists():
            return audio_path
        else:
            return None
    
    def get_subtitle_path(self, scene_num: str) -> Path:
        """Возвращает путь для файла субтитров"""
        return self.subtitles_dir / f"scene_{scene_num}.ass"


class SubtitleGenerator:
    """Основной класс для генерации субтитров"""
    
    def __init__(self, chunks: List[Dict[str, Any]], subtitles_dir: Path, audio_dir: Path, config: Optional[SubtitleConfig] = None):
        self.config = config or SubtitleConfig()
        self.whisper_client = WhisperClient(config)
        self.chunks = chunks
        self.subtitles_dir = subtitles_dir
        self.audio_dir = audio_dir
    
    def generate(self, style_name: str = "karaoke") -> Tuple[int, int]:
        """Генерирует субтитры для всего проекта"""
        # Проверяем стиль
        if style_name not in SUBTITLE_STYLES:
            raise ValueError(f"Неизвестный стиль: {style_name}. Доступные стили: {', '.join(SUBTITLE_STYLES.keys())}")
        
        # Инициализируем менеджер файлов
        file_manager = AudioFileManager(self.audio_dir, self.subtitles_dir)
        
        # Создаем стиль
        style = ASSStyleFactory.create_style(style_name)
        
        processed_scenes = 0
        failed_scenes = 0
        
        for chunk in self.chunks:
            scene_num = str(chunk["id"]).zfill(3)
            print(f"DEBUG: Начинаю обработку сцены {scene_num}")
            
            # Находим аудио файл
            audio_path = file_manager.find_audio_file(scene_num)
            if not audio_path:
                print(f"⚠️ Аудио не найдено для сцены {scene_num}")
                failed_scenes += 1
                continue
            
            try:
                # Получаем транскрипт
                print(f"DEBUG: Отправляю аудио {audio_path} в Whisper API")
                transcript = self.whisper_client.call_whisper_with_retry(audio_path)
                
                print(f"DEBUG: transcript получен для {scene_num}")
                
                # Извлекаем слова
                words = WordProcessor.extract_words_from_transcript(transcript)
                print(f"DEBUG: words для {scene_num}: {len(words)}")
                
                if not words:
                    print(f"❌ Нет слов для {audio_path}")
                    failed_scenes += 1
                    continue
                
                # Создаем субтитры
                ass_path = file_manager.get_subtitle_path(scene_num)
                print(f"DEBUG: Генерирую ASS для {ass_path} (слов: {len(words)})")
                style.create_subtitles(words, ass_path)
                
                print(f"✅ ASS-субтитры для сцены {scene_num} сохранены: {ass_path}")
                processed_scenes += 1
                
            except Exception as e:
                print(f"❌ Ошибка при обработке сцены {scene_num}: {e}")
                failed_scenes += 1
                continue
        
        return processed_scenes, failed_scenes