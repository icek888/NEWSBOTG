"""Analytics module — tracking post views, reactions, and daily stats"""

from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, update
from app.database import get_session
from app.models.base import News, Publication, Analytics, Source
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class AnalyticsTracker:
    """Сбор и хранение метрик публикаций"""

    def __init__(self):
        pass

    async def track(self, news_id: int, views: int = 0, reactions: int = 0,
                    comments: int = 0, reposts: int = 0):
        """Записать или обновить метрики для новости"""
        async for db in get_session():
            stmt = select(Analytics).where(Analytics.news_id == news_id)
            res = await db.execute(stmt)
            record = res.scalars().first()

            if not record:
                record = Analytics(news_id=news_id)
                db.add(record)

            record.views = views
            record.reactions = reactions
            record.comments = comments
            record.reposts = reposts
            if views > 0:
                record.click_rate = reactions / views

            await db.commit()

    async def get_stats(self, days: int = 7) -> dict:
        """Получить сводную статистику за N дней"""
        async for db in get_session():
            since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

            # Опубликованные за период
            pub_count = await db.execute(
                select(func.count(Publication.id))
                .where(Publication.status == "published")
                .where(Publication.published_at >= since)
            )
            published = pub_count.scalar() or 0

            # Средние просмотры
            avg_views = await db.execute(
                select(func.avg(Analytics.views))
                .join(Publication, Publication.news_id == Analytics.news_id)
                .where(Publication.published_at >= since)
            )
            avg_v = avg_views.scalar() or 0

            # Топ источник
            top_src = await db.execute(
                select(Source.name, func.count(News.id).label("cnt"))
                .join(News, News.source_id == Source.id)
                .join(Publication, Publication.news_id == News.id)
                .where(Publication.status == "published")
                .where(Publication.published_at >= since)
                .group_by(Source.name)
                .order_by(func.count(News.id).desc())
                .limit(1)
            )
            top = top_src.first()

            # Total reactions
            total_reactions = await db.execute(
                select(func.sum(Analytics.reactions))
                .join(Publication, Publication.news_id == Analytics.news_id)
                .where(Publication.published_at >= since)
            )
            reactions = total_reactions.scalar() or 0

            # Ожидающие модерацию
            pending = await db.execute(
                select(func.count(Publication.id))
                .where(Publication.status.in_(["review_raw", "ai_draft_ready"]))
            )
            pending_count = pending.scalar() or 0

            return {
                "period_days": days,
                "published": published,
                "pending_review": pending_count,
                "avg_views": round(avg_v, 1),
                "total_reactions": reactions,
                "top_source": top[0] if top else "N/A",
                "top_source_count": top[1] if top else 0,
            }

    async def format_stats_message(self, days: int = 7) -> str:
        """Форматировать статистику для отправки в Telegram"""
        stats = await self.get_stats(days)
        return (
            f"📊 <b>Статистика за {days} дней</b>\n\n"
            f"📝 Опубликовано: <b>{stats['published']}</b>\n"
            f"⏳ На модерации: <b>{stats['pending_review']}</b>\n"
            f"👁 Средние просмотры: <b>{stats['avg_views']}</b>\n"
            f"❤️ Всего реакций: <b>{stats['total_reactions']}</b>\n"
            f"📰 Топ источник: <b>{stats['top_source']}</b> ({stats['top_source_count']} постов)"
        )
