import re
import asyncio
from bs4 import BeautifulSoup
from typing import List, Dict
from urllib.parse import urljoin
from app.parsers.base_parser import BaseParser
from app.utils.logger import setup_logger
logger = setup_logger(__name__)

ARTICLE_RE = re.compile(r"^https?://(www\.)?theverge\.com/\d{4}/\d{1,2}/\d{1,2}/")

class TheVergeParser(BaseParser):
    async def parse(self) -> List[Dict]:
        html = await self._get_html(self.source.url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")

        # 1) собираем кандидатов: все ссылки
        urls = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href:
                continue
            full = urljoin("https://www.theverge.com", href)
            if ARTICLE_RE.match(full):
                urls.add(full)

        candidates = [{"url": u, "title": None, "source": self.source.name} for u in sorted(urls)]
        logger.info(f"🧩 The Verge: найдено ссылок на статьи: {len(candidates)}")

        # 2) MVP вариант: не заходить внутрь, если боишься paywall.
        # Просто вернём url + заголовок из текста ссылки (если есть).
        # Но лучше — догрузить og:title/og:image.
        async def enrich(item: Dict) -> Dict:
            page = await self._get_html(item["url"])
            if not page:
                return item
            item["title"] = self.extract_title(page) or item.get("title")
            item["image_url"] = self.extract_og_image(page)
            item["publish_date"] = self.extract_published_time(page)
            item["content"] = self.extract_short_content(page)  # og:description / первые абзацы
            return item

        enriched = await asyncio.gather(*(enrich(x) for x in candidates[:20]))
        # ограничили 20, чтобы не долбить сайт

        # фильтруем пустые
        return [x for x in enriched if x.get("title") and x.get("url")]
