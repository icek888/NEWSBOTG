import aiohttp
import asyncio
from bs4 import BeautifulSoup
from typing import Optional, Dict
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.base import News
from app.utils.logger import setup_logger
from datetime import datetime, timezone

log = setup_logger(__name__)


class BaseParser:
    def __init__(self, source_obj, *, concurrency: int = 5):
        self.source = source_obj
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self._session: Optional[aiohttp.ClientSession] = None
        self._sem = asyncio.Semaphore(concurrency)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=25)
            self._session = aiohttp.ClientSession(headers=self.headers, timeout=timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    def normalize_url(self, url: str) -> str:
        """
        Убираем мусорные query-параметры (utm_*, ref, fbclid и т.д.)
        чтобы дедуп работал стабильнее.
        """
        try:
            p = urlparse(url)
            qs = parse_qsl(p.query, keep_blank_values=True)
            cleaned = []
            for k, v in qs:
                lk = k.lower()
                if lk.startswith("utm_"):
                    continue
                if lk in {"ref", "ref_src", "fbclid", "gclid", "mc_cid", "mc_eid"}:
                    continue
                cleaned.append((k, v))
            new_query = urlencode(cleaned, doseq=True)
            return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, ""))  # убираем fragment
        except Exception:
            return url

    async def _get_html(self, url: str) -> str:
        session = await self._get_session()
        try:
            async with self._sem:
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status >= 400:
                        return ""
                    return await resp.text()
        except Exception:
            return ""

    def _meta(self, soup: BeautifulSoup, *, prop: str | None = None, name: str | None = None) -> Optional[str]:
        tag = None
        if prop:
            tag = soup.find("meta", attrs={"property": prop})
        if not tag and name:
            tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
        return None

    def extract_og_image(self, html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        return self._meta(soup, prop="og:image") or self._meta(soup, name="twitter:image")

    def extract_published_time(self, html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        # 1) article:published_time
        t = self._meta(soup, prop="article:published_time")
        if t:
            return t
        # 2) time datetime
        time_tag = soup.find("time")
        if time_tag and time_tag.get("datetime"):
            return str(time_tag["datetime"]).strip()
        return None

    def extract_title(self, html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        return self._meta(soup, prop="og:title") or (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else None)

    def extract_description(self, html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        return self._meta(soup, prop="og:description") or self._meta(soup, name="description")

    def extract_short_content(self, html: str, *, max_chars: int = 1200) -> Optional[str]:
        """
        Универсальный MVP: берём og:description или первые абзацы article.
        """
        soup = BeautifulSoup(html, "html.parser")
        desc = self._meta(soup, prop="og:description") or self._meta(soup, name="description")
        if desc:
            return desc[:max_chars]

        ps = [p.get_text(" ", strip=True) for p in soup.select("article p")]
        text = " ".join(ps[:3]).strip()
        return text[:max_chars] if text else None

    @staticmethod
    def parse_dt(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            s = value.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                return None
        return None

    @staticmethod
    def to_utc_naive(dt: datetime | None) -> datetime | None:
        """
        Приводим дату к UTC-naive, чтобы писать в TIMESTAMP WITHOUT TIME ZONE.
        """
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt  # считаем уже naive (желательно чтобы это был UTC)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    async def save_article(self, article: Dict) -> bool:
        url = self.normalize_url(article["url"])
        publish_dt = self.to_utc_naive(self.parse_dt(article.get("publish_date")))

        async with AsyncSessionLocal() as db:
            try:
                # ✅ дедуп по нормализованному URL
                stmt = select(News).where(News.url == url)
                res = await db.execute(stmt)
                if res.scalar_one_or_none():
                    return False

                news = News(
                    source_id=self.source.id,
                    title=article.get("title"),
                    content=article.get("content"),
                    url=url,  # ✅ сохраняем нормализованный URL
                    image_url=article.get("image_url"),
                    publish_date=publish_dt,  # ✅ теперь naive
                    is_published=False,
                    is_breaking=article.get("is_breaking", False),
                )

                db.add(news)
                await db.commit()

                log.info(f"✅ Статья сохранена: {news.title[:60]}…")
                return True

            except Exception as e:
                await db.rollback()
                log.error(f"❌ Ошибка сохранения статьи: {e}", exc_info=True)
                return False