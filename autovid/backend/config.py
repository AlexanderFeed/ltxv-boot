"""
config.py
---------
Конфигурационный файл для всех настроек проекта AutoVid.
Содержит константы, переменные окружения и настройки для всех модулей.
"""
from pathlib import Path
from dotenv import load_dotenv
import os
from typing import Dict, Any

# Корневая папка проекта
BASE_DIR = Path(__file__).resolve().parent.parent

# Загружаем переменные окружения из .env, лежащего в корне проекта
load_dotenv(BASE_DIR / ".env")

# ========== API КЛЮЧИ И ИДЕНТИФИКАТОРЫ ========== #
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("VOICE_ID", "Rachel")  # дефолтный голос

# ========== ПАРАМЕТРЫ ГЕНЕРИРУЕМОГО ВИДЕО ========== #
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")  # модель GPT
CHAR_PER_SEC = int(os.getenv("CHAR_PER_SEC", "13"))  # ≈ 150 слов/мин → 13 символов/сек
CHUNK_SEC = int(os.getenv("CHUNK_SEC", "5"))  # длина одного аудиофрагмента (6‑8 с)
WIDTH, HEIGHT = 1920, 1080  # разрешение Full HD
BITRATE = os.getenv("BITRATE", "10M")  # целевой битрейт mp4

# ========== ФОРМАТЫ ВИДЕО ========== #
VIDEO_FORMATS = {
    "long": {
        "WIDTH": 1920,
        "HEIGHT": 1080,
        "CHUNK_SEC": 8,
        "FPS": 25,
        "BITRATE": "10M"
    },
    "shorts": {
        "WIDTH": 1080,
        "HEIGHT": 1920,
        "CHUNK_SEC": 6,
        "FPS": 25,
        "BITRATE": "10M"
    }
}

# ========== ПУТИ К ФАЙЛАМ ========== #
CHUNKS_PATH = Path("assets/chunks/chunks.json")
IMAGE_PROMPTS_PATH = Path("assets/prompts/image_prompts.json")

# ========== IMAGE-TO-VIDEO НАСТРОЙКИ ========== #

ltx_id = os.getenv("RUNPOD_LTX_ID", "unknown")
LTX_VIDEO_CONFIG = {
    "api_base_url": f"https://{ltx_id}-8000.proxy.runpod.net",
    "enabled": True,
    "timeout": 300,  # 5 минут таймаут для запроса
    "polling_interval": 35,  # Проверять статус каждые 35 секунд
    "max_retries": 3,
    "scene_selection": {
        "strategy": "first_n",  # "first_n", "every_nth", "custom_list"
        "count": 5,  # Для "first_n" - количество сцен
        "step": 2,   # Для "every_nth" - каждая N-я сцена  
        "custom_scenes": [1, 2, 5, 8],  # Для "custom_list" - конкретные номера
        "max_scenes_for_shorts": 3  # Максимум для shorts формата
    },
    "duration_settings": {
        "target_animation_duration": 4.0,  # Оптимальная длительность анимации (секунды)
        "min_animation_duration": 2.0,     # Минимальная длительность
        "max_animation_duration": 5.0,     # Максимальная длительность
        "scene_split_threshold": 5.1,      # Разбивать сцены длиннее этого значения
        "overlap_duration": 0.2             # Перекрытие между частями (секунды)
    },
    "prompt_settings": {
        "use_original_prompts": True,       # Использовать оригинальные промпты сцен
        "universal_prompt": "Add smooth, cinematic animation to this image with gentle camera movement and natural motion",
        "animation_style_suffix": ", smooth cinematic movement, professional video animation",
        "vary_seeds_for_parts": True        # Использовать разные seeds для частей сцены
    },
    "video_params": {
        "negative_prompt": "worst quality, inconsistent motion, blurry, jittery, distorted",
        "num_frames": 120,
        "seed": 42
    }
}

# ========== CHUNKER НАСТРОЙКИ ========== #
CHUNKER_CONFIG = {
    "default_format": "long",
    "min_chunk_seconds": {
        "long": 4,
        "shorts": 2
    }
}

# ========== FLUX IMAGE GENERATOR НАСТРОЙКИ ========== #
FLUX_API_URL = os.getenv("FLUX_API_URL", "http://localhost:8000")
# FLUX_API_URL = os.getenv("FLUX_API_URL", "https://api.bfl.ai/v1/flux-dev")
FLUX_API_KEY = os.getenv("FLUX_API_KEY", "bc4fe6fa-c015-4bd6-be80-b1d059b95aa4")
FLUX_MODEL = os.getenv("FLUX_MODEL", "flux-dev")
FLUX_CONFIG = {
    "timeout": int(os.getenv("FLUX_TIMEOUT", "30")),
    "max_retries": int(os.getenv("FLUX_MAX_RETRIES", "3")),
    "api_key": FLUX_API_KEY,
    "model": FLUX_MODEL
}

# ========== VOICEOVER GENERATOR НАСТРОЙКИ ========== #
VOICEOVER_CONFIG = {
    "voice_id": os.getenv("VOICEOVER_VOICE_ID", "vYEa0poxgOWoLcB1c9Vz"),  # голос сергея
    "model_id": os.getenv("VOICEOVER_MODEL_ID", "eleven_turbo_v2_5"),
    "stability": float(os.getenv("VOICEOVER_STABILITY", "0.5")),
    "similarity_boost": float(os.getenv("VOICEOVER_SIMILARITY_BOOST", "0.75")),
    "max_retries": int(os.getenv("VOICEOVER_MAX_RETRIES", "5")),
    "retry_delay": int(os.getenv("VOICEOVER_RETRY_DELAY", "5")),
    "target_dbfs": float(os.getenv("VOICEOVER_TARGET_DBFS", "-20.0")),
    "proxies": {
        "http": os.getenv("VOICEOVER_PROXY_HTTP", "http://6TXECjTG:mEPUpuB2@194.87.165.174:63982"),
        "https": os.getenv("VOICEOVER_PROXY_HTTPS", "http://6TXECjTG:mEPUpuB2@194.87.165.174:63982")
    }
}

# ========== YOUTUBE AUTH НАСТРОЙКИ ========== #
YOUTUBE_AUTH_CONFIG = {
    "scopes": [
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.force-ssl"
    ],
    "token_path": Path("token.json"),
    "secrets_path": Path("client_secret.json"),
    "authorization_base_url": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_url": "https://oauth2.googleapis.com/token",
    "redirect_uri": os.getenv("YOUTUBE_REDIRECT_URI", "https://ccr1ee2yb1s9m5-8003.proxy.runpod.net/"),
    "server_port": int(os.getenv("YOUTUBE_SERVER_PORT", "8003")),
    "server_host": os.getenv("YOUTUBE_SERVER_HOST", "0.0.0.0")
}

# ========== YOUTUBE UPLOAD НАСТРОЙКИ ========== #
YOUTUBE_UPLOAD_CONFIG = {
    "category_id": os.getenv("YOUTUBE_CATEGORY_ID", "22"),  # YouTube: People & Blogs
    "default_language": os.getenv("YOUTUBE_DEFAULT_LANGUAGE", "ru"),
    "default_audio_language": os.getenv("YOUTUBE_DEFAULT_AUDIO_LANGUAGE", "ru"),
    "privacy_status": os.getenv("YOUTUBE_PRIVACY_STATUS", "private"),
    "made_for_kids": os.getenv("YOUTUBE_MADE_FOR_KIDS", "false").lower() == "true",
    "publish_interval_hours": int(os.getenv("YOUTUBE_PUBLISH_INTERVAL_HOURS", "12"))
}

# ========== PLAYPROFI НАСТРОЙКИ ========== #
PLAYPROFI_CONFIG = {
    "api_url": os.getenv("PLAYPROFI_API_URL", "https://backend.playprofi.ru/admin_auto/create_project_pancake_v2"),
    "timeout": int(os.getenv("PLAYPROFI_TIMEOUT", "3600")),  # 1 час
    "max_retries": int(os.getenv("PLAYPROFI_MAX_RETRIES", "3")),
    "backoff_factor": int(os.getenv("PLAYPROFI_BACKOFF_FACTOR", "1")),
    "pool_connections": int(os.getenv("PLAYPROFI_POOL_CONNECTIONS", "10")),
    "pool_maxsize": int(os.getenv("PLAYPROFI_POOL_MAXSIZE", "10")),
    "verify_ssl": os.getenv("PLAYPROFI_VERIFY_SSL", "false").lower() == "true"
}

# ========== SUBTITLE GENERATOR НАСТРОЙКИ ========== #
SUBTITLE_CONFIG = {
    "whisper_timeout": int(os.getenv("WHISPER_TIMEOUT", "120")),
    "max_retries": int(os.getenv("SUBTITLE_MAX_RETRIES", "3")),
    "retry_delay": int(os.getenv("SUBTITLE_RETRY_DELAY", "5")),
    "language": os.getenv("SUBTITLE_LANGUAGE", "ru"),
    "model": os.getenv("SUBTITLE_MODEL", "whisper-1"),
    "response_format": os.getenv("SUBTITLE_RESPONSE_FORMAT", "verbose_json"),
    "timestamp_granularities": ["word"]
}

# ========== PROMPT GENERATOR НАСТРОЙКИ ========== #
PROMPT_CONFIG = {
    "temperature": float(os.getenv("PROMPT_TEMPERATURE", "0.7")),
    "max_prompt_words": int(os.getenv("PROMPT_MAX_WORDS", "120")),
    "max_retries": int(os.getenv("PROMPT_MAX_RETRIES", "2")),
    "retry_delay": int(os.getenv("PROMPT_RETRY_DELAY", "2")),
    "max_workers": int(os.getenv("PROMPT_MAX_WORKERS", "10"))
}

# ========== SUBTITLE STYLES ========== #
SUBTITLE_STYLES = {
    "karaoke": {
        "color_inactive": "&HFFFFFF&",
        "color_active": "&H00FFFF&",
        "font": "fonts/aa_badaboom_bb.ttf",
        "font_size": 60,
        "outline_color": "&H000000&",
        "outline_width": 2,
        "shadow": 1,
        "fade_ms": 200,
        "fade_curve": "linear",
        "letter_spacing": 0
    },
    "highlight": {
        "color_active": "&HFFFFFF&",
        "highlight_color": "&H800080&",
        "font": "Montserrat",
        "font_size": 60,
        "padding_percent": 10,
        "fade_ms": 300,
        "fade_curve": "ease-in-out",
        "margin_v": 320
    }
}

# ========== THUMBNAIL GENERATOR НАСТРОЙКИ ========== #
THUMBNAIL_CONFIG = {
    "flux_api_url": os.getenv("THUMBNAIL_FLUX_API_URL", "http://localhost:8000"),
    "max_retries": int(os.getenv("THUMBNAIL_MAX_RETRIES", "3")),
    "retry_delay": int(os.getenv("THUMBNAIL_RETRY_DELAY", "2")),
    "timeout": int(os.getenv("THUMBNAIL_TIMEOUT", "30")),
    "max_workers": int(os.getenv("THUMBNAIL_MAX_WORKERS", "5")),
    "temperature": float(os.getenv("THUMBNAIL_TEMPERATURE", "0.7")),
    "max_prompt_words": int(os.getenv("THUMBNAIL_MAX_WORDS", "120")),
    "default_format": os.getenv("THUMBNAIL_DEFAULT_FORMAT", "long")
}

# ========== METADATA GENERATOR НАСТРОЙКИ ========== #
METADATA_CONFIG = {
    "model_name": os.getenv("METADATA_MODEL_NAME", "gpt-4o"),
    "temperature": float(os.getenv("METADATA_TEMPERATURE", "0.7")),
    "max_retries": int(os.getenv("METADATA_MAX_RETRIES", "3")),
    "retry_delay": int(os.getenv("METADATA_RETRY_DELAY", "2")),
    "max_workers": int(os.getenv("METADATA_MAX_WORKERS", "5")),
    "max_title_length": int(os.getenv("METADATA_MAX_TITLE_LENGTH", "100")),
    "max_description_sentences": int(os.getenv("METADATA_MAX_DESCRIPTION_SENTENCES", "7")),
    "max_tags_count": int(os.getenv("METADATA_MAX_TAGS_COUNT", "20")),
    "max_script_words_for_gpt": int(os.getenv("METADATA_MAX_SCRIPT_WORDS", "1500"))
}

# ========== ANIMATE SCENE НАСТРОЙКИ ========== #
ANIMATE_SCENE_CONFIG = {
    "ffmpeg_path": os.getenv("FFMPEG_PATH", "ffmpeg"),
    "max_retries": int(os.getenv("ANIMATE_MAX_RETRIES", "3")),
    "retry_delay": int(os.getenv("ANIMATE_RETRY_DELAY", "2")),
    "timeout": int(os.getenv("ANIMATE_TIMEOUT", "300"))
}

# ========== SCRIPT GENERATOR НАСТРОЙКИ ========== #
SCRIPT_CONFIG = {
    "temperature": float(os.getenv("SCRIPT_TEMPERATURE", "0.8")),
    "max_retries": int(os.getenv("SCRIPT_MAX_RETRIES", "3")),
    "retry_delay": int(os.getenv("SCRIPT_RETRY_DELAY", "2")),
    "max_tokens": int(os.getenv("SCRIPT_MAX_TOKENS", "4000"))
}

# ========== ОБЩИЕ НАСТРОЙКИ ========== #
GENERAL_CONFIG = {
    "log_level": os.getenv("LOG_LEVEL", "INFO"),
    "debug_mode": os.getenv("DEBUG_MODE", "false").lower() == "true",
    "temp_dir": Path(os.getenv("TEMP_DIR", "temp")),
    "max_concurrent_jobs": int(os.getenv("MAX_CONCURRENT_JOBS", "3"))
}
