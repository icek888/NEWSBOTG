import asyncio
from bs4 import BeautifulSoup
from typing import List, Dict
from sqlalchemy import select
from app.parsers.base_parser import BaseParser
from app.database import AsyncSessionLocal
from app.models.base import News
from app.utils.logger import setup_logger
logger = setup_logger(__name__)


class TechCrunchParser(BaseParser):
    async def parse(self) -> List[Dict]:
        listing_html = await self._get_html(self.source.url)
        if not listing_html:
            return []

        soup = BeautifulSoup(listing_html, "html.parser")
        links = soup.find_all("a", class_="loop-card__title-link")

        # 1) соберём уникальные url
        candidates: List[Dict] = []
        seen = set()
        for link in links:
            title = link.get_text(strip=True)
            url = link.get("href")
            if not url or url in seen:
                continue
            seen.add(url)
            candidates.append({"title": title, "url": url, "source": self.source.name})

        if not candidates:
            return []

        # 2) отфильтруем уже сохранённые в БД (чтобы не делать лишние запросы)
        urls = [c["url"] for c in candidates]
        existing = set()
        async with AsyncSessionLocal() as s:
            res = await s.execute(select(News.url).where(News.url.in_(urls)))
            existing = {row[0] for row in res.all()}

        fresh = [c for c in candidates if c["url"] not in existing]
        if not fresh:
            return []

        # 3) догружаем детали параллельно (но с семафором из BaseParser)
        async def enrich(item: Dict) -> Dict:
            html = await self._get_html(item["url"])
            if not html:
                return item

            # og:image + дата + краткий контент
            item["image_url"] = self.extract_og_image(html)
            item["publish_date"] = self.extract_published_time(html)

            soup2 = BeautifulSoup(html, "html.parser")

            # короткий текст — для MVP. На TechCrunch часто есть абзацы в статье.
            paragraphs = [p.get_text(" ", strip=True) for p in soup2.select("article p")]
            text = " ".join(paragraphs[:3]).strip()  # первые 2-3 абзаца
            item["content"] = text[:1200] if text else None

            return item

        enriched = await asyncio.gather(*(enrich(x) for x in fresh))
        return enriched

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
