# handler.py
import os, time, subprocess, requests, runpod, pathlib

START_FLAG = pathlib.Path("/tmp/ltx_started")
DAEMON_FLAG = pathlib.Path("/workspace/LTX-Video/daemon_ready.flag")
API_BASE = os.getenv("LTX_LOCAL_API", "http://127.0.0.1:8000")
API_PATH = os.getenv("LTX_LOCAL_API_PATH", "/infer")   # <-- ПОПРАВЬ на реальный путь из run_api_server.py
BOOT_TIMEOUT = int(os.getenv("LTX_BOOT_TIMEOUT", "1200"))   # до 20 мин на холодный старт
API_TIMEOUT  = int(os.getenv("LTX_API_TIMEOUT",  "1800"))

def _boot_once():
    if START_FLAG.exists():
        return
    # запускаем твой startup.sh в фоне, логи пишем в файл
    subprocess.Popen(
        ['bash','-lc','nohup /workspace/startup.sh > /workspace/startup_boot.log 2>&1 &'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    # ждём готовности демона (startup.sh сам создаёт daemon_ready.flag)
    waited = 0
    step = 5
    while waited < BOOT_TIMEOUT:
        if DAEMON_FLAG.exists():
            START_FLAG.write_text("ok")
            return
        time.sleep(step); waited += step
    raise RuntimeError(
        f"LTX daemon not ready in {BOOT_TIMEOUT}s. Check logs: "
        f"/workspace/LTX-Video/inference_daemon_official.log and /workspace/startup_boot.log"
    )

def handler(event):
    _boot_once()
    payload = event.get("input", {}) or {}
    # ⚠️ Уточни конечную точку в run_api_server.py и подставь её в API_PATH
    url = f"{API_BASE}{API_PATH}"
    r = requests.post(url, json=payload, timeout=API_TIMEOUT)
    r.raise_for_status()
    # если API отдаёт не JSON — вернём как текст
    try:
        return r.json()
    except Exception:
        return {"text": r.text}

runpod.serverless.start({"handler": handler})
