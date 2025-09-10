import os
import io
import base64
import uuid
from PIL import Image

import torch
from celery import Celery
from diffusers import LTXConditionPipeline, LTXLatentUpsamplePipeline
from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
from diffusers.utils import export_to_video, load_image, load_video
from my_celery import celery_app, get_models, load_models_on_startup

def round_to_nearest_resolution_acceptable_by_vae(height, width, pipe):
    """Округляет размеры до ближайших, приемлемых для VAE."""
    # Используем реальные значения VAE
    spatial_compression_ratio = pipe.vae.spatial_compression_ratio
    height = height - (height % spatial_compression_ratio)
    width = width - (width % spatial_compression_ratio)
    return height, width

@celery_app.task(name="celery_task.generate_video_task")
def generate_video_task(
    prompt, 
    negative_prompt=None, 
    image_base64=None, 
    width=720, 
    height=1280, 
    num_frames=121, 
    seed=0,
    
    # Параметры генерации
    num_inference_steps=50,
    denoise_strength=0.3,
    decode_timestep=0.05,
    image_cond_noise_scale=0.025,
    
    # Параметры downscale/upscale
    downscale_factor=0.67,
    upscale_factor=2.0,
    
    # Параметры финального денойза
    final_num_inference_steps=10,
    
    # Параметры VAE
    vae_spatial_compression_ratio=32,
    vae_temporal_compression_ratio=8,
    
    # Параметры Transformer
    transformer_num_attention_heads=32,
    transformer_num_layers=48,
    transformer_attention_head_dim=128,
    
    # Параметры Scheduler
    scheduler_num_train_timesteps=1000,
    scheduler_stochastic_sampling=False,
    scheduler_use_karras_sigmas=False,
):
    print(f"🔍 Получены параметры:")
    print(f"🔍 final_num_inference_steps: {final_num_inference_steps}")
    print(f"🔍 num_inference_steps: {num_inference_steps}")
    print(f"🔍 downscale_factor: {downscale_factor}")
    print(f"🔍 upscale_factor: {upscale_factor}")
    # Приведение типов
    width = int(width)
    height = int(height)
    num_frames = int(num_frames)
    num_inference_steps = int(num_inference_steps)
    final_num_inference_steps = int(final_num_inference_steps)
    seed = int(seed)
    
    # Приведение типов для VAE и Transformer
    vae_spatial_compression_ratio = int(vae_spatial_compression_ratio)
    vae_temporal_compression_ratio = int(vae_temporal_compression_ratio)
    transformer_num_attention_heads = int(transformer_num_attention_heads)
    transformer_num_layers = int(transformer_num_layers)
    transformer_attention_head_dim = int(transformer_attention_head_dim)
    scheduler_num_train_timesteps = int(scheduler_num_train_timesteps)

    # Грузим модели только если их нет (только в воркере)
    load_models_on_startup()
    pipe, pipe_upsample = get_models()
    
    # Применяем настройки VAE если они отличаются от стандартных
    if hasattr(pipe, 'vae') and hasattr(pipe.vae, 'spatial_compression_ratio'):
        if pipe.vae.spatial_compression_ratio != vae_spatial_compression_ratio:
            pipe.vae.spatial_compression_ratio = vae_spatial_compression_ratio
        if hasattr(pipe.vae, 'temporal_compression_ratio') and pipe.vae.temporal_compression_ratio != vae_temporal_compression_ratio:
            pipe.vae.temporal_compression_ratio = vae_temporal_compression_ratio

    # Применяем настройки Transformer если они отличаются от стандартных
    if hasattr(pipe, 'transformer'):
        if hasattr(pipe.transformer, 'config') and hasattr(pipe.transformer.config, 'num_attention_heads') and pipe.transformer.config.num_attention_heads != transformer_num_attention_heads:
            pipe.transformer.config.num_attention_heads = transformer_num_attention_heads
        if hasattr(pipe.transformer, 'config') and hasattr(pipe.transformer.config, 'num_layers') and pipe.transformer.config.num_layers != transformer_num_layers:
            pipe.transformer.config.num_layers = transformer_num_layers
        if hasattr(pipe.transformer, 'config') and hasattr(pipe.transformer.config, 'attention_head_dim') and pipe.transformer.config.attention_head_dim != transformer_attention_head_dim:
            pipe.transformer.config.attention_head_dim = transformer_attention_head_dim

    # Применяем настройки Scheduler
    if hasattr(pipe, 'scheduler'):
        if hasattr(pipe.scheduler, 'config') and hasattr(pipe.scheduler.config, 'num_train_timesteps') and pipe.scheduler.config.num_train_timesteps != scheduler_num_train_timesteps:
            pipe.scheduler.config.num_train_timesteps = scheduler_num_train_timesteps
        if hasattr(pipe.scheduler, 'config') and hasattr(pipe.scheduler.config, 'stochastic_sampling') and pipe.scheduler.config.stochastic_sampling != scheduler_stochastic_sampling:
            pipe.scheduler.config.stochastic_sampling = scheduler_stochastic_sampling
        if hasattr(pipe.scheduler, 'config') and hasattr(pipe.scheduler.config, 'use_karras_sigmas') and pipe.scheduler.config.use_karras_sigmas != scheduler_use_karras_sigmas:
            pipe.scheduler.config.use_karras_sigmas = scheduler_use_karras_sigmas

    # Вычисляем размеры с учетом downscale_factor и округляем до кратных 32
    print(f"🔍 Исходные размеры: {width}x{height}")
    print(f"🔍 Downscale factor: {downscale_factor}")
    
    downscaled_height = int(height * downscale_factor)
    downscaled_width = int(width * downscale_factor)
    print(f"🔍 После downscale: {downscaled_width}x{downscaled_height}")
    
    # Округляем до ближайшего числа, кратного 32
    downscaled_height = (downscaled_height // 32) * 32
    downscaled_width = (downscaled_width // 32) * 32
    print(f"🔍 После округления до 32: {downscaled_width}x{downscaled_height}")
    
    # Убеждаемся, что размеры не меньше минимальных
    downscaled_height = max(32, downscaled_height)
    downscaled_width = max(32, downscaled_width)
    print(f"🔍 После проверки минимума: {downscaled_width}x{downscaled_height}")
    
    downscaled_height, downscaled_width = round_to_nearest_resolution_acceptable_by_vae(downscaled_height, downscaled_width, pipe)
    print(f"🔍 После VAE округления: {downscaled_width}x{downscaled_height}")

    # Определяем режим: text-to-video или image-to-video
    if image_base64 and isinstance(image_base64, str):
        # image-to-video
        image = Image.open(io.BytesIO(base64.b64decode(image_base64))).convert("RGB")
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        # Сжимаем картинку в видео (1 кадр)
        temp_video_path = f"temp_{uuid.uuid4().hex}.mp4"
        export_to_video([image], temp_video_path, fps=30)
        video_frames = load_video(temp_video_path)
        os.remove(temp_video_path)
        condition1 = LTXVideoCondition(video=video_frames, frame_index=0)
        conditions = [condition1]
    else:
        # text-to-video
        conditions = None

    # Part 1. Генерация видео в низком разрешении
    print(f"🔍 Первая генерация с размерами: {downscaled_width}x{downscaled_height}")
    latents = pipe(
        conditions=conditions,
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=downscaled_width,
        height=downscaled_height,
        num_frames=num_frames,
        num_inference_steps=num_inference_steps,
        generator=torch.Generator("cuda").manual_seed(seed),
        output_type="latent",
    ).frames
    print(f"🔍 Размеры полученных latents: {latents.shape}")

    # Part 2. Апскейл латентов
    upscaled_height = int(downscaled_height * upscale_factor)
    upscaled_width = int(downscaled_width * upscale_factor)
    
    # Округляем до ближайшего числа, кратного 32
    upscaled_height = (upscaled_height // 32) * 32
    upscaled_width = (upscaled_width // 32) * 32
    
    # Убеждаемся, что размеры не меньше минимальных
    upscaled_height = max(32, upscaled_height)
    upscaled_width = max(32, upscaled_width)
    upscaled_latents = pipe_upsample(
        latents=latents,
        output_type="latent"
    ).frames

    # Part 3. Финальный денойз и декод
    print(f"🔍 Размеры upscaled_latents: {upscaled_latents.shape}")
    
    # Вычисляем правильные размеры на основе размеров латентов
    latent_height, latent_width = upscaled_latents.shape[-2], upscaled_latents.shape[-1]
    final_width = latent_width * 32
    final_height = latent_height * 32
    print(f"🔍 Вычисленные размеры для финальной генерации: {final_width}x{final_height}")
    print(f"🔍 Используем final_num_inference_steps: {final_num_inference_steps}")
    
    video = pipe(
        conditions=conditions,
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=final_width,  # Используем размеры, соответствующие латентам
        height=final_height,
        num_frames=num_frames,
        denoise_strength=denoise_strength,
        num_inference_steps=final_num_inference_steps,
        latents=upscaled_latents,
        decode_timestep=decode_timestep,
        image_cond_noise_scale=image_cond_noise_scale,
        generator=torch.Generator("cuda").manual_seed(seed),
        output_type="pil",
    ).frames[0]

    # Part 4. Приведение к ожидаемому разрешению
    video = [frame.resize((width, height)) for frame in video]

    # Сохраняем видео
    output_path = f"result_{uuid.uuid4().hex}.mp4"
    export_to_video(video, output_path, fps=30)
    return output_path