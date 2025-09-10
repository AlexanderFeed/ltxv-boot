import os, io, tempfile, base64
import numpy as np
import requests
import runpod

import torch
from PIL import Image
from huggingface_hub import login

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
UPSAMPLER  = os.getenv("LTX_UPSAMPLER", "Lightricks/ltxv-spatial-upscaler-0.9.7")

device = "cuda"
dtype = torch.bfloat16

pipe = None
pipe_up = None

DEFAULT_FPS = 8  # fps для экспорта mp4

# ----------------------------
# Utils
# ----------------------------
def _round_to_vae(h: int, w: int, ratio: int):
    return h - (h % ratio), w - (w % ratio)

def _save_bytes_to_tmp(ext: str, content: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        return tmp.name

def _cond_with_mask(video_tensor, h: int, w: int, num_frames: int):
    """
    Создаёт LTXVideoCondition и проставляет маску в латентном масштабе.
    ВАЖНО: эту функцию вызываем только если действительно есть conditioning.
    """
    cond = LTXVideoCondition(video=video_tensor, frame_index=0)

    # размерность в латентном масштабе
    ratio = getattr(pipe, "vae_spatial_compression_ratio", 32)
    h_lat, w_lat = max(1, h // ratio), max(1, w // ratio)

    # mask формы (T, 1, H_lat, W_lat). 0 — «не шумить» (сильнее учитывать conditioning)
    mask = torch.zeros((num_frames, 1, h_lat, w_lat), dtype=torch.float32)
    cond.conditioning_mask = mask
    cond.mask = mask

    return [cond]

def _repeat_image_to_video(img: Image.Image, num_frames: int, fps: int = DEFAULT_FPS) -> str:
    frames = [img] * num_frames
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "cond.mp4")
        export_to_video(frames, out_path, fps=fps)
        with open(out_path, "rb") as f:
            return _save_bytes_to_tmp(".mp4", f.read())

def _load_condition(init_image_url, init_video_url, h, w, num_frames):
    """
    Возвращает список conditions или None (если conditioning нет).
    """
    if init_video_url:
        resp = requests.get(init_video_url, stream=True); resp.raise_for_status()
        vpath = _save_bytes_to_tmp(".mp4", resp.content)
        v = load_video(vpath)
        return _cond_with_mask(v, h, w, num_frames)

    if init_image_url:
        resp = requests.get(init_image_url, stream=True); resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        vpath = _repeat_image_to_video(img, num_frames)
        v = load_video(vpath)
        return _cond_with_mask(v, h, w, num_frames)

    # conditioning отсутствует — возвращаем None и НЕ передаём conditions в пайплайн
    return None

def _to_hwc_uint8(frame):
    import numpy as _np
    from PIL import Image as _PILImage

    if isinstance(frame, _PILImage.Image):
        frame = _np.array(frame)
    if isinstance(frame, torch.Tensor):
        f = frame.detach().cpu().numpy()
    else:
        f = _np.asarray(frame)
    f = _np.squeeze(f)

    if f.ndim == 2:
        f = f[:, :, None]
    elif f.ndim == 3 and f.shape[0] in (1, 3, 4):
        # (C,H,W) -> (H,W,C)
        f = _np.transpose(f, (1, 2, 0))

    if _np.issubdtype(f.dtype, _np.floating):
        f = (_np.clip(f, -1, 1) + 1.0) * 127.5
        f = _np.round(f).astype(_np.uint8)
    elif f.dtype != _np.uint8:
        f = _np.clip(f, 0, 255).astype(_np.uint8)

    if f.ndim == 3 and f.shape[2] == 1:
        f = _np.repeat(f, 3, axis=2)
    if f.ndim == 3 and f.shape[2] > 4:
        f = f[:, :, :3]
    return f

# ----------------------------
# Init (lazy)
# ----------------------------
def init_pipes():
    global pipe, pipe_up
    if pipe is not None:
        return

    print(f"[INIT] loading base model: {BASE_MODEL}", flush=True)
    pipe = LTXConditionPipeline.from_pretrained(BASE_MODEL, torch_dtype=dtype)
    pipe.to(device)
    if hasattr(pipe, "vae") and hasattr(pipe.vae, "enable_tiling"):
        pipe.vae.enable_tiling()

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
    width  = int(inp.get("width", 832))
    steps  = int(inp.get("steps", 30))
    num_frames = int(inp.get("num_frames", 41))
    seed = int(inp.get("seed", 0))
    do_upsample = bool(inp.get("upsample", False))

    ratio = getattr(pipe, "vae_spatial_compression_ratio", 32)
    h, w = _round_to_vae(height, width, ratio)
    if num_frames % 8 != 1:
        num_frames = (num_frames // 8) * 8 + 1

    # --- conditioning (image or video)
    media_path = None
    if inp.get("init_image_url"):
        resp = requests.get(inp["init_image_url"], stream=True); resp.raise_for_status()
        media_path = _save_bytes_to_tmp(".png", resp.content)
    elif inp.get("init_video_url"):
        resp = requests.get(inp["init_video_url"], stream=True); resp.raise_for_status()
        media_path = _save_bytes_to_tmp(".mp4", resp.content)

    gen = torch.Generator(device=device).manual_seed(seed)

    kwargs = dict(
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=w,
        height=h,
        num_frames=num_frames,
        num_inference_steps=steps,
        generator=gen,
    )

    if media_path:
        v = load_video(media_path)
        kwargs["conditions"] = _cond_with_mask(v, h, w, num_frames)


    print(f"[GEN] num_frames requested: {num_frames}", flush=True)
    print("[GEN] generating...", flush=True)

    if do_upsample and pipe_up is not None:
        out = pipe(**kwargs, output_type="latent")
        latents = out.frames

        print("[GEN] latent upsample...", flush=True)
        latents = pipe_up(latents=latents, output_type="latent").frames

        # decode latents -> numpy
        with torch.no_grad():
            if isinstance(latents, list):
                latents = torch.stack(latents, dim=0)
            if latents.dim() == 4:
                latents = latents.unsqueeze(0)  # (1, C, T, H, W)
            vae_dtype = next(pipe.vae.parameters()).dtype
            latents = latents.to(device=device, dtype=vae_dtype)
            scal = getattr(pipe.vae.config, "scaling_factor", 0.18215)
            imgs = pipe.vae.decode(latents / scal).sample
            imgs = (imgs.clamp(-1, 1) + 1) / 2
            imgs = (imgs * 255).round().to(torch.uint8)
            imgs = imgs.squeeze(0).permute(1, 2, 3, 0).cpu().numpy()
            frames = [f for f in imgs]
    else:
        out = pipe(**kwargs, output_type="np")
        frames = out.frames

    # --- convert to list of HWC uint8
    if isinstance(frames, np.ndarray):
        if frames.ndim == 5 and frames.shape[0] == 1:
            frames = frames[0]
        if frames.ndim == 4:
            frames_iter = [frames[i] for i in range(frames.shape[0])]
        elif frames.ndim == 3:
            frames_iter = [np.repeat(frames[i, :, :, None], 3, axis=2) for i in range(frames.shape[0])]
        else:
            raise ValueError(f"Unexpected frame shape: {frames.shape}")
    else:
        frames_iter = frames

    frames_norm = [_to_hwc_uint8(fr) for fr in frames_iter]
    print("[DEBUG] first frame shape:", frames_norm[0].shape, frames_norm[0].dtype, flush=True)

    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, f"{job['id']}.mp4")
        export_to_video(frames_norm, out_path, fps=DEFAULT_FPS)
        with open(out_path, "rb") as f:
            video_bytes = f.read()

    video_b64 = base64.b64encode(video_bytes).decode("ascii")
    data_url = f"data:video/mp4;base64,{video_b64}"
    print(f"[VIDEO DATA-URL] {data_url[:120]}... (len={len(data_url)})", flush=True)

    return {
        "video_data_url": data_url,
        "mime": "video/mp4",
        "width": w,
        "height": h,
        "frames": len(frames_norm),
    }


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
