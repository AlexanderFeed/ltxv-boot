#!/usr/bin/env python3
"""
Тестовый файл для функции merge_audio_files
Использование: python test_merge_audio.py <путь_к_папке_с_аудио>
"""

import sys
import os
import re
from pathlib import Path
from pydub import AudioSegment


def extract_number(filename):
    """Функция для извлечения номера из имени файла"""
    match = re.search(r"(\d+)", filename)
    return int(match.group(1)) if match else -1


def merge_audio_files(audio_dir: Path, output_filename: str = "merged_output.mp3") -> str:
    """Объединяет все аудиофайлы в один файл"""
    if not audio_dir.exists():
        raise FileNotFoundError(f"Папка с аудиофайлами не найдена: {audio_dir}")
    
    # Получаем и сортируем файлы по номеру
    files = sorted(
        [f for f in os.listdir(audio_dir) if f.endswith(".mp3")],
        key=extract_number
    )
    
    if not files:
        raise FileNotFoundError(f"Аудиофайлы не найдены в папке: {audio_dir}")
    
    print(f"📁 Найдено {len(files)} аудиофайлов:")
    for i, filename in enumerate(files, 1):
        print(f"  {i}. {filename}")
    
    # Объединение
    combined = AudioSegment.empty()
    for filename in files:
        file_path = audio_dir / filename
        print(f"🎵 Обрабатываю файл: {filename}")
        audio = AudioSegment.from_file(str(file_path))
        combined += audio
    
    # Сохраняем объединенный файл
    output_path = audio_dir / output_filename
    combined.export(str(output_path), format="mp3", bitrate="192k")
    
    print(f"✅ Объединено {len(files)} файлов в {output_path}")
    print(f"📊 Размер итогового файла: {output_path.stat().st_size / 1024 / 1024:.2f} МБ")
    return str(output_path)


def main():
    """Основная функция"""
    if len(sys.argv) != 2:
        print("❌ Ошибка: Необходимо указать путь к папке с аудиофайлами")
        print("Использование: python test_merge_audio.py <путь_к_папке>")
        print("Пример: python3 -m autovid.backend.tests.test_merge_audio assets/audio/123")
        sys.exit(1)
    
    audio_dir_path = Path(sys.argv[1])
    
    try:
        print(f"🚀 Начинаю объединение аудиофайлов из папки: {audio_dir_path}")
        result_path = merge_audio_files(audio_dir_path)
        print(f"🎉 Успешно! Объединенный файл: {result_path}")
        
    except FileNotFoundError as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 