import os, time, subprocess, requests, runpod, pathlib

START_FLAG = pathlib.Path("/tmp/autovid_started")

API_BASE = os.getenv("AUTOVID_API_BASE", "http://127.0.0.1:3000")

API_PATH = os.getenv("AUTOVID_API_PATH", "/api/projects")

HEALTH_PATH = os.getenv("AUTOVID_HEALTH_PATH", "/api/health")
BOOT_TIMEOUT = int(os.getenv("AUTOVID_BOOT_TIMEOUT", "600"))
API_TIMEOUT  = int(os.getenv("AUTOVID_API_TIMEOUT",  "1800"))

def boot_once():
    """Запускаем startup.sh и ждём пока FastAPI поднимется"""
    if START_FLAG.exists():
        return
    subprocess.Popen(
        ['bash','-lc','nohup /workspace/startup.sh > /workspace/startup_boot.log 2>&1 &'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    waited = 0
    while waited < BOOT_TIMEOUT:
        try:
            r = requests.get(f"{API_BASE}{HEALTH_PATH}", timeout=3)
            if r.status_code == 200 and r.json().get("status") == "healthy":
                START_FLAG.write_text("ok")
                return
        except Exception:
            pass
        time.sleep(5)
        waited += 5

    raise RuntimeError(
        f"❌ API не поднялся за {BOOT_TIMEOUT} секунд. Смотри логи: /workspace/startup_boot.log"
    )

def handler(event):
    boot_once()
    payload = event.get("input", {}) or {}

    url = f"{API_BASE}{API_PATH}"
    r = requests.post(url, json=payload, timeout=API_TIMEOUT)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"text": r.text}

runpod.serverless.start({"handler": handler})
