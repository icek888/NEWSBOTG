import os
import hashlib
import io
import aiohttp
from PIL import Image
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class ImageProcessor:
    def __init__(self, cache_dir: str = "images/cache"):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    async def process_image(self, image_url: str, news_id: int) -> str | None:
        """Асинхронная обработка изображения для Telegram"""
        cached_path = self._get_cached_path(image_url, news_id)
        if os.path.exists(cached_path):
            return cached_path

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            ) as session:
                async with session.get(image_url) as resp:
                    if resp.status != 200:
                        logger.warning(f"Image download failed: {resp.status} for {image_url}")
                        return None
                    data = await resp.read()

            img = Image.open(io.BytesIO(data))

            # Конвертируем RGBA → RGB если нужно
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # Оптимизируем для Telegram
            img.thumbnail((1200, 630), Image.LANCZOS)
            img.save(cached_path, "JPEG", quality=85, optimize=True)

            logger.info(f"Image cached: {cached_path}")
            return cached_path

        except Exception as e:
            logger.error(f"Error processing image {image_url}: {e}")
            return None

    def _get_cached_path(self, image_url: str, news_id: int) -> str:
        url_hash = hashlib.md5(image_url.encode()).hexdigest()[:12]
        return os.path.join(self.cache_dir, f"{news_id}_{url_hash}.jpg")
