"""
chunker.py
----------
Делит текст сценария на фрагменты длиной ~6‑8 секунд озвучки,
при этом не разрывает предложения и избегает слишком коротких кусков.
Поддерживает разные форматы: long (16:9) и shorts (9:16).
Объектно-ориентированная версия.
"""
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

from autovid.backend.config import CHAR_PER_SEC, VIDEO_FORMATS, CHUNKER_CONFIG

@dataclass
class ChunkConfig:
    """Конфигурация для разбиения текста на чанки"""
    video_format: str = "long"
    max_len: Optional[int] = None
    min_len: Optional[int] = None
    
    def __post_init__(self):
        if self.max_len is None or self.min_len is None:
            self.max_len, self.min_len = self._get_chunk_params()
    
    def _get_chunk_params(self) -> Tuple[int, int]:
        """Возвращает параметры чанков для указанного формата"""
        format_params = VIDEO_FORMATS.get(self.video_format, VIDEO_FORMATS["long"])
        chunk_sec = format_params["CHUNK_SEC"]
        max_len = CHAR_PER_SEC * chunk_sec
        min_sec = CHUNKER_CONFIG["min_chunk_seconds"].get(self.video_format, 4)
        min_len = CHAR_PER_SEC * min_sec
        return max_len, min_len


class TextProcessor:
    """Класс для обработки текста"""
    
    @staticmethod
    def split_into_sentences(text: str) -> List[str]:
        """Делим текст на предложения по знакам . ! ?"""
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        return [s for s in sentences if s]


class ChunkMerger:
    """Класс для объединения коротких чанков"""
    
    @staticmethod
    def merge_short_chunks(blocks: List[str], min_len: int) -> List[str]:
        """Объединяет короткие блоки с соседними"""
        merged: List[str] = []
        i = 0
        
        while i < len(blocks):
            chunk = blocks[i]
            if len(chunk) < min_len and i + 1 < len(blocks):
                blocks[i + 1] = f"{chunk} {blocks[i + 1]}".strip()
            else:
                merged.append(chunk)
            i += 1

        # Обрабатываем последний блок
        if merged and len(merged) > 1 and len(merged[-1]) < min_len:
            merged[-2] = f"{merged[-2]} {merged[-1]}".strip()
            merged.pop()

        return merged


class ScriptChunker:
    """Основной класс для разбиения сценария на чанки"""
    
    def __init__(self, config: Optional[ChunkConfig] = None):
        self.config = config or ChunkConfig()
        self.text_processor = TextProcessor()
        self.chunk_merger = ChunkMerger()
    
    def chunk_script(self, text: str) -> List[Dict[str, Any]]:
        """
        Возвращает список словарей с id и текстом.
        Поддерживает разные форматы: long (16:9) и shorts (9:16).
        """
        blocks: List[str] = []
        current: List[str] = []
        length = 0

        for sent in self.text_processor.split_into_sentences(text):
            if length + len(sent) <= self.config.max_len:
                current.append(sent)
                length += len(sent)
            else:
                blocks.append(" ".join(current))
                current = [sent]
                length = len(sent)

        if current:
            blocks.append(" ".join(current))

        # Склейка коротких блоков
        merged = self.chunk_merger.merge_short_chunks(blocks, self.config.min_len)

        return [{"id": idx + 1, "text": chunk} for idx, chunk in enumerate(merged)]

class ChunkingManager:
    """Основной класс для управления процессом разбиения"""
    
    def __init__(self, project_id: int, video_format: str = "long", script: str = None):
        self.project_id = project_id
        self.config = ChunkConfig(video_format=video_format)
        self.chunker = ScriptChunker(self.config)
        self.script = script
    
    def generate(self) -> List[Dict[str, Any]]:
        """Обрабатывает сценарий и возвращает чанки"""  
        if not self.script:
            raise ValueError("Сценарий не задан")
        
        chunks = self.chunker.chunk_script(self.script)
        
        return chunks
