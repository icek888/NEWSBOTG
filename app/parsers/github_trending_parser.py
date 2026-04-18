"""GitHub trending AI repos parser"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from sqlalchemy import select

import httpx
from app.parsers.base_parser import BaseParser
from app.database import AsyncSessionLocal
from app.models.base import News
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# GitHub search topics for AI repos
AI_TOPICS = [
    ("topic:ai+topic:tool", "stars:>30"),
    ("topic:llm+topic:agent", "stars:>20"),
    ("topic:machine-learning+topic:framework", "stars:>50"),
    ("topic:generative-ai", "stars:>30"),
    ("topic:artificial-intelligence+language:python", "stars:>50"),
]


class GitHubTrendingParser(BaseParser):
    """Парсер trending GitHub репозиториев в AI/ML тематике"""

    def __init__(self, source_obj, *, concurrency: int = 3):
        super().__init__(source_obj, concurrency=concurrency)
        self.github_token = None  # Optional: GITHUB_TOKEN env var

    async def parse(self, max_repos: int = 5) -> List[Dict]:
        """Получить trending AI репозитории за последнюю неделю"""
        all_repos = []

        async with httpx.AsyncClient(timeout=20) as client:
            for topic_query, stars_filter in AI_TOPICS:
                try:
                    repos = await self._search_topic(client, topic_query, stars_filter, per_page=3)
                    all_repos.extend(repos)
                except Exception as e:
                    logger.warning(f"GitHub search failed for {topic_query}: {e}")
                    continue

                await asyncio.sleep(1.5)  # Rate limit

        # Дедуп по full_name
        seen = set()
        unique = []
        for r in all_repos:
            if r["full_name"] not in seen:
                seen.add(r["full_name"])
                unique.append(r)

        # Сортировка по звёздам (недельный прирост если есть)
        unique.sort(key=lambda x: x.get("stars_weekly", x.get("stars", 0)), reverse=True)

        # Фильтруем уже опубликованные
        fresh = await self._filter_existing(unique)

        # Форматируем для News модели
        articles = []
        for repo in fresh[:max_repos]:
            articles.append(self._repo_to_article(repo))

        logger.info(f"🔧 GitHub trending: {len(articles)} fresh repos")
        return articles

    async def _search_topic(self, client: httpx.AsyncClient, topic: str,
                            stars_filter: str = "stars:>20",
                            per_page: int = 3) -> List[Dict]:
        """Поиск по GitHub Search API"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

        url = "https://api.github.com/search/repositories"
        params = {
            "q": f"{topic} {stars_filter} pushed:>{cutoff}",
            "sort": "stars",
            "order": "desc",
            "per_page": per_page,
        }
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"

        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            logger.warning(f"GitHub API {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        results = []
        for item in data.get("items", []):
            results.append({
                "full_name": item["full_name"],
                "description": item.get("description", "") or "",
                "url": item["html_url"],
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language", "Unknown"),
                "topics": item.get("topics", []),
                "updated_at": item.get("updated_at", ""),
                "open_issues": item.get("open_issues_count", 0),
                "forks": item.get("forks_count", 0),
            })
        return results

    async def _filter_existing(self, repos: List[Dict]) -> List[Dict]:
        """Убрать уже сохранённые репозитории"""
        urls = [r["url"] for r in repos]
        existing = set()

        async with AsyncSessionLocal() as s:
            res = await s.execute(select(News.url).where(News.url.in_(urls)))
            existing = {row[0] for row in res.all()}

        return [r for r in repos if r["url"] not in existing]

    def _repo_to_article(self, repo: Dict) -> Dict:
        """Конвертировать repo data в формат article для News"""
        desc = repo.get("description", "No description")
        topics = repo.get("topics", [])
        lang = repo.get("language", "Unknown")
        stars = repo.get("stars", 0)
        forks = repo.get("forks", 0)

        content = (
            f"{desc}\n\n"
            f"⭐ {stars:,} stars | 🔄 {forks:,} forks | 💻 {lang}\n"
            f"Topics: {', '.join(topics[:5]) if topics else 'N/A'}"
        )

        return {
            "title": f"🔧 GitHub: {repo['full_name']}",
            "content": content,
            "url": repo["url"],
            "image_url": None,
            "source": self.source.name,
            "publish_date": repo.get("updated_at"),
            "repo_data": repo,  # Для специального форматирования
        }

    async def parse_page(self) -> List[Dict]:
        """Совместимость с BaseParser interface"""
        return await self.parse()
