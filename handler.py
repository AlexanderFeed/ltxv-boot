import os, io, tempfile
import requests
import runpod
from huggingface_hub import login
import torch
import numpy as np
from PIL import Image
from diffusers import LTXConditionPipeline, LTXLatentUpsamplePipeline
from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
from diffusers.utils import export_to_video, load_video
from diffusers.schedulers import FlowMatchEulerDiscreteScheduler
from runpod.serverless.utils import rp_upload

# HF auth (если нужен токен)
HF_TOKEN = os.getenv("HF_TOKEN")
if HF_TOKEN:
    login(token=HF_TOKEN, add_to_git_credential=False)

# Модели по умолчанию (можно переопределить в env)
BASE_MODEL = os.getenv("LTX_MODEL", "Lightricks/LTX-Video")
UPSAMPLER  = os.getenv("LTX_UPSAMPLER", "Lightricks/ltxv-spatial-upscaler-0.9.7")

dtype = torch.bfloat16
device = "cuda"

pipe = None
pipe_up = None


def init_pipes():
    """Ленивая инициализация пайплайнов"""
    global pipe, pipe_up
    if pipe is not None:
        return

    print(f"[INIT] loading base model: {BASE_MODEL}", flush=True)
    pipe = LTXConditionPipeline.from_pretrained(BASE_MODEL, torch_dtype=dtype)
    pipe.to(device)
    pipe.vae.enable_tiling()

    # 🔧 ВАРИАНТ A: отключаем dynamic shifting, чтобы не требовался mu
    try:
        if isinstance(pipe.scheduler, FlowMatchEulerDiscreteScheduler):
            pipe.scheduler.register_to_config(use_dynamic_shifting=False)
            print("[INIT] scheduler.use_dynamic_shifting = False", flush=True)
    except Exception as e:
        print("[INIT] scheduler tweak skipped:", e, flush=True)

    try:
        print(f"[INIT] loading upsampler: {UPSAMPLER}", flush=True)
        pipe_up = LTXLatentUpsamplePipeline.from_pretrained(
            UPSAMPLER, vae=pipe.vae, torch_dtype=dtype
        )
        pipe_up.to(device)
        print("[INIT] upsampler loaded", flush=True)
    except Exception as e:
        print("[INIT] upsampler skipped:", e, flush=True)
        pipe_up = None


def _round_to_vae(h, w, ratio):
    return h - (h % ratio), w - (w % ratio)


def _load_condition(init_image_url=None, init_video_url=None, h=None, w=None, num_frames=1):
    """Возвращаем LTXVideoCondition: URL-видео, URL-картинку или пустой кадр (fallback)."""
    if init_video_url:
        resp = requests.get(init_video_url, stream=True)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name
        v = load_video(tmp_path)
        return [LTXVideoCondition(video=v, frame_index=0)]

    if init_image_url:
        resp = requests.get(init_image_url, stream=True)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        frame = np.array(img)
        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "cond.mp4")
            export_to_video([frame], out_path)
            v = load_video(out_path)
        return [LTXVideoCondition(video=v, frame_index=0)]

    # Fallback: чёрный кадр нужного размера
    if h is None or w is None:
        # на всякий случай ставим дефолты
        h, w = 480, 832
    blank = np.zeros((h, w, 3), dtype=np.uint8)
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "cond_blank.mp4")
        # одного кадра достаточно, т.к. используем frame_index=0
        export_to_video([blank], out_path)
        v = load_video(out_path)
    return [LTXVideoCondition(video=v, frame_index=0)]



def handler(job):
    init_pipes()

    inp = job.get("input", {}) or {}
    print("[JOB] input keys:", list(inp.keys()), flush=True)

    prompt = inp.get("prompt", "")
    negative_prompt = inp.get("negative_prompt", "worst quality, blurry, jittery")

    height = int(inp.get("height", 480))
    width  = int(inp.get("width", 832))
    steps  = int(inp.get("steps", 30))
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
        h=h,
        w=w,
        num_frames=num_frames,
    )

    conditioning_mask = torch.zeros((1, h, w), dtype=torch.float32, device=device)

    gen = torch.Generator(device=device).manual_seed(seed)

    # Генерация в латентах
    out = pipe(
        conditions=conditions,
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=w,
        height=h,
        num_frames=num_frames,
        num_inference_steps=steps,
        generator=gen,
        output_type="latent",
        conditioning_mask=conditioning_mask,   # ← добавили
    )

    latents = out.frames

    # Апскейл (если доступен)
    if do_upsample and pipe_up is not None:
        latents = pipe_up(latents=latents, output_type="latent").frames

    # Сохраняем и грузим
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, f"{job['id']}.mp4")
        export_to_video(latents, out_path)  # imageio[ffmpeg]
        url = rp_upload.upload_file(job["id"], out_path)
        return {"video_url": url, "width": w, "height": h, "frames": len(latents)}


# safe-обёртка: вместо exit code 1 вернём traceback в output
def _safe(job):
    try:
        return handler(job)
    except Exception as e:
        import traceback, sys
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        return {"error": str(e), "traceback": tb}

runpod.serverless.start({"handler": _safe})
