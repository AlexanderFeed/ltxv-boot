import os
import uuid
import json
import time
from pathlib import Path
from celery import shared_task

@shared_task(name="celery_task.generate_video_inference_task")
def generate_video_inference_task(
    prompt,
    negative_prompt=None,
    image_base64=None,
    width=1280,
    height=720,
    num_frames=120,
    seed=0,
    output_path=None
):
    """Генерируем видео через inference демон"""
    print(f"🎬 Начинаем генерацию через inference демон...")
    print(f"📝 Промпт: {prompt}")
    print(f"📏 Разрешение: {width}x{height}")
    print(f"🎞️ Кадры: {num_frames}")
    print(f"🎲 Seed: {seed}")
    
    # Сохраняем изображение если передано в base64
    image_path = None
    if image_base64:
        import base64
        from PIL import Image
        import io
        
        # Декодируем base64
        image_data = base64.b64decode(image_base64.split(',')[1] if ',' in image_base64 else image_base64)
        image = Image.open(io.BytesIO(image_data))
        
        # Конвертируем в RGB если нужно (для JPEG)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Сохраняем временный файл
        image_path = f"temp_image_{uuid.uuid4().hex}.jpg"
        image.save(image_path)
        print(f"💾 Изображение сохранено: {image_path}")
    else:
        # Для text-to-video режима не используем изображение
        image_path = None
    
    # Создаем уникальный ID для команды
    command_id = uuid.uuid4().hex
    command_file = f"inference_commands/command_{command_id}.json"
    result_file = f"inference_commands/result_{command_id}.json"
    
    # Создаем команду для демона
    command = {
        'prompt': prompt,
        'negative_prompt': negative_prompt or "worst quality, inconsistent motion, blurry, jittery, distorted",
        'image_path': image_path,
        'height': height,
        'width': width,
        'num_frames': num_frames,
        'seed': seed,
        'output_path': output_path
    }
    
    # Создаем папку для команд
    os.makedirs("inference_commands", exist_ok=True)
    
    # Сохраняем команду
    with open(command_file, 'w') as f:
        json.dump(command, f)
    
    print(f"📤 Отправляем команду демону: {command_file}")
    
    # Ждем результат от демона
    max_wait_time = 3600  # 1 час
    start_time = time.time()
    
    while time.time() - start_time < max_wait_time:
        if os.path.exists(result_file):
            try:
                # Читаем результат
                with open(result_file, 'r') as f:
                    result_data = json.load(f)
                
                # Удаляем файл результата
                os.remove(result_file)
                
                if result_data['status'] == 'success':
                    print("✅ Генерация завершена успешно!")
                    
                    # Копируем результат в task_results
                    video_path = result_data['result']
                    final_path = f"task_results/result_{uuid.uuid4().hex}.mp4"
                    os.makedirs("task_results", exist_ok=True)
                    
                    import shutil
                    shutil.copy2(video_path, final_path)
                    
                    # Удаляем временное изображение
                    if image_path and image_path.startswith("temp_image_"):
                        os.remove(image_path)
                    
                    return final_path
                else:
                    raise Exception(f"Ошибка в демоне: {result_data['error']}")
                    
            except Exception as e:
                print(f"❌ Ошибка чтения результата: {e}")
                raise e
        
        time.sleep(2)  # Проверяем каждые 2 секунды
    
    # Таймаут
    raise Exception("Таймаут ожидания результата от демона") 