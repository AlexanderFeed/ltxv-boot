#!/usr/bin/env python3
"""
Мини‑тест вашего метода `generate_image_local`.

❯ python test_local_flux.py -p "blue car" -f long -o blue.png
"""

import argparse, random, requests
from pathlib import Path

def generate_image_local(prompt: str, video_format: str = "long") -> bytes:
    """Грубая копия вашей функции ― возвращает raw‑байты PNG."""
    seed = random.randint(1, 100_000)
    print(f"🖼️  Запрос: '{prompt}'  seed={seed}  format={video_format}")

    # 1) /generate
    params = {"prompt": prompt, "seed": seed, "format": video_format}
    resp = requests.get("http://localhost:8000/generate", params=params, timeout=300)
    resp.raise_for_status()

    # 2) берём относительный путь к картинке
    rel_path = resp.json()["file"].lstrip("/")           # без ведущего /
    img_url  = f"http://localhost:8000/{rel_path}"

    # 3) скачиваем png‑байты
    img_bytes = requests.get(img_url, timeout=300).content
    if not img_bytes:
        raise RuntimeError("Пустой ответ от /static")

    return img_bytes

def main():
    parser = argparse.ArgumentParser(description="Тест локальной генерации через FastAPI‑service")
    parser.add_argument("-p", "--prompt", default="blue car", help="Текстовый промпт")
    parser.add_argument("-f", "--format", default="long", choices=["long", "shorts"], help="Формат")
    parser.add_argument("-o", "--output", type=Path, default=Path("out.png"), help="Имя png‑файла")
    args = parser.parse_args()

    png_bytes = generate_image_local(args.prompt, args.format)
    args.output.write_bytes(png_bytes)
    print(f"✓  Сохранено {args.output.resolve()}  ({len(png_bytes):,} bytes)")

if __name__ == "__main__":
    main()
