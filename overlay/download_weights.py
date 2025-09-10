from huggingface_hub import hf_hub_download
import os

print("🎬 Проверяем веса LTX-Video...")

# Создаем папку для моделей
os.makedirs("models", exist_ok=True)

# Проверяем существование файлов
main_model_path = "./models/ltxv-13b-0.9.8-distilled.safetensors"
upscaler_path = "./models/ltxv-spatial-upscaler-0.9.8.safetensors"

if os.path.exists(main_model_path) and os.path.exists(upscaler_path):
    print("✅ Веса уже загружены! Пропускаем загрузку.")
    print(f"📁 Основная модель: {main_model_path}")
    print(f"📁 Upscaler: {upscaler_path}")
else:
    print("📥 Начинаем загрузку весов...")
    
    # Скачиваем основную модель (13B distilled)
    if not os.path.exists(main_model_path):
        print("📥 Скачиваем основную модель ltxv-13b-0.9.8-distilled...")
        hf_hub_download(
            repo_id="Lightricks/LTX-Video",
            filename="ltxv-13b-0.9.8-distilled.safetensors",
            local_dir="./models",
    local_dir_use_symlinks=False
)
    else:
        print("✅ Основная модель уже существует")

# Скачиваем spatial upscaler
    if not os.path.exists(upscaler_path):
        print("📥 Скачиваем spatial upscaler...")
        hf_hub_download(
            repo_id="Lightricks/LTX-Video",
            filename="ltxv-spatial-upscaler-0.9.8.safetensors",
            local_dir="./models",
    local_dir_use_symlinks=False
)
    else:
        print("✅ Upscaler уже существует")

    print("✅ Все веса загружены успешно!")