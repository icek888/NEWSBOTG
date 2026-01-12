import os
import requests
from PIL import Image
import io
from app.config import settings


class ImageProcessor:
    def __init__(self):
        self.cache_dir = "images/cache"
        os.makedirs(self.cache_dir, exist_ok=True)
    
    async def process_image(self, image_url: str, news_id: int) -> str:
        """Обработка изображения для Telegram"""
        # Проверяем кэш
        cached_path = self._get_cached_path(image_url, news_id)
        if os.path.exists(cached_path):
            return cached_path
        
        # Скачиваем изображение
        try:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            
            # Открываем изображение
            img = Image.open(io.BytesIO(response.content))
            
            # Оптимизируем для Telegram
            img.thumbnail((1200, 630), Image.LANCZOS)
            
            # Сохраняем
            img.save(cached_path, 'JPEG', quality=85, optimize=True)
            return cached_path
            
        except Exception as e:
            print(f"Error processing image: {e}")
            return None
    
    def _get_cached_path(self, image_url: str, news_id: int) -> str:
        """Генерация пути для кэшированного изображения"""
        filename = f"{news_id}_{hash(image_url)}.jpg"
        return os.path.join(self.cache_dir, filename)