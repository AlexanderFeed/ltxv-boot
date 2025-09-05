from .pipeline import pipe
import torch
from pathlib import Path

def generate_image(prompt: str, seed: int = 42, filename: str = "output.png", format: str = "long"):
    generator = torch.Generator("cuda").manual_seed(seed)

    # Определяем размеры в зависимости от формата
    if format == "shorts":
        # Вертикальный формат 9:16 (1080x1920) - Full HD
        width = 720
        height = 1280
        steps = 17
    else:
        # Горизонтальный формат 16:9 (1920x1080) - Full HD
        width = 1280
        height = 720
        steps = 17

    # Сброс состояния FORA cache
    if hasattr(pipe, 'cache_helper'):
        pipe.cache_helper.step = 0
        pipe.cache_helper.cache_schedule = pipe.cache_helper.get_cache_schedule(steps)

    # Генерируем изображение с PrunaAI моделью
    result = pipe(
        prompt,
        height=height,
        width=width,
        guidance_scale=3.5,
        num_inference_steps=steps,
        generator=generator
    )

    # Извлекаем изображение из результата PrunaAI
    if hasattr(result, 'images') and len(result.images) > 0:
        image = result.images[0]
    elif hasattr(result, 'image'):
        image = result.image
    else:
        raise ValueError(f"Неожиданная структура результата PrunaAI: {type(result)}")

    # Сохраняем изображение
    out_path = Path("flux_service/static") / filename
    image.save(out_path)
    return str(out_path)