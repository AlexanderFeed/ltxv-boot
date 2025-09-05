from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import base64
import os
from celery.result import AsyncResult
from my_celery import celery_app

app = FastAPI()

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/generate")
async def generate(
    prompt: str = Form(...),
    negative_prompt: str = Form("worst quality, inconsistent motion, blurry, jittery, distorted"),
    expected_height: int = Form(512),
    expected_width: int = Form(704),
    num_frames: int = Form(96),
    seed: int = Form(42),
    image: UploadFile = File(None),
):
    image_base64 = None
    if image is not None:
        image_bytes = await image.read()
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    
    # Отправляем задачу через Celery клиент
    task = celery_app.send_task(
        'celery_task.generate_video_inference_task',
        args=[prompt, negative_prompt, image_base64, expected_width, expected_height, num_frames, seed]
    )
    return {"task_id": task.id}

@app.get("/status/{task_id}")
async def get_task_status(task_id: str):
    """Получить статус задачи"""
    task_result = AsyncResult(task_id, app=celery_app)
    return {
        "task_id": task_id,
        "status": task_result.status,
        "result": task_result.result if task_result.ready() else None
    }

@app.get("/video/{filename:path}")
async def get_video(filename: str):
    """Получить видео файл"""
    file_path = os.path.join(os.getcwd(), filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Видео файл не найден")
    
    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=os.path.basename(filename)
    )

@app.get("/")
async def root():
    """Корневой endpoint"""
    return {"message": "LTX-Video API работает! Используйте /docs для документации"} 