import os
import io
import tempfile
import requests
import runpod
import numpy as np
from PIL import Image

import torch
from diffusers import LTXConditionPipeline, LTXLatentUpsamplePipeline
from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
from diffusers.schedulers import FlowMatchEulerDiscreteScheduler
from diffusers.utils import export_to_video, load_video
from huggingface_hub import login
from runpod.serverless.utils import rp_upload


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
    """Export a single RGB frame (H,W,3) to tmp mp4 and return path."""
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "oneframe.mp4")
        export_to_video([frame_array], out_path)
        # copy to NamedTemporaryFile so the path survives context exit
        with open(out_path, "rb") as f:
            keep = _save_bytes_to_tmp(".mp4", f.read())
    return keep


def _make_blank_video(h: int, w: int) -> str:
    blank = np.zeros((h, w, 3), dtype=np.uint8)
    return _export_single_frame_video(blank)


def _cond_with_mask(video_tensor, h: int, w: int, num_frames: int):
    """
    Wrap video tensor into LTXVideoCondition and attach a neutral (zeros) mask
    to avoid None-path crashes in pipeline.
    """
    cond = LTXVideoCondition(video=video_tensor, frame_index=0)

    # Most builds expect HxW or (num_frames,H,W). Start with HxW, adjust if needed.
    mask = torch.zeros((h, w), dtype=torch.float32)
    cond.mask = mask
    return [cond]


def _load_condition(init_image_url: str | None,
                    init_video_url: str | None,
                    h: int,
                    w: int,
                    num_frames: int):
    """Return a list[LTXVideoCondition] from URLs or fallback to a blank frame video."""
    # Video URL
    if init_video_url:
        resp = requests.get(init_video_url, stream=True)
        resp.raise_for_status()
        vpath = _save_bytes_to_tmp(".mp4", resp.content)
        v = load_video(vpath)
        return _cond_with_mask(v, h, w, num_frames)

    # Image URL
    if init_image_url:
        resp = requests.get(init_image_url, stream=True)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        frame = np.array(img)
        vpath = _export_single_frame_video(frame)
        v = load_video(vpath)
        return _cond_with_mask(v, h, w, num_frames)

    # Fallback: blank video (one frame)
    vpath = _make_blank_video(h, w)
    v = load_video(vpath)
    return _cond_with_mask(v, h, w, num_frames)


# ----------------------------
# Init (lazy)
# ----------------------------
def init_pipes():
    global pipe, pipe_up
    if pipe is not None:
        return

    print(f"[INIT] loading base model: {BASE_MODEL}", flush=True)
    # use dtype=.. (torch_dtype is deprecated in newer diffusers)
    pipe = LTXConditionPipeline.from_pretrained(BASE_MODEL, dtype=dtype)
    pipe.to(device)
    if hasattr(pipe, "vae") and hasattr(pipe.vae, "enable_tiling"):
        pipe.vae.enable_tiling()

    # Variant A: disable dynamic shifting to avoid mandatory mu argument
    try:
        if isinstance(pipe.scheduler, FlowMatchEulerDiscreteScheduler):
            pipe.scheduler.register_to_config(use_dynamic_shifting=False)
            print("[INIT] scheduler.use_dynamic_shifting = False", flush=True)
    except Exception as e:
        print("[INIT] scheduler tweak skipped:", e, flush=True)

    # Optional upsampler
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

    # Generate latent video
    print("[GEN] generating latents...", flush=True)
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

    # Optional latent upsample
    if do_upsample and pipe_up is not None:
        print("[GEN] latent upsample...", flush=True)
        latents = pipe_up(latents=latents, output_type="latent").frames

    # Decode & upload
    print("[SAVE] decoding & uploading...", flush=True)
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, f"{job['id']}.mp4")
        export_to_video(latents, out_path)  # requires imageio[ffmpeg]
        url = rp_upload.upload_file(job["id"], out_path)

    print("[DONE]", url, flush=True)
    return {"video_url": url, "width": w, "height": h, "frames": len(latents)}


# Safe wrapper: return tracebacks in output instead of exit 1
def _safe(job):
    try:
        return handler(job)
    except Exception as e:
        import traceback, sys
        tb = traceback.format_exc()
        print(tb, file=sys.stderr, flush=True)
        return {"error": str(e), "traceback": tb}


runpod.serverless.start({"handler": _safe})
