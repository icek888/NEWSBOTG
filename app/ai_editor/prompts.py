from sqlalchemy import select, update
from app.database import get_session
from app.models.base import PromptConfig

from app.utils.logger import setup_logger
logger = setup_logger(__name__)


class PromptManager:
    """Управление промптами из БД с fallback в код"""

    # Дефолтные промпты (fallback)
    DEFAULT_PROMPTS = {
        "editor_ru": """Ты - редактор AI-новостей для Telegram канала.

Задача: Преобразуй новость в брендированный пост на русском языке.

Правила:
1. Заголовок: ёмкий, кликабельный (до 80 символов)
2. Буллеты: 3-5 ключевых фактов
3. "Что это значит": объяснение простым языком (1-2 предложения)
4. Теги: 3-5 релевантных тегов
5. Тон: профессиональный, но доступный

Формат ответа (строго JSON):
{
  "headline": "Краткий заголовок",
  "summary_bullets": ["факт1", "факт2", "факт3"],
  "meaning": "Что это значит простыми словами",
  "tags": ["ai", "llm", "news"],
  "final_post_html": "<b>Заголовок</b>\\n\\nФакты...\\n\\n<i>Что это значит</i>"
}""",
        "editor_en": """You are an AI news editor for Telegram channel.

Task: Transform news into a branded post in English.

Rules:
1. Headline: concise, click-worthy (up to 80 chars)
2. Bullets: 3-5 key facts
3. "What this means": explanation in simple terms (1-2 sentences)
4. Tags: 3-5 relevant tags
5. Tone: professional but accessible

Response format (strict JSON):
{
  "headline": "Short headline",
  "summary_bullets": ["fact1", "fact2", "fact3"],
  "meaning": "What this means in simple terms",
  "tags": ["ai", "llm", "news"],
  "final_post_html": "<b>Headline</b>\\n\\nFacts...\\n\\n<i>What this means</i>"
}""",
    }

    async def get_prompt(self, key: str) -> str:
        """Получить активный промпт из БД или fallback"""
        async for db in get_session():
            stmt = (
                select(PromptConfig)
                .where(PromptConfig.key == key)
                .where(PromptConfig.is_active == True)
                .order_by(PromptConfig.version.desc())
                .limit(1)
            )
            res = await db.execute(stmt)
            config = res.scalars().first()

            if config:
                logger.info(f"Using prompt from DB: {key} v{config.version}")
                return config.content

            fallback = self.DEFAULT_PROMPTS.get(key, "")
            if fallback:
                logger.warning(f"Using fallback prompt for: {key}")
            else:
                logger.error(f"No prompt found for key: {key}")
            return fallback

    async def save_prompt(self, key: str, content: str) -> PromptConfig:
        """Сохранить новую версию промпта"""
        async for db in get_session():
            # Получить последнюю версию
            stmt = (
                select(PromptConfig)
                .where(PromptConfig.key == key)
                .order_by(PromptConfig.version.desc())
                .limit(1)
            )
            res = await db.execute(stmt)
            last = res.scalars().first()
            next_version = (last.version + 1) if last else 1

            # Деактивировать старые версии этого ключа
            await db.execute(
                update(PromptConfig)
                .where(PromptConfig.key == key)
                .values(is_active=False)
            )

            # Создать новую версию
            config = PromptConfig(
                key=key,
                content=content,
                version=next_version,
                is_active=True
            )
            db.add(config)
            await db.commit()
            await db.refresh(config)
            logger.info(f"Saved new prompt version: {key} v{next_version}")
            return config

    async def list_prompts(self) -> list[PromptConfig]:
        """Получить список всех промптов с версиями"""
        async for db in get_session():
            stmt = (
                select(PromptConfig)
                .where(PromptConfig.is_active == True)
                .order_by(PromptConfig.key.asc())
            )
            res = await db.execute(stmt)
            return list(res.scalars().all())
