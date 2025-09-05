from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
from .tasks import generate_image
from pathlib import Path
import uuid
import threading
import asyncio
import time
from collections import deque
import os

app = FastAPI()

BASE_DIR   = Path(__file__).resolve().parent.parent   # .../flux_service
STATIC_DIR = BASE_DIR / "static"                      # .../flux_service/static
STATIC_URL = "/flux_service/static"

STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount(STATIC_URL, StaticFiles(directory=STATIC_DIR), name="static")

###############################################################################
# Приоритетная очередь задач (high/low) + воркер с concurrency=1
###############################################################################

class EnqueueRequest(BaseModel):
    prompt: str
    seed: Optional[int] = None
    format: Optional[str] = "long"  # "long" | "shorts"
    priority: Optional[str] = "low"  # "high" | "low"
    wait: Optional[bool] = True


class Job:
    def __init__(self, job_id: str, prompt: str, seed: int, fmt: str, priority: str, future: "asyncio.Future"):
        self.id = job_id
        self.prompt = prompt
        self.seed = seed
        self.format = fmt
        self.priority = priority
        self.future = future


# Очереди по приоритетам
HIGH_Q: deque[Job] = deque()
LOW_Q: deque[Job] = deque()

# Состояния задач
TASKS: Dict[str, Dict[str, Any]] = {}

# Главный event loop для future
MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _now_ts() -> float:
    return time.time()


def _build_static_url_from_file(file_path: str) -> str:
    # Ожидаем, что file_path вида "flux_service/static/<filename>"
    name = Path(file_path).name
    return f"{STATIC_URL}/{name}"


def _worker_loop():
    while True:
        job: Optional[Job] = None
        try:
            # Берём сначала high, иначе low
            if HIGH_Q:
                job = HIGH_Q.popleft()
            elif LOW_Q:
                job = LOW_Q.popleft()
            else:
                time.sleep(0.005)
                continue

            TASKS[job.id]["status"] = "processing"
            TASKS[job.id]["updated_at"] = _now_ts()

            try:
                out_path = generate_image(job.prompt, seed=job.seed, filename=f"{uuid.uuid4().hex}.png", format=job.format)
                TASKS[job.id]["file"] = out_path
                TASKS[job.id]["url"] = _build_static_url_from_file(out_path)
                TASKS[job.id]["status"] = "completed"
                TASKS[job.id]["updated_at"] = _now_ts()
                if MAIN_LOOP and not job.future.done():
                    MAIN_LOOP.call_soon_threadsafe(job.future.set_result, {
                        "file": out_path,
                        "url": TASKS[job.id]["url"],
                    })
            except Exception as e:
                TASKS[job.id]["status"] = "failed"
                TASKS[job.id]["error"] = str(e)
                TASKS[job.id]["updated_at"] = _now_ts()
                if MAIN_LOOP and not job.future.done():
                    MAIN_LOOP.call_soon_threadsafe(job.future.set_exception, e)
        except Exception:
            # Гарантированно не валим воркер
            time.sleep(0.01)


@app.on_event("startup")
async def _on_startup():
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_event_loop()
    t = threading.Thread(target=_worker_loop, daemon=True)
    t.start()

@app.get("/health")
def health_check_api():
    """Проверка здоровья системы"""
    try:
       return {'status': "healthy"}
    except Exception as e:
        return {
            "status": "unhealthy",
        }

@app.post("/enqueue")
async def enqueue(req: EnqueueRequest):
    # Подготовка задачи
    job_id = uuid.uuid4().hex
    seed = int(req.seed) if req.seed is not None else 42
    fmt = req.format or "long"
    priority = (req.priority or "low").lower()
    wait = bool(req.wait) if req.wait is not None else True

    # Регистрируем состояние
    TASKS[job_id] = {
        "status": "queued",
        "priority": priority,
        "file": None,
        "url": None,
        "error": None,
        "created_at": _now_ts(),
        "updated_at": _now_ts(),
        "prompt": req.prompt,
        "format": fmt,
        "seed": seed,
    }

    # Готовим future и ставим в очередь
    assert MAIN_LOOP is not None, "Event loop not initialized"
    fut: asyncio.Future = MAIN_LOOP.create_future()
    job = Job(job_id, req.prompt, seed, fmt, priority, fut)
    if priority == "high":
        HIGH_Q.append(job)
    else:
        LOW_Q.append(job)

    if wait:
        # Дождаться результата и вернуть сразу
        try:
            result = await fut
            return {
                "id": job_id,
                "status": TASKS[job_id]["status"],
                "file": TASKS[job_id]["file"],
                "url": TASKS[job_id]["url"],
            }
        except Exception as e:
            return {
                "id": job_id,
                "status": "failed",
                "error": str(e),
            }
    else:
        # Немедленно вернуть id
        return {"id": job_id, "status": "queued"}


@app.get("/status/{task_id}")
def get_status(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        return {"status": "not_found"}
    return {
        "id": task_id,
        "status": task.get("status"),
        "file": task.get("file"),
        "url": task.get("url"),
        "priority": task.get("priority"),
        "error": task.get("error"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }

@app.delete("/file/{task_id}")
def delete_file(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        return {"status": "not_found", "id": task_id}

    file_path = task.get("file")
    if not file_path:
        return {"status": "no_file", "id": task_id}

    try:
        if os.path.exists(file_path):
            os.remove(file_path)
        return {"status": "deleted", "id": task_id}
    except Exception as e:
        return {"status": "error", "id": task_id, "error": str(e)}

# Совместимость: старый маршрут генерации. Теперь поддерживает приоритет и ожидание
@app.get("/generate")
async def generate(prompt: str, seed: int = 42, format: str = "long", priority: str = "low", wait: bool = True):
    req = EnqueueRequest(prompt=prompt, seed=seed, format=format, priority=priority, wait=wait)
    return await enqueue(req)
