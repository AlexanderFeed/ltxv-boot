from pruna import PrunaModel
import torch, time
    
t0 = time.time()
    
# 1. Загружаем веса сразу в FP16 (быстрее I/O)
pipe = PrunaModel.from_pretrained(
    "/workspace/auto_vid/models/pruna_flux_model",
    torch_dtype=torch.float16
)
    
    # 2. Переносим ВСЮ пайплайн‑структуру на CUDA и оставляем FP16
pipe = pipe.to(device="cuda", dtype=torch.float16)
    
    # 3. Переводим все под‑модули в режим eval
for name, module in pipe.components.items():      # text_encoder, vae, transformer …
    if isinstance(module, torch.nn.Module):
        module.eval()
    
    # 4. Отключаем глобальный расчёт градиентов
torch.set_grad_enabled(False)
    
print("⚡ cold‑start:", round(time.time() - t0, 2), "сек")
