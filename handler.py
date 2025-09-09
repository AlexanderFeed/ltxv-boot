import os
import io
import tempfile
import numpy as np
import requests
import runpod

import torch
from PIL import Image
from huggingface_hub import login
from runpod.serverless.utils import rp_upload

from diffusers import LTXConditionPipeline, LTXLatentUpsamplePipeline
from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
from diffusers.schedulers import FlowMatchEulerDiscreteScheduler
from diffusers.utils import export_to_video, load_video


# ----------------------------
# Auth / Config
# ----------------------------
HF_TOKEN = os.getenv("HF_TOKEN")
if HF_TOKEN:
    login(token=HF_TOKEN, add_to_git_credential=False)

BASE_MODEL = os.getenv("LTX_MODEL", "Lightricks/LTX-Video")
UPSAMPLER = os.getenv("LTX_UPSAMPLER", "Lightricks/ltxv-spatial-upscaler-0.9.7")

device = "cuda"
dtype = torch.bfloat16

pipe = None
pipe_up = None


# ----------------------------
# Utils
# ----------------------------
def _round_to_vae(h: int, w: int, ratio: int):
    return h - (h % ratio), w - (w % ratio)


def _save_bytes_to_tmp(ext: str, content: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        return tmp.name


def _export_single_frame_video(frame_array: np.ndarray) -> str:
    """Export a single RGB frame (H,W,3) to tmp mp4 and return path that survives."""
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "oneframe.mp4")
        export_to_video([frame_array], out_path)
        with open(out_path, "rb") as f:
            keep = _save_bytes_to_tmp(".mp4", f.read())
    return keep


def _make_blank_video(h: int, w: int) -> str:
    blank = np.zeros((h, w, 3), dtype=np.uint8)
    return _export_single_frame_video(blank)


def _cond_with_mask(video_tensor, h: int, w: int, num_frames: int):
    """
    Wrap video tensor into LTXVideoCondition and attach a neutral zero mask
    to avoid None-path crashes inside the pipeline.
    """
    cond = LTXVideoCondition(video=video_tensor, frame_index=0)
    # Базовая форма маски: (H, W). Если ревизия попросит иную форму —
    # поменять на (1, H, W) или (num_frames, H, W).
    cond.mask = torch.zeros((h, w), dtype=torch.float32)
    return [cond]


def _load_condition(init_image_url: str | None,
                    init_video_url: str | None,
                    h: int,
                    w: int,
                    num_frames: int):
    """Return a list[LTXVideoCondition] from URLs or fallback to a blank frame video."""
    # Видео по URL
    if init_video_url:
        resp = requests.get(init_video_url, stream=True)
        resp.raise_for_status()
        vpath = _save_bytes_to_tmp(".mp4", resp.content)
        v = load_video(vpath)
        return _cond_with_mask(v, h, w, num_frames)

    # Картинка по URL
    if init_image_url:
        resp = requests.get(init_image_url, stream=True)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        frame = np.array(img)
        vpath = _export_single_frame_video(frame)
        v = load_video(vpath)
        return _cond_with_mask(v, h, w, num_frames)

    # Fallback: пустой кадр нужного размера
    vpath = _make_blank_video(h, w)
    v = load_video(vpath)
    return _cond_with_mask(v, h, w, num_frames)


def _to_hwc_uint8(frame):
    """Нормализация кадра к HxWxC uint8 (C = 3) перед export_to_video."""
    import numpy as _np
    from PIL import Image as _PILImage

    # PIL -> np
    if isinstance(frame, _PILImage.Image):
        frame = _np.array(frame)

    # torch -> np
    if isinstance(frame, torch.Tensor):
        f = frame.detach().cpu().numpy()
    else:
        f = _np.asarray(frame)

    # squeeze лишнее
    f = _np.squeeze(f)

    # Привести к HWC:
    if f.ndim == 2:
        # H, W -> H, W, 1
        f = f[:, :, None]
    elif f.ndim == 3:
        # если формат C,H,W — перенесём в H,W,C
        if f.shape[0] in (1, 3, 4) and (f.shape[1] != f.shape[-2] or f.shape[2] != f.shape[-1]):
            f = _np.transpose(f, (1, 2, 0))
    else:
        # неожиданные формы — сведём к одноканальной
        f = f.reshape(f.shape[0], f.shape[1], -1)[:, :, :1]

    # Нормализация значений -> uint8
    if _np.issubdtype(f.dtype, _np.floating):
        f_min, f_max = f.min(), f.max()
        # поддержка [-1,1] и [0,1]
        if f_min >= -1.0 - 1e-3 and f_max <= 1.0 + 1e-3:
            f = (_np.clip(f, -1, 1) + 1.0) * 127.5
        else:
            f = _np.clip(f, 0.0, 255.0)
        f = _np.round(f).astype(_np.uint8)
    elif f.dtype != _np.uint8:
        f = _np.clip(f, 0, 255).astype(_np.uint8)

    # Если одноканальная — дублируем до 3 каналов
    if f.shape[2] == 1:
        f = _np.repeat(f, 3, axis=2)

    # Обрежем лишние каналы >4
    if f.shape[2] > 4:
        f = f[:, :, :3]

    return f


def _s3_upload(local_path: str, filename: str) -> str:
    """
    Резервная загрузка в S3-совместимое хранилище через boto3.
    Требуются env:
      BUCKET_NAME (обязательно)
      AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (или IAM роль)
      BUCKET_ENDPOINT (если не AWS S3)
      AWS_DEFAULT_REGION (если нужно)
      PUBLIC_BASE_URL (опционально, если бакет публичный)
    """
    import boto3

    bucket = os.environ["BUCKET_NAME"]
    key = f"ltx/{filename}"
    endpoint = os.getenv("BUCKET_ENDPOINT")
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

    s3 = boto3.client("s3", endpoint_url=endpoint, region_name=region)
    s3.upload_file(
        local_path,
        bucket,
        key,
        ExtraArgs={"ContentType": "video/mp4", "ACL": "public-read"},
    )

    public_base = os.getenv("PUBLIC_BASE_URL")
    if public_base:
        return f"{public_base.rstrip('/')}/{key}"
    # иначе вернем presigned URL на 7 дней
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=7 * 24 * 3600,
    )


# ----------------------------
# Init (lazy)
# ----------------------------
def init_pipes():
    global pipe, pipe_up
    if pipe is not None:
        return

    print(f"[INIT] loading base model: {BASE_MODEL}", flush=True)
    # В новых diffusers предпочтительнее dtype=...
    pipe = LTXConditionPipeline.from_pretrained(BASE_MODEL, dtype=dtype)
    pipe.to(device)
    if hasattr(pipe, "vae") and hasattr(pipe.vae, "enable_tiling"):
        pipe.vae.enable_tiling()

    # Вариант A: отключить dynamic shifting (не требовать 'mu')
    try:
        if isinstance(pipe.scheduler, FlowMatchEulerDiscreteScheduler):
            pipe.scheduler.register_to_config(use_dynamic_shifting=False)
            print("[INIT] scheduler.use_dynamic_shifting = False", flush=True)
    except Exception as e:
        print("[INIT] scheduler tweak skipped:", e, flush=True)

    # Опциональный апскейлер
    try:
        print(f"[INIT] loading upsampler: {UPSAMPLER}", flush=True)
        pipe_up = LTXLatentUpsamplePipeline.from_pretrained(
            UPSAMPLER, vae=pipe.vae, dtype=dtype
        )
        pipe_up.to(device)
        print("[INIT] upsampler loaded", flush=True)
    except Exception as e:
        pipe_up = None
        print("[INIT] upsampler skipped:", e, flush=True)


# ----------------------------
# Handler
# ----------------------------
def handler(job):
    init_pipes()

    inp = job.get("input", {}) or {}
    print("[JOB] input keys:", list(inp.keys()), flush=True)

    prompt = inp.get("prompt", "")
    negative_prompt = inp.get("negative_prompt", "worst quality, blurry, jittery")

    height = int(inp.get("height", 480))
    width = int(inp.get("width", 832))
    steps = int(inp.get("steps", 30))
    num_frames = int(inp.get("num_frames", 97))
    seed = int(inp.get("seed", 0))
    do_upsample = bool(inp.get("upsample", False))

    # enforce sizes / frames
    ratio = getattr(pipe, "vae_spatial_compression_ratio", 32)
    h, w = _round_to_vae(height, width, ratio)
    if num_frames % 8 != 1:
        num_frames = (num_frames // 8) * 8 + 1

    # conditions (image/video/fallback) + mask inside
    conditions = _load_condition(
        init_image_url=inp.get("init_image_url"),
        init_video_url=inp.get("init_video_url"),
        h=h, w=w, num_frames=num_frames,
    )

    gen = torch.Generator(device=device).manual_seed(seed)

    # --- Генерация / декодирование ---
    print("[GEN] generating...", flush=True)

    if do_upsample and pipe_up is not None:
        # 1) генерим латенты
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
        )
        latents = out.frames

        # 2) апскейлим в латентах
        print("[GEN] latent upsample...", flush=True)
        latents = pipe_up(latents=latents, output_type="latent").frames

        # 3) декодируем латенты в пиксели (numpy)
        print("[GEN] decoding latents...", flush=True)
        try:
            frames = pipe.decode_latents(latents)  # список np.ndarray (H,W,3) [0..255]
        except Exception:
            with torch.no_grad():
                t = latents
                if isinstance(t, list):
                    t = torch.stack(t, dim=0)
                t = t.to(device=device, dtype=torch.float32)
                if t.dim() == 5:
                    b, tt, c, hh, ww = t.shape
                    t = t.reshape(b * tt, c, hh, ww)
                scal = getattr(getattr(pipe, "vae", object), "config", object).__dict__.get("scaling_factor", 0.18215)
                imgs = pipe.vae.decode(t / scal).sample
                imgs = (imgs.clamp(-1, 1) + 1) / 2
                imgs = (imgs * 255).round().to(torch.uint8).permute(0, 2, 3, 1).cpu().numpy()
                frames = [f for f in imgs]
    else:
        # Без апскейла — сразу просим numpy-кадры
        out = pipe(
            conditions=conditions,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=w,
            height=h,
            num_frames=num_frames,
            num_inference_steps=steps,
            generator=gen,
            output_type="np",
        )
        frames = out.frames  # список np.ndarray

    # Нормализация кадров к HxWxC uint8
    frames_norm = [_to_hwc_uint8(fr) for fr in frames]

    # --- Сохранение и загрузка ---
    print("[SAVE] writing & uploading...", flush=True)
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, f"{job['id']}.mp4")
        export_to_video(frames_norm, out_path)  # imageio[ffmpeg]

        # сначала пробуем штатный ранпод-аплоад
        try:
            url = rp_upload.upload_image(f"{job['id']}.mp4", out_path)
        except Exception as e:
            print("[SAVE] rp_upload.upload_image failed, falling back to boto3:", e, flush=True)
            url = _s3_upload(out_path, filename=f"{job['id']}.mp4")

    print("[DONE]", url, flush=True)
    return {"video_url": url, "width": w, "height": h, "frames": len(frames_norm)}


# ----------------------------
# Safe wrapper
# ----------------------------
def _safe(job):
    try:
        return handler(job)
    except Exception as e:
        import traceback, sys
        tb = traceback.format_exc()
        print(tb, file=sys.stderr, flush=True)
        return {"error": str(e), "traceback": tb}


runpod.serverless.start({"handler": _safe})
