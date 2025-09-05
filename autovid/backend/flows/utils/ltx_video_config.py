"""
ltx_video_config.py
------------------
Утилиты для управления конфигурацией LTX-Video анимации.
Позволяет легко изменять стратегии выбора сцен и тестировать систему.
"""
from typing import List, Dict, Any
from pathlib import Path

from autovid.backend.config import LTX_VIDEO_CONFIG


class LTXVideoConfigManager:
    """Класс для управления конфигурацией LTX-Video"""
    
    @staticmethod
    def enable_ltx_video():
        """Включает LTX-Video анимацию"""
        LTX_VIDEO_CONFIG["enabled"] = True
        print("✅ LTX-Video анимация включена")
    
    @staticmethod
    def disable_ltx_video():
        """Отключает LTX-Video анимацию"""
        LTX_VIDEO_CONFIG["enabled"] = False
        print("⏸️ LTX-Video анимация отключена")
    
    @staticmethod
    def set_first_n_scenes(count: int):
        """Устанавливает анимацию первых N сцен"""
        LTX_VIDEO_CONFIG["scene_selection"]["strategy"] = "first_n"
        LTX_VIDEO_CONFIG["scene_selection"]["count"] = count
        print(f"🎯 Настроена анимация первых {count} сцен")
    
    @staticmethod
    def set_every_nth_scene(step: int):
        """Устанавливает анимацию каждой N-й сцены"""
        LTX_VIDEO_CONFIG["scene_selection"]["strategy"] = "every_nth"
        LTX_VIDEO_CONFIG["scene_selection"]["step"] = step
        print(f"🎯 Настроена анимация каждой {step}-й сцены")
    
    @staticmethod
    def set_custom_scenes(scene_list: List[int]):
        """Устанавливает анимацию конкретных сцен"""
        LTX_VIDEO_CONFIG["scene_selection"]["strategy"] = "custom_list"
        LTX_VIDEO_CONFIG["scene_selection"]["custom_scenes"] = scene_list
        print(f"🎯 Настроена анимация сцен: {scene_list}")
    
    @staticmethod
    def set_animation_duration(target: float = 4.0, max_dur: float = 6.0, threshold: float = 6.5):
        """Настраивает параметры длительности анимации"""
        LTX_VIDEO_CONFIG["duration_settings"]["target_animation_duration"] = target
        LTX_VIDEO_CONFIG["duration_settings"]["max_animation_duration"] = max_dur
        LTX_VIDEO_CONFIG["duration_settings"]["scene_split_threshold"] = threshold
        print(f"⏱️ Длительность анимации: цель {target}с, макс {max_dur}с, разбивать от {threshold}с")
    
    @staticmethod
    def use_original_prompts(enabled: bool = True):
        """Включает/выключает использование оригинальных промптов сцен"""
        LTX_VIDEO_CONFIG["prompt_settings"]["use_original_prompts"] = enabled
        status = "включено" if enabled else "выключено"
        print(f"📝 Использование оригинальных промптов: {status}")
    
    @staticmethod
    def set_universal_prompt(prompt: str):
        """Устанавливает универсальный промпт для всех анимаций"""
        LTX_VIDEO_CONFIG["prompt_settings"]["universal_prompt"] = prompt
        LTX_VIDEO_CONFIG["prompt_settings"]["use_original_prompts"] = False
        print(f"📝 Установлен универсальный промпт: {prompt[:50]}...")
    
    @staticmethod
    def set_animation_style(suffix: str):
        """Устанавливает суффикс стиля анимации"""
        LTX_VIDEO_CONFIG["prompt_settings"]["animation_style_suffix"] = suffix
        print(f"🎨 Суффикс анимации: {suffix}")
    
    @staticmethod
    def enable_seed_variation(enabled: bool = True):
        """Включает/выключает вариацию seeds для частей сцен"""
        LTX_VIDEO_CONFIG["prompt_settings"]["vary_seeds_for_parts"] = enabled
        status = "включена" if enabled else "выключена"
        print(f"🎲 Вариация seeds для частей: {status}")
    
    @staticmethod
    def get_current_config() -> Dict[str, Any]:
        """Возвращает текущую конфигурацию"""
        return {
            "enabled": LTX_VIDEO_CONFIG["enabled"],
            "api_base_url": LTX_VIDEO_CONFIG["api_base_url"],
            "scene_selection": LTX_VIDEO_CONFIG["scene_selection"].copy(),
            "duration_settings": LTX_VIDEO_CONFIG["duration_settings"].copy(),
            "prompt_settings": LTX_VIDEO_CONFIG["prompt_settings"].copy(),
            "video_params": LTX_VIDEO_CONFIG["video_params"].copy()
        }
    
    @staticmethod
    def print_config():
        """Выводит текущую конфигурацию"""
        config = LTXVideoConfigManager.get_current_config()
        print("\n📋 Текущая конфигурация LTX-Video:")
        print(f"   Включено: {'✅' if config['enabled'] else '❌'}")
        print(f"   API URL: {config['api_base_url']}")
        
        # Выбор сцен
        print(f"\n🎯 Выбор сцен:")
        print(f"   Стратегия: {config['scene_selection']['strategy']}")
        strategy = config['scene_selection']['strategy']
        if strategy == "first_n":
            print(f"   Количество сцен: {config['scene_selection']['count']}")
        elif strategy == "every_nth":
            print(f"   Каждая N-я сцена: {config['scene_selection']['step']}")
        elif strategy == "custom_list":
            print(f"   Конкретные сцены: {config['scene_selection']['custom_scenes']}")
        
        # Длительность
        print(f"\n⏱️ Настройки длительности:")
        dur = config['duration_settings']
        print(f"   Целевая длительность: {dur['target_animation_duration']}с")
        print(f"   Максимальная длительность: {dur['max_animation_duration']}с")
        print(f"   Порог разбиения: {dur['scene_split_threshold']}с")
        print(f"   Перекрытие частей: {dur['overlap_duration']}с")
        
        # Промпты
        print(f"\n📝 Настройки промптов:")
        prompts = config['prompt_settings']
        print(f"   Использовать оригинальные: {'✅' if prompts['use_original_prompts'] else '❌'}")
        if not prompts['use_original_prompts']:
            print(f"   Универсальный промпт: {prompts['universal_prompt'][:50]}...")
        print(f"   Суффикс анимации: {prompts['animation_style_suffix']}")
        print(f"   Вариация seeds: {'✅' if prompts['vary_seeds_for_parts'] else '❌'}")
        
        # Параметры видео
        print(f"\n🎥 Параметры видео:")
        print(f"   Базовый seed: {config['video_params']['seed']}")
        print()


class LTXVideoTester:
    """Класс для тестирования LTX-Video системы"""
    
    @staticmethod
    def test_api_connection():
        """Тестирует подключение к LTX-Video API"""
        import requests
        
        api_url = LTX_VIDEO_CONFIG["api_base_url"]
        try:
            response = requests.get(f"{api_url}/health", timeout=10)
            if response.status_code == 200:
                print(f"✅ LTX-Video API доступен: {api_url}")
                return True
            else:
                print(f"❌ LTX-Video API недоступен: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Ошибка подключения к LTX-Video API: {e}")
            return False
    
    @staticmethod
    def simulate_scene_selection(project_id: int, total_scenes: int, video_format: str = "long"):
        """Симулирует выбор сцен для анимации"""
        from autovid.backend.flows.steps.ltx_video_animate import SceneSelector
        
        scenes = SceneSelector.get_scenes_to_animate(project_id, video_format, total_scenes)
        
        print(f"\n🎬 Симуляция выбора сцен:")
        print(f"   Проект: {project_id}")
        print(f"   Формат: {video_format}")
        print(f"   Всего сцен: {total_scenes}")
        print(f"   Сцены для анимации: {scenes}")
        print(f"   Количество анимируемых: {len(scenes)}")
        
        return scenes
    
    @staticmethod
    def simulate_duration_analysis(project_id: int, scene_ids: List[int] = None):
        """Симулирует анализ длительности сцен"""
        from autovid.backend.flows.steps.ltx_video_animate import SceneDurationAnalyzer
        
        analyzer = SceneDurationAnalyzer(project_id)
        
        if scene_ids is None:
            scene_ids = [1, 2, 3, 4, 5]  # Тестируем первые 5 сцен
        
        print(f"\n⏱️ Анализ длительности сцен проекта {project_id}:")
        total_duration = 0
        scenes_to_split = []
        
        for scene_id in scene_ids:
            duration = analyzer.get_scene_duration(scene_id)
            if duration > 0:
                total_duration += duration
                parts = analyzer.calculate_scene_parts(scene_id)
                print(f"   Сцена {scene_id}: {duration:.1f}с → {len(parts)} частей")
                if len(parts) > 1:
                    scenes_to_split.append(scene_id)
                    for i, (start, dur) in enumerate(parts):
                        print(f"     Часть {i+1}: {start:.1f}с - {start+dur:.1f}с ({dur:.1f}с)")
        
        print(f"\n📊 Итого: {len(scene_ids)} сцен, {total_duration:.1f}с общая длительность")
        print(f"   Сцены для разбиения: {len(scenes_to_split)} ({scenes_to_split})")
        
        return scenes_to_split
    
    @staticmethod
    def test_prompt_loading(project_id: int):
        """Тестирует загрузку промптов"""
        from autovid.backend.flows.steps.ltx_video_animate import PromptManager
        
        print(f"\n📝 Тестирование промптов проекта {project_id}:")
        
        prompt_manager = PromptManager(project_id)
        prompts = prompt_manager.load_prompts()
        
        if not prompts:
            print("   ❌ Промпты не найдены")
            return False
        
        print(f"   ✅ Загружено {len(prompts)} промптов")
        
        # Показываем примеры промптов
        for scene_id in list(prompts.keys())[:3]:  # Первые 3 сцены
            original_prompt = prompts[scene_id]
            scene_prompt = prompt_manager.get_scene_prompt(scene_id)
            
            print(f"\n   Сцена {scene_id}:")
            print(f"     Оригинал: {original_prompt[:60]}...")
            print(f"     Для анимации: {scene_prompt[:60]}...")
        
        return True
    
    @staticmethod
    def check_project_scenes(project_id: int):
        """Проверяет состояние сцен проекта"""
        video_dir = Path(f"assets/video/{project_id}")
        scenes_dir = Path(f"assets/scenes/{project_id}")
        audio_dir = Path(f"assets/audio/{project_id}")
        
        print(f"\n📁 Проверка сцен проекта {project_id}:")
        
        if not video_dir.exists():
            print(f"   ❌ Папка видео не существует: {video_dir}")
            return
        
        if not scenes_dir.exists():
            print(f"   ❌ Папка изображений не существует: {scenes_dir}")
            return
        
        if not audio_dir.exists():
            print(f"   ❌ Папка аудио не существует: {audio_dir}")
            return
        
        # Подсчитываем файлы
        video_files = list(video_dir.glob("scene_*.mp4"))
        image_files = list(scenes_dir.glob("scene_*.jpg")) + list(scenes_dir.glob("scene_*.png"))
        audio_files = list(audio_dir.glob("scene_*.mp3"))
        
        print(f"   📹 Видео сцен: {len(video_files)}")
        print(f"   🖼️ Изображений: {len(image_files)}")
        print(f"   🎵 Аудио файлов: {len(audio_files)}")
        
        # Проверяем готовность для LTX-Video
        ready_scenes = []
        for video_file in video_files:
            if video_file.stat().st_size > 100_000:  # Файл больше 100KB
                scene_num = int(video_file.stem.split('_')[1])
                ready_scenes.append(scene_num)
        
        print(f"   ✅ Готовых сцен: {len(ready_scenes)}")
        if ready_scenes:
            print(f"   📋 Номера готовых сцен: {sorted(ready_scenes)}")


# Быстрые функции для использования в скриптах
def enable_ltx_video():
    """Быстрое включение LTX-Video"""
    LTXVideoConfigManager.enable_ltx_video()

def disable_ltx_video():
    """Быстрое отключение LTX-Video"""
    LTXVideoConfigManager.disable_ltx_video()

def animate_first_scenes(count: int = 10):
    """Быстрая настройка анимации первых N сцен"""
    LTXVideoConfigManager.set_first_n_scenes(count)

def animate_every_nth_scene(step: int = 2):
    """Быстрая настройка анимации каждой N-й сцены"""
    LTXVideoConfigManager.set_every_nth_scene(step)

def animate_custom_scenes(scenes: List[int]):
    """Быстрая настройка анимации конкретных сцен"""
    LTXVideoConfigManager.set_custom_scenes(scenes)

def set_short_animations(target: float = 3.0):
    """Быстрая настройка для коротких анимаций"""
    LTXVideoConfigManager.set_animation_duration(target=target, max_dur=5.0, threshold=5.5)
    print(f"🚀 Настроены короткие анимации ({target}с)")

def set_long_animations(target: float = 5.0):
    """Быстрая настройка для длинных анимаций"""
    LTXVideoConfigManager.set_animation_duration(target=target, max_dur=7.0, threshold=7.5)
    print(f"🎬 Настроены длинные анимации ({target}с)")

def use_original_prompts():
    """Быстрое включение оригинальных промптов"""
    LTXVideoConfigManager.use_original_prompts(True)

def use_universal_prompt(prompt: str = None):
    """Быстрое включение универсального промпта"""
    if prompt is None:
        prompt = "Add smooth, cinematic animation to this image with gentle camera movement"
    LTXVideoConfigManager.set_universal_prompt(prompt)

def show_config():
    """Быстрый вывод конфигурации"""
    LTXVideoConfigManager.print_config()

def test_system():
    """Быстрый тест системы"""
    print("🧪 Тестирование LTX-Video системы...")
    show_config()
    LTXVideoTester.test_api_connection()

def analyze_project(project_id: int):
    """Быстрый анализ проекта"""
    print(f"🔍 Анализ проекта {project_id}...")
    LTXVideoTester.check_project_scenes(project_id)
    LTXVideoTester.test_prompt_loading(project_id)
    LTXVideoTester.simulate_duration_analysis(project_id)


if __name__ == "__main__":
    # Пример использования
    print("🎬 LTX-Video Configuration Manager")
    print("=" * 40)
    
    show_config()
    test_system()
    
    # Демонстрация новых возможностей
    print("\n🎯 Демонстрация конфигурации:")
    set_short_animations(3.5)
    use_original_prompts()
    animate_first_scenes(5)
    
    print("\n📊 Симуляция:")
    LTXVideoTester.simulate_scene_selection(project_id=1, total_scenes=15, video_format="long")
    LTXVideoTester.simulate_scene_selection(project_id=1, total_scenes=8, video_format="shorts") 