# 🎬 LTX-Video API Документация

## 🚀 Быстрый старт

### Базовый URL
```
https://y4q99s523clow6-8000.proxy.runpod.net
```

### 1. Простейший запрос (Text-to-Video)
```bash
curl -X POST "https://y4q99s523clow6-8000.proxy.runpod.net/generate" \
  -F "prompt=A cat walking in the garden"
```

**Ответ:**
```json
{"task_id": "abc123-def456-ghi789"}
```

### 2. Проверка статуса
```bash
curl "https://y4q99s523clow6-8000.proxy.runpod.net/status/abc123-def456-ghi789"
```

**Ответ:**
```json
{"task_id": "abc123-def456-ghi789", "status": "SUCCESS", "result": "task_results/result_xyz.mp4"}
```

### 3. Скачивание видео
```bash
curl "https://y4q99s523clow6-8000.proxy.runpod.net/video/result_xyz.mp4" -o video.mp4
```

---

## 📚 Полная документация

### 🌐 Базовый URL
```
https://y4q99s523clow6-8000.proxy.runpod.net
```

### 📖 Swagger UI документация
```
https://y4q99s523clow6-8000.proxy.runpod.net/docs
```

---

## 🎬 1. Создание задачи генерации видео

### **POST** `/generate`

#### Text-to-Video (без изображения)
```bash
curl -X POST "https://y4q99s523clow6-8000.proxy.runpod.net/generate" \
  -H "Content-Type: multipart/form-data" \
  -F "prompt=A beautiful sunset over mountains with clouds moving slowly" \
  -F "negative_prompt=worst quality, blurry, distorted, jittery" \
  -F "width=1280" \
  -F "height=720" \
  -F "num_frames=120" \
  -F "seed=42"
```

#### Image-to-Video (с изображением)
```bash
curl -X POST "https://y4q99s523clow6-8000.proxy.runpod.net/generate" \
  -H "Content-Type: multipart/form-data" \
  -F "prompt=Animate this scene with gentle movement" \
  -F "negative_prompt=worst quality, blurry, distorted" \
  -F "width=1280" \
  -F "height=720" \
  -F "num_frames=120" \
  -F "seed=42" \
  -F "image=@/path/to/your/image.jpg"
```

#### Параметры
| Параметр | Тип | Обязательный | По умолчанию | Описание |
|----------|-----|--------------|--------------|----------|
| `prompt` | string | ✅ | - | Описание желаемого видео |
| `negative_prompt` | string | ❌ | "worst quality, inconsistent motion, blurry, jittery, distorted" | Что исключить из видео |
| `width` | integer | ❌ | 1280 | Ширина видео |
| `height` | integer | ❌ | 720 | Высота видео |
| `num_frames` | integer | ❌ | 120 | Количество кадров |
| `seed` | integer | ❌ | 42 | Seed для воспроизводимости |
| `image` | file | ❌ | null | Изображение для image-to-video |

#### Ответ
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

---

## 📊 2. Проверка статуса задачи

### **GET** `/status/{task_id}`

```bash
curl -X GET "https://y4q99s523clow6-8000.proxy.runpod.net/status/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

#### Возможные ответы

**В процессе:**
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "PENDING",
  "result": null
}
```

**Выполняется:**
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "STARTED",
  "result": null
}
```

**Успешно завершено:**
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "SUCCESS",
  "result": "task_results/result_xyz123.mp4"
}
```

**Ошибка:**
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "FAILURE",
  "result": "Error message description"
}
```

#### Статусы задач
| Статус | Описание |
|--------|----------|
| `PENDING` | Задача в очереди |
| `STARTED` | Задача выполняется |
| `SUCCESS` | Задача завершена успешно |
| `FAILURE` | Ошибка выполнения |

---

## 🎥 3. Скачивание готового видео

### **GET** `/video/{filename}`

```bash
curl -X GET "https://y4q99s523clow6-8000.proxy.runpod.net/video/result_xyz123.mp4" \
  --output "my_generated_video.mp4"
```

---

## 🔄 Полный рабочий процесс

### Bash скрипт для автоматизации:

```bash
#!/bin/bash

API_BASE="https://y4q99s523clow6-8000.proxy.runpod.net"

# 1. Создаем задачу
echo "🎬 Создаем задачу генерации..."
RESPONSE=$(curl -s -X POST "$API_BASE/generate" \
  -F "prompt=A majestic eagle soaring through mountain valleys" \
  -F "width=1280" \
  -F "height=720" \
  -F "num_frames=120" \
  -F "seed=42")

# 2. Извлекаем task_id
TASK_ID=$(echo $RESPONSE | grep -o '"task_id":"[^"]*"' | cut -d'"' -f4)
echo "📋 Task ID: $TASK_ID"

# 3. Ждем выполнения
echo "⏳ Ожидаем выполнения..."
while true; do
  STATUS_RESPONSE=$(curl -s "$API_BASE/status/$TASK_ID")
  STATUS=$(echo $STATUS_RESPONSE | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
  echo "📊 Статус: $STATUS"
  
  if [ "$STATUS" = "SUCCESS" ]; then
    # 4. Извлекаем путь к видео
    RESULT=$(echo $STATUS_RESPONSE | grep -o '"result":"[^"]*"' | cut -d'"' -f4)
    echo "✅ Видео готово: $RESULT"
    
    # 5. Скачиваем видео
    FILENAME=$(basename "$RESULT")
    curl -X GET "$API_BASE/video/$FILENAME" --output "generated_video.mp4"
    echo "💾 Видео скачано как generated_video.mp4"
    break
  elif [ "$STATUS" = "FAILURE" ]; then
    echo "❌ Ошибка генерации!"
    echo $STATUS_RESPONSE
    break
  fi
  
  sleep 10
done
```

---

## 📝 Примеры промптов

### Text-to-Video
```bash
# Природа
"A peaceful lake with gentle ripples, surrounded by autumn trees with falling leaves"

# Городская сцена
"Busy city street at night with neon lights reflecting on wet pavement"

# Животные
"A group of dolphins jumping out of crystal clear ocean water"
```

### Image-to-Video промпты
```bash
# Добавление движения
"Add gentle camera movement and subtle animation to this scene"

# Природные эффекты
"Add wind effects making grass and leaves move naturally"

# Атмосферные эффекты
"Add floating particles and soft lighting changes"
```

---

## ⚠️ Ограничения и рекомендации

- **Время генерации**: 2-5 минут в зависимости от параметров
- **Максимальное разрешение**: 1280x720 рекомендуется
- **Поддерживаемые форматы изображений**: JPG, PNG
- **Размер изображения**: до 10MB
- **Формат вывода**: MP4

---

## 🚨 Коды ошибок

| Код | Описание |
|-----|----------|
| 200 | Успешный запрос |
| 422 | Ошибка валидации параметров |
| 404 | Видео файл не найден |
| 500 | Внутренняя ошибка сервера | 