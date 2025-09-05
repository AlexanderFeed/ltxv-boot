from celery import chain, group
import redis

from autovid.backend.flows.config.celery_app import app
from autovid.backend.models.db_utils import update_project_status
from autovid.backend.flows.tasks.generate_script import generate_script
from autovid.backend.flows.tasks.generate_metadata import generate_metadata
from autovid.backend.flows.tasks.generate_chunks import generate_chunks
from autovid.backend.flows.tasks.generate_video import generate_video
from autovid.backend.flows.tasks.send_to_playprofi import send_to_cdn


# Redis для флагов завершения
r = redis.Redis(host='localhost', port=6379, db=5, decode_responses=True)

@app.task
def mark_done(key):
    r.set(key, '1')

def is_paused(project_id):
    return r.get(f"{project_id}:paused") == '1'

def acquire_once(key: str, ttl_seconds: int = 6 * 3600) -> bool:
    """Устанавливает флаг один раз (атомарно). Возвращает True, если флаг установлен впервые."""
    try:
        return bool(r.set(key, '1', nx=True, ex=ttl_seconds))
    except Exception:
        # В случае проблем с Redis лучше не блокировать пайплайн
        return True

@app.task
def try_generate_video(project_id, video_format):
    """Генерирует видео когда готовы voiceover и images"""
    if is_paused(project_id):
        print(f"⏸ Project {project_id} is paused. Skipping video generation.")
        return
    voiceover_ready = r.get(f"{project_id}:voiceover_ready")
    images_ready = r.get(f"{project_id}:images_ready")
    if voiceover_ready and images_ready:
        # Гарантируем, что сборка видео будет запущена один раз
        if not acquire_once(f"{project_id}:video_started"):
            print(f"⏭️ Video already started for project {project_id}, skipping duplicate launch")
            return
        print(f"✅ Conditions met. Generating video for project {project_id}")
        # После генерации видео отправляем на CDN
        chain(
            generate_video.si(project_id, video_format),
            try_generate_final_video.si(project_id, video_format)
        ).apply_async()
    else:
        print(f"⏳ Waiting for other parts. Current: voiceover={voiceover_ready}, images={images_ready}")

@app.task
def try_generate_final_video(project_id, video_format):
    """Отправляет на CDN когда готово обычное видео"""
    if is_paused(project_id):
        print(f"⏸ Project {project_id} is paused. Skipping final video generation.")
        return
    # Гарантируем единичную отправку на CDN
    if not acquire_once(f"{project_id}:cdn_enqueued"):
        print(f"⏭️ CDN already enqueued for project {project_id}, skipping duplicate send")
        return

    print(f"✅ Видео готово. Отправляем на CDN для проекта {project_id}")
    send_to_cdn.delay(project_id)

@app.task
def start_post_chunks_branches(project_id, video_format):
    """Запускает voiceover_branch и prompts_branch после завершения chunks"""
    print(f"🚀 Запускаем post_chunks ветви для проекта {project_id}")
    
    # Импортируем задачи здесь, чтобы избежать циклических импортов
    from autovid.backend.flows.tasks.generate_voiceover import generate_voiceover
    from autovid.backend.flows.tasks.generate_prompts import generate_prompts
    from autovid.backend.flows.tasks.generate_images import generate_images
    from autovid.backend.flows.tasks.generate_thumbnail import generate_thumbnail
    
    # Ветви, которые должны запускаться после generate_chunks
    voiceover_branch = chain(
        generate_voiceover.si(project_id, specific_chunk_id=None),
        mark_done.si(f"{project_id}:voiceover_ready"),
        try_generate_video.si(project_id, video_format)
    )

    # Явно маршрутизируем задачи по очередям и делаем их immutable, чтобы не передавать результат дальше
    prompts_branch = chain(
        generate_prompts.si(project_id).set(queue="prompts"),
        generate_thumbnail.si(project_id, video_format).set(queue="thumbnails"),
        generate_images.si(project_id, video_format).set(queue="images"),
        mark_done.si(f"{project_id}:images_ready"),
        try_generate_video.si(project_id, video_format)
    )
    
    # Запускаем обе ветви параллельно
    print(f"📢 Запускаем voiceover для проекта {project_id}")
    voiceover_branch.apply_async()
    print(f"🖼️ Запускаем prompts для проекта {project_id}")
    prompts_branch.apply_async()

@app.task
def video_pipeline(topic, chapters, project_id, video_format="long"):
    if is_paused(project_id):
        print(f"⏸ Project {project_id} is paused. Skipping pipeline.")
        return
    print(f"🚀 Starting pipeline for project {project_id}")

    # Очищаем все флаги готовности
    r.delete(f"{project_id}:voiceover_ready")
    r.delete(f"{project_id}:images_ready")
    # Очищаем флаги идемпотентности для нового запуска
    r.delete(f"{project_id}:video_started")
    r.delete(f"{project_id}:cdn_enqueued")

    # Создаем основную цепочку с запуском post_chunks в конце
    main_chain = chain(
        generate_script.si(project_id, topic, chapters, video_format),
        generate_metadata.si(project_id),
        generate_chunks.si(project_id),
        start_post_chunks_branches.si(project_id, video_format)
    )
    
    # Запускаем основную цепочку
    main_chain.apply_async()
    
    update_project_status(project_id, True)

@app.task
def add_to_queue(project_id, topic, chapters, video_format):
    
    video_pipeline.delay(topic, chapters, project_id, video_format)
