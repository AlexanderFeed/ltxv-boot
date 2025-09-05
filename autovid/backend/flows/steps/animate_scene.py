from __future__ import annotations
import sys
import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
from mutagen.mp3 import MP3

from autovid.backend.config import VIDEO_FORMATS, LTX_VIDEO_CONFIG
from autovid.backend.flows.steps.ltx_video_animate import LTXVideoAPIClient

os.environ["PATH"] = "/workspace/bin:" + os.environ.get("PATH", "")
WAIT_TIME_SECONDS = 5


def ffprobe_duration(path: Path) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)], text=True
        )
        return float(out.strip())
    except Exception:
        return 0.0


def mp4_quick_check(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 100_000 and b"ftyp" in path.read_bytes()[:12]


@dataclass
class SceneInfo:
    scene_num: str
    image_path: Path
    audio_path: Path
    output_path: Path
    subtitle_path: Optional[Path] = None
    duration: Optional[float] = None


# -------------------------- Frame + Video Builders --------------------------

def generate_zoom_video(scene: SceneInfo, width: int, height: int, fps: int = 25,
                        zoom_start: float = 1.0, zoom_end: float = 1.2) -> None:
    print(f"🎬 Генерируем zoom видео для сцены {scene.scene_num} в разрешении {width}x{height}")
    temp_dir = scene.output_path.parent / f"tmp_{scene.scene_num}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    img = cv2.imread(str(scene.image_path))
    if img is None:
        raise RuntimeError(f"Cannot read image {scene.image_path}")
    h, w = img.shape[:2]
    cx, cy = w / 2, h / 2
    frames = int(scene.duration * fps)

    for i in range(frames):
        scale = zoom_start + (zoom_end - zoom_start) * (i / max(frames - 1, 1))
        M = cv2.getRotationMatrix2D((cx, cy), 0, scale)
        frame = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        if (w, h) != (width, height):
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(str(temp_dir / f"frame_{i:04d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 100])

    temp_video = scene.output_path.with_name(scene.output_path.stem + "_tmp.mp4")

    subprocess.run([
        "ffmpeg", "-y", "-framerate", str(fps),
        "-i", str(temp_dir / "frame_%04d.jpg"),
        "-i", str(scene.audio_path),
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "8M",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
        str(temp_video)
    ], check=True)

    temp_video.replace(scene.output_path)
    shutil.rmtree(temp_dir, ignore_errors=True)



def overlay_subs(video: Path, subs: Path, out: Path) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-i", str(video),
        "-vf", f"subtitles='{subs}:fontsdir=fonts'",
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "8M",
        "-c:a", "copy", str(out)
    ], check=True)


# -------------------------- Manager --------------------------

class SceneAnimationManager:
    def __init__(self, project_id: str, video_format: str):
        self.project_id = project_id
        self.video_format = video_format
        params = VIDEO_FORMATS.get(video_format, VIDEO_FORMATS["long"])
        self.width, self.height = params["WIDTH"], params["HEIGHT"]
        self.fps = params.get("FPS", 25)
        
        print(f"🎬 Инициализация SceneAnimationManager:")
        print(f"  Проект: {project_id}")
        print(f"  Формат: {video_format}")
        print(f"  Разрешение: {self.width}x{self.height}")
        print(f"  FPS: {self.fps}")

        assets_dir = Path(os.getenv("ASSETS_DIR", "assets"))
        self.scenes_dir = assets_dir / "scenes" / str(project_id)
        self.audio_dir = assets_dir / "audio" / str(project_id)
        self.output_dir = assets_dir / "video" / str(project_id)
        self.chunks_file = assets_dir / "chunks" / str(project_id) / "chunks.json"
        self.subtitle_dir = assets_dir / "scripts" / str(project_id) / "subtitles"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        with open(self.chunks_file, "r", encoding="utf-8") as fp:
            self.chunks = json.load(fp)
        self.scene_ids = [str(c["id"]) for c in self.chunks]
        self.start = time.time()

    def run(self) -> None:
        print(f"\U0001F3AC start video generation {self.project_id} ({self.video_format})")
        # Валидация доступности LTX сервиса до запуска анимаций
        if LTX_VIDEO_CONFIG["enabled"]:
            self._validate_ltx_connectivity()
        
        # Запускаем LTX анимацию в фоне сразу
        if LTX_VIDEO_CONFIG["enabled"]:
            print("🚀 Запускаем LTX анимацию в фоне параллельно с базовыми сценами...")
            self._start_ltx_animations_in_background()
        
        while True:
            todo, missing = self._scan_scenes()
            if missing:
                print("waiting for images", missing)
            if not todo:
                if self._all_done():
                    break
                time.sleep(WAIT_TIME_SECONDS)
                continue
            self._animate_parallel(todo)
        
        # Ждем завершения LTX анимации перед сборкой
        if LTX_VIDEO_CONFIG["enabled"]:
            print("⏳ Ждем завершения LTX анимации...")
            self._wait_for_ltx_animation()
        
        self._concat()
        print(f"✅ finished in {time.time() - self.start:.1f}s")

    def _validate_ltx_connectivity(self) -> None:
        """Проверяет корректность RUNPOD_LTX_ID и базовую доступность LTX.
        Не требует наличия /health: допускает 200/403/404/405, фейлится только на сетевых ошибках.
        """
        try:
            runpod_id = os.environ.get("RUNPOD_LTX_ID", "").strip()
            if not runpod_id or runpod_id == "unknown":
                raise RuntimeError(
                    "RUNPOD_LTX_ID не задан (unknown/empty). Установите актуальный идентификатор перед запуском видеоэтапа."
                )

            client = LTXVideoAPIClient()
            base_url = client.base_url.rstrip("/")
            print(f"🔧 LTX validation: RUNPOD_LTX_ID={runpod_id}, base_url={base_url}")

            allowed_status = {200, 201, 202, 203, 204, 301, 302, 303, 307, 308, 403, 404, 405}

            def ok_status(code: int) -> bool:
                return code in allowed_status

            # 1) Пингуем корень
            try:
                r1 = requests.get(base_url + "/", timeout=8)
                if ok_status(r1.status_code):
                    print(f"✅ LTX base reachable: HTTP {r1.status_code}")
                    return
            except Exception as e:
                print(f"⚠️ LTX root GET ошибка: {e}")

            # 2) Пробуем OPTIONS /generate (маршрут, который мы используем)
            try:
                r2 = requests.options(base_url + "/generate", timeout=8)
                if ok_status(r2.status_code):
                    print(f"✅ LTX /generate reachable: HTTP {r2.status_code}")
                    return
                else:
                    print(f"⚠️ LTX /generate unexpected status: HTTP {r2.status_code}")
            except Exception as e:
                print(f"⚠️ LTX /generate OPTIONS ошибка: {e}")

            # Если до сюда дошли — считаем сервис недоступным на сетевом уровне
            raise RuntimeError(
                f"LTX недоступен (нет успешного ответа от {base_url}/ или OPTIONS {base_url}/generate). RUNPOD_LTX_ID={runpod_id}"
            )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Ошибка валидации LTX: {e}")

    def _scan_scenes(self) -> Tuple[List[SceneInfo], List[str]]:
        todo, missing = [], []
        for sid in self.scene_ids:
            img = self._find(self.scenes_dir, sid, "jpg")
            aud = self._find(self.audio_dir, sid, "mp3")
            out = self._find(self.output_dir, sid, "mp4") or self.output_dir / f"scene_{sid.zfill(3)}.mp4"
            
            if not (img and aud):
                missing.append(sid)
                print(f"⚠️ Сцена {sid}: отсутствует {'изображение' if not img else 'аудио'}")
                continue
                
            if mp4_quick_check(out):
                print(f"✅ Сцена {sid}: уже готова")
                continue
                
            duration = MP3(aud).info.length
            sub = self._find(self.subtitle_dir, sid, "ass") if self.video_format == "shorts" else None
            todo.append(SceneInfo(sid, img, aud, out, sub, duration))
            print(f"🎬 Сцена {sid}: добавлена в очередь (длительность: {duration:.1f}с)")
            
        print(f"📋 Сканирование сцен: {len(todo)} в очереди, {len(missing)} отсутствует")
        return todo, missing

    @staticmethod
    def _find(folder: Path, sid: str, ext: str) -> Optional[Path]:
        # Ищем файлы с разными форматами нумерации
        for z in (3, 2, 1):
            p = folder / f"scene_{sid.zfill(z)}.{ext}"
            if p.exists():
                return p
        return None

    def _animate_parallel(self, scenes: List[SceneInfo]) -> None:
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = [
                ex.submit(self._animate_scene, sc)
                for sc in scenes
            ]
            for f in as_completed(futs):
                f.result()

    def _animate_scene(self, scene: SceneInfo) -> None:
        """Генерирует базовое видео для сцены (без блокировки LTX анимации)"""
        # Генерируем обычное видео
        generate_zoom_video(scene, self.width, self.height, fps=self.fps)
        if self.video_format == "shorts" and scene.subtitle_path:
            final_path = scene.output_path.parent / f"final_{scene.output_path.name}"
            overlay_subs(scene.output_path, scene.subtitle_path, final_path)
            scene.output_path.unlink(missing_ok=True)
            final_path.rename(scene.output_path)
        
        print(f"✅ Базовая сцена {scene.scene_num} готова")
        
        # НЕ запускаем LTX анимацию здесь - она будет запущена отдельно
        # self._start_ltx_animation_if_needed(scene)

    def _all_done(self) -> bool:
        """Проверяет готовность всех сцен (базовых) - LTX анимация работает в фоне"""
        for sid in self.scene_ids:
            # Проверяем базовую сцену
            base_path = self._find(self.output_dir, sid, "mp4")
            if not base_path or not mp4_quick_check(base_path):
                return False
        return True

    def _concat(self) -> None:
        concat = self.output_dir / "file_list.txt"
        
        print(f"🎬 Начинаем сборку видео в формате: {self.video_format} ({self.width}x{self.height})")
        
        # Отладочная информация: показываем все файлы в директории
        print(f"🔍 Файлы в директории {self.output_dir}:")
        for file_path in sorted(self.output_dir.glob("*.mp4")):
            print(f"  {file_path.name}")
        
        # Собираем клипы: приоритет animated, иначе базовый
        id_to_clip: dict[int, Path] = {}

        # Сначала animated
        for clip in self.output_dir.glob("scene_*_animated.mp4"):
            try:
                sid_part = clip.stem.split("_")[-2]  # scene_XXX_animated -> XXX
                sid = int(sid_part)
                id_to_clip[sid] = clip
                print(f"✅ Добавляем анимированную сцену {sid}: {clip.name}")
            except Exception as e:
                print(f"❌ Ошибка парсинга анимированной сцены {clip.name}: {e}")
                continue

        # Затем базовые, только если нет animated
        for clip in self.output_dir.glob("scene_*.mp4"):
            name = clip.stem
            if "_animated" in name or "_part_" in name or ".normalized" in name:
                continue  # Пропускаем уже обработанные и нормализованные
            try:
                # Извлекаем ID сцены из имени файла scene_XXX.mp4
                # Убираем "scene_" и берем только цифры
                scene_id_str = name.replace("scene_", "")
                sid = int(scene_id_str)
                
                # Добавляем только если нет анимированной версии
                if sid not in id_to_clip:
                    id_to_clip[sid] = clip
                    print(f"✅ Добавляем базовую сцену {sid}: {clip.name}")
                else:
                    print(f"⏭️ Пропускаем базовую сцену {sid} (есть анимированная)")
            except Exception as e:
                print(f"❌ Ошибка парсинга базовой сцены {clip.name}: {e}")
                continue

        print(f"📋 Собираем видео из {len(id_to_clip)} сцен:")
        for sid in sorted(id_to_clip.keys()):
            clip_name = id_to_clip[sid].name
            clip_type = "анимированная" if clip_name.endswith("_animated.mp4") else "базовая"
            print(f"  Сцена {sid}: {clip_name} ({clip_type})")

        # Нормализация только для LTX-анимированных сцен при необходимости
        target_width, target_height = self.width, self.height
        temp_dir = self.output_dir / "temp_normalized"
        temp_dir.mkdir(exist_ok=True)
        normalized_overrides: dict[int, Path] = {}

        for sid, clip in sorted(id_to_clip.items()):
            if not clip.name.endswith("_animated.mp4"):
                continue
            try:
                # Получаем ширину, высоту и fps
                dim_res = subprocess.run([
                    "ffprobe", "-v", "quiet", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height", "-of", "csv=p=0",
                    str(clip)
                ], capture_output=True, text=True, check=True)
                width_str, height_str = dim_res.stdout.strip().split(',')
                width, height = int(width_str), int(height_str)

                fps_res = subprocess.run([
                    "ffprobe", "-v", "quiet", "-select_streams", "v:0",
                    "-show_entries", "stream=avg_frame_rate", "-of", "csv=p=0",
                    str(clip)
                ], capture_output=True, text=True, check=True)
                avg_fr = fps_res.stdout.strip()
                try:
                    num, den = avg_fr.split('/')
                    clip_fps = int(round(float(num) / float(den))) if den != '0' else self.fps
                except Exception:
                    clip_fps = self.fps

                needs_resize = (width != target_width or height != target_height)
                needs_fps = (clip_fps != self.fps)

                if needs_resize or needs_fps:
                    normalized_file = temp_dir / f"normalized_{sid:03d}.mp4"
                    vf_filters = [
                        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease",
                        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2"
                    ] if needs_resize else []
                    cmd = [
                        "ffmpeg", "-y", "-i", str(clip),
                        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                        "-c:a", "aac", "-b:a", "128k",
                        "-pix_fmt", "yuv420p",
                    ]
                    if vf_filters:
                        cmd += ["-vf", ",".join(vf_filters)]
                    # Принудительно приводим к целевому fps и CFR
                    cmd += [
                        "-r", str(self.fps),
                        "-vsync", "cfr",
                        "-avoid_negative_ts", "make_zero",
                        "-fflags", "+genpts",
                        str(normalized_file)
                    ]
                    subprocess.run(cmd, check=True, capture_output=True)
                    normalized_overrides[sid] = normalized_file
                    print(f"✅ Нормализована анимированная сцена {sid} -> {target_width}x{target_height}@{self.fps}")
            except Exception as e:
                print(f"⚠️ Не удалось нормализовать {clip.name}: {e}")

        # Пишем единый список финальных клипов
        with concat.open("w") as fp:
            for sid in sorted(id_to_clip.keys()):
                final_clip = normalized_overrides.get(sid, id_to_clip[sid])
                fp.write(f"file '{final_clip.resolve()}'\n")

        # Финальная склейка
        final_path = self.output_dir / "final_video.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-c", "copy",
            str(final_path)
        ], check=True)
        if not final_path.exists() or final_path.stat().st_size == 0:
            raise RuntimeError("Итоговый файл final_video.mp4 не создан")

        # Обновляем тайминги по итоговым клипам
        durs = []
        for sid in sorted(id_to_clip.keys()):
            clip = normalized_overrides.get(sid, id_to_clip[sid])
            if mp4_quick_check(clip):
                durs.append((sid, ffprobe_duration(clip)))
        cur = 0.0
        for scid, dur in sorted(durs):
            for ch in self.chunks:
                if int(ch["id"]) == scid:
                    ch["time"] = f"{self._fmt(cur)}-{self._fmt(cur + dur)}"
                    break
            cur += dur
        with open(self.chunks_file, "w", encoding="utf-8") as fp:
            json.dump(self.chunks, fp, ensure_ascii=False, indent=2)

        # Чистим временную директорию
        try:
            import shutil
            shutil.rmtree(temp_dir)
        except Exception:
            pass

    @staticmethod
    def _fmt(s: float) -> str:
        ms = int((s - int(s)) * 1000)
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = int(s % 60)
        return f"{h:02}:{m:02}:{sec:02}.{ms:03}"
    
    def _start_ltx_animations_in_background(self) -> None:
        """Запускает LTX Video анимацию для выбранных сцен в фоне"""
        if not LTX_VIDEO_CONFIG["enabled"]:
            print("⏸️ LTX Video отключен в конфигурации")
            return
        
        print("🎬 Запускаем LTX Video анимацию для выбранных сцен...")
        
        # Определяем какие сцены нужно анимировать
        strategy = LTX_VIDEO_CONFIG["scene_selection"]["strategy"]
        scenes_to_animate = []
        
        for scene_id in self.scene_ids:
            scene_num = int(scene_id)
            should_animate = False
            
            if strategy == "first_n":
                count = LTX_VIDEO_CONFIG["scene_selection"]["count"]
                if self.video_format == "shorts":
                    count = min(count, LTX_VIDEO_CONFIG["scene_selection"]["max_scenes_for_shorts"])
                should_animate = scene_num <= count
                
            elif strategy == "every_nth":
                step = LTX_VIDEO_CONFIG["scene_selection"]["step"]
                should_animate = scene_num % step == 0
                
            elif strategy == "custom_list":
                custom_scenes = LTX_VIDEO_CONFIG["scene_selection"]["custom_scenes"]
                should_animate = scene_num in custom_scenes
            
            if should_animate:
                scenes_to_animate.append(scene_num)
        
        if not scenes_to_animate:
            print("⏭️ Нет сцен для LTX анимации")
            return
        
        print(f"🎯 Сцены для LTX анимации: {scenes_to_animate}")
        
        # Запускаем LTX анимацию в отдельном потоке
        import threading
        
        def run_ltx_animation():
            try:
                from autovid.backend.flows.steps.ltx_video_animate import LTXVideoManager
                manager = LTXVideoManager(int(self.project_id), self.video_format)
                
                # Ждем готовности базовых сцен для LTX анимации
                print("⏳ Ожидаем готовности базовых сцен для LTX анимации...")
                
                from concurrent.futures import ThreadPoolExecutor, as_completed
                
                def wait_and_animate(sn: int) -> bool:
                    print(f"🎬 Ожидаем готовности базовой сцены {sn} для LTX анимации...")
                    while True:
                        base_scene_path = self.output_dir / f"scene_{str(sn).zfill(3)}.mp4"
                        if base_scene_path.exists() and mp4_quick_check(base_scene_path):
                            print(f"✅ Базовая сцена {sn} готова, отправляем в LTX")
                            break
                        time.sleep(2)
                    return manager.animate_scene(sn)
                
                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures = {pool.submit(wait_and_animate, scene_num): scene_num for scene_num in scenes_to_animate}
                    for fut in as_completed(futures):
                        sn = futures[fut]
                        try:
                            ok = fut.result()
                            print(f"✅ LTX анимация для сцены {sn} завершена: {ok}")
                        except Exception as e:
                            print(f"❌ Ошибка LTX анимации для сцены {sn}: {e}")
                
            except Exception as e:
                print(f"❌ Критическая ошибка LTX анимации: {e}")
        
        # Запускаем в фоне
        ltx_thread = threading.Thread(target=run_ltx_animation, daemon=True)
        ltx_thread.start()
        print(f"🚀 LTX анимация запущена в фоне для {len(scenes_to_animate)} сцен")
        
        # Сохраняем информацию о запущенных анимациях для отслеживания
        self.ltx_animations = scenes_to_animate
    
    def _wait_for_ltx_animation(self) -> None:
        """Ждет завершения всех LTX анимаций с fail-fast по таймауту и диагностикой."""
        if not hasattr(self, 'ltx_animations') or not self.ltx_animations:
            print("⏭️ Нет LTX анимаций для ожидания")
            return
        
        print(f"⏳ Ожидаем завершения LTX анимации для сцен: {self.ltx_animations}")
        
        # Ждем с ограничением времени, чтобы не зависать бесконечно при неверном RUNPOD_LTX_ID
        check_interval = 3
        max_wait_seconds = 15 * 60  # 15 минут
        waited = 0
        while True:
            completed_scenes = []
            
            for scene_id in self.ltx_animations:
                # Проверяем наличие анимированного файла
                animated_path = self.output_dir / f"scene_{str(scene_id).zfill(3)}_animated.mp4"
                if animated_path.exists():
                    # Проверяем что файл не пустой и можно читать
                    try:
                        if animated_path.stat().st_size > 0 and mp4_quick_check(animated_path):
                            completed_scenes.append(scene_id)
                            print(f"✅ LTX анимация для сцены {scene_id} завершена")
                        else:
                            print(f"⏳ LTX анимация для сцены {scene_id} еще в процессе (файл существует но не готов)")
                    except Exception as e:
                        print(f"⏳ LTX анимация для сцены {scene_id} еще в процессе (ошибка проверки: {e})")
                else:
                    print(f"⏳ LTX анимация для сцены {scene_id} еще в процессе (файл не найден)")
            
            # Если все анимации завершены
            if len(completed_scenes) == len(self.ltx_animations):
                print(f"🎉 Все LTX анимации завершены! Сцены: {completed_scenes}")
                break
            
            remaining = set(self.ltx_animations) - set(completed_scenes)
            print(f"⏳ Ожидаем завершения LTX анимации для сцен: {sorted(remaining)}")
            time.sleep(check_interval)
            waited += check_interval

            if waited >= max_wait_seconds:
                # Диагностика окружения для LTX
                ltx_id = os.getenv("RUNPOD_LTX_ID", "unknown")
                base_url = f"https://{ltx_id}-8000.proxy.runpod.net"
                raise RuntimeError(
                    "Таймаут ожидания LTX анимации. "
                    f"RUNPOD_LTX_ID={ltx_id}, base_url={base_url}. "
                    "Проверьте корректность идентификатора и доступность LTX сервиса."
                )
    
    def _start_ltx_animation_if_needed(self, scene: SceneInfo) -> None:
        """Запускает LTX Video анимацию для сцены если она выбрана в конфигурации"""
        if not LTX_VIDEO_CONFIG["enabled"]:
            return
        
        scene_num = int(scene.scene_num)
        strategy = LTX_VIDEO_CONFIG["scene_selection"]["strategy"]
        
        # Проверяем должна ли эта сцена анимироваться
        should_animate = False
        
        if strategy == "first_n":
            count = LTX_VIDEO_CONFIG["scene_selection"]["count"]
            if self.video_format == "shorts":
                count = min(count, LTX_VIDEO_CONFIG["scene_selection"]["max_scenes_for_shorts"])
            should_animate = scene_num <= count
            
        elif strategy == "every_nth":
            step = LTX_VIDEO_CONFIG["scene_selection"]["step"]
            should_animate = scene_num % step == 0
            
        elif strategy == "custom_list":
            custom_scenes = LTX_VIDEO_CONFIG["scene_selection"]["custom_scenes"]
            should_animate = scene_num in custom_scenes
        
        if should_animate:
            print(f"🎬 Запускаем LTX Video анимацию для сцены {scene_num}")
            # Импортируем здесь чтобы избежать циклических импортов
            from autovid.backend.flows.steps.ltx_video_animate import LTXVideoManager
            manager = LTXVideoManager(int(self.project_id), self.video_format)
            manager.animate_scene(scene_num)
        else:
            print(f"⏭️ Сцена {scene_num} не выбрана для LTX Video анимации")
    
if __name__ == "__main__":
    project_id = sys.argv[1]
    video_format = sys.argv[2] if len(sys.argv) > 2 else "long"
    SceneAnimationManager(project_id, video_format).run()