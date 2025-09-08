import os, io, tempfile, requests, runpod
from huggingface_hub import login
import torch
from diffusers import (
    LTXConditionPipeline, LTXLatentUpsamplePipeline
)
from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
from diffusers.utils import export_to_video, load_image, load_video

# HF auth (если модель потребует токен/ускоренную загрузку)
HF_TOKEN = os.getenv("HF_TOKEN")
if HF_TOKEN:
    login(token=HF_TOKEN, add_to_git_credential=False)

# Модель по умолчанию (можно поменять на distilled/fp8)
BASE_MODEL = os.getenv("LTX_MODEL", "Lightricks/LTX-Video-0.9.8-dev")
UPSAMPLER  = os.getenv("LTX_UPSAMPLER", "Lightricks/ltxv-spatial-upscaler-0.9.8")

# Глобальная инициализация для тёплого старта
dtype = torch.bfloat16
device = "cuda"

pipe = LTXConditionPipeline.from_pretrained(BASE_MODEL, torch_dtype=dtype)
pipe.to(device)
pipe.vae.enable_tiling()

pipe_up = None
try:
    pipe_up = LTXLatentUpsamplePipeline.from_pretrained(UPSAMPLER, vae=pipe.vae, torch_dtype=dtype)
    pipe_up.to(device)
except Exception:
    pass  # апскейлер опционален

def _round_to_vae(h, w, ratio):
    return h - (h % ratio), w - (w % ratio)

def _load_condition(init_image_url=None, init_video_url=None):
    if init_video_url:
        v = load_video(init_video_url)
        return [LTXVideoCondition(video=v, frame_index=0)]
    if init_image_url:
        img = load_image(init_image_url)
        # модель обучена на видео — оборачиваем кадр в видео-контейнер
        v = load_video(export_to_video([img]))
        return [LTXVideoCondition(video=v, frame_index=0)]
    # Можно генерировать и без кондишна (чисто по тексту) — создадим пустой список
    return []

def handler(job):
    """Ожидаемый input:
    {
      "prompt": "text prompt",
      "negative_prompt": "optional",
      "init_image_url": "https://... (optional)",
      "init_video_url": "https://... (optional)",
      "height": 480,
      "width": 832,
      "num_frames": 96,          # кратность: 8n+1 предпочтительна (пример: 97)
      "steps": 30,
      "seed": 0,
      "upsample": true
    }
    """
    inp = job["input"]

    prompt = inp.get("prompt", "")
    negative_prompt = inp.get("negative_prompt", "worst quality, blurry, jittery")

    height = int(inp.get("height", 480))
    width  = int(inp.get("width", 832))
    steps  = int(inp.get("steps", 30))
    num_frames = int(inp.get("num_frames", 97))
    seed = int(inp.get("seed", 0))
    do_upsample = bool(inp.get("upsample", False))

    # Требования: размеры кратны 32, фреймы ~ 8n+1 — скорректируем
    h, w = _round_to_vae(height, width, pipe.vae_spatial_compression_ratio)
    if num_frames % 8 != 1:
        num_frames = (num_frames // 8) * 8 + 1

    conditions = _load_condition(
        init_image_url=inp.get("init_image_url"),
        init_video_url=inp.get("init_video_url"),
    )

    gen = torch.Generator(device=device).manual_seed(seed)

    # Генерация в латентах
    latents = pipe(
        conditions=conditions,
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=w,
        height=h,
        num_frames=num_frames,
        num_inference_steps=steps,
        generator=gen,
        output_type="latent",
    ).frames

    # Апскейл по латентам (если доступен и запрошен)
    if do_upsample and pipe_up is not None:
        latents = pipe_up(latents=latents, output_type="latent").frames

    # Декод и сохранение mp4
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, f"{job['id']}.mp4")
        export_to_video(latents, out_path)  # imageio[ffmpeg]
        # Загрузка в S3-совместимое хранилище через утилиту RunPod
        from runpod.serverless.utils import rp_upload
        # Вернёт публичный URL, если BUCKET_* настроены в endpoint
        url = rp_upload.upload_image(job["id"], out_path)
        return {"video_url": url, "width": w, "height": h, "frames": len(latents)}

runpod.serverless.start({"handler": handler})
