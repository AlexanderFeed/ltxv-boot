import os, io, tempfile 
import requests 
import runpod
from huggingface_hub import login
import torch
from PIL import Image
from diffusers import (
    LTXConditionPipeline, LTXLatentUpsamplePipeline
)
from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
from diffusers.utils import export_to_video, load_video

from runpod.serverless.utils import rp_upload

# HF auth (если нужен токен)
HF_TOKEN = os.getenv("HF_TOKEN")
if HF_TOKEN:
    login(token=HF_TOKEN, add_to_git_credential=False)

# Модель по умолчанию
BASE_MODEL = os.getenv("LTX_MODEL", "Lightricks/LTX-Video-0.9.8-dev")
UPSAMPLER  = os.getenv("LTX_UPSAMPLER", "Lightricks/ltxv-spatial-upscaler-0.9.8")

dtype = torch.bfloat16
device = "cuda"

pipe = None
pipe_up = None


def init_pipes():
    """Ленивая инициализация пайплайнов"""
    global pipe, pipe_up
    if pipe is None:
        pipe = LTXConditionPipeline.from_pretrained(BASE_MODEL, torch_dtype=dtype)
        pipe.to(device)
        pipe.vae.enable_tiling()

        try:
            pipe_up = LTXLatentUpsamplePipeline.from_pretrained(
                UPSAMPLER, vae=pipe.vae, torch_dtype=dtype
            )
            pipe_up.to(device)
        except Exception:
            pipe_up = None


def _round_to_vae(h, w, ratio):
    return h - (h % ratio), w - (w % ratio)


def _load_condition(init_image_url=None, init_video_url=None):
    """Скачиваем картинку/видео по URL и конвертим в LTXVideoCondition"""
    if init_video_url:
        resp = requests.get(init_video_url, stream=True)
        resp.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        with open(tmp.name, "wb") as f:
            f.write(resp.content)
        v = load_video(tmp.name)
        return [LTXVideoCondition(video=v, frame_index=0)]

    if init_image_url:
        resp = requests.get(init_image_url, stream=True)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(tmp.name)
        v = load_video(export_to_video([img]))
        return [LTXVideoCondition(video=v, frame_index=0)]

    return []


def handler(job):
    """Основной handler"""
    init_pipes()  # лениво загружаем модель

    inp = job["input"]

    prompt = inp.get("prompt", "")
    negative_prompt = inp.get("negative_prompt", "worst quality, blurry, jittery")

    height = int(inp.get("height", 480))
    width = int(inp.get("width", 832))
    steps = int(inp.get("steps", 30))
    num_frames = int(inp.get("num_frames", 97))
    seed = int(inp.get("seed", 0))
    do_upsample = bool(inp.get("upsample", False))

    # Требования: размеры кратны 32, фреймы ~ 8n+1
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

    # Апскейл
    if do_upsample and pipe_up is not None:
        latents = pipe_up(latents=latents, output_type="latent").frames

    # Сохраняем и грузим
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, f"{job['id']}.mp4")
        export_to_video(latents, out_path)  # imageio[ffmpeg]

        url = rp_upload.upload_file(job["id"], out_path)
        return {"video_url": url, "width": w, "height": h, "frames": len(latents)}


runpod.serverless.start({"handler": handler})
