import re
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from telethon import TelegramClient, Button
from sqlalchemy import select, update
from sqlalchemy.orm import aliased

from app.config import settings
from app.database import get_session
from app.models.base import News, Publication, Source
from app.utils.logger import setup_logger
logger = setup_logger(__name__)


# Publication.status (используем как модерацию/паблишинг в MVP)
PUB_REVIEW_RAW = "review_raw"         # Сырая новость на модерации
PUB_AI_DRAFT_READY = "ai_draft_ready" # AI драфт готов
PUB_REVIEW = "review"                 # Для обратной совместимости
PUB_POSTPONED = "postponed"
PUB_REJECTED = "rejected"
PUB_PUBLISHED = "published"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize_html_text(s: Optional[str]) -> str:
    # Минимальная защита от случайных разрывов разметки.
    # (Без внешних libs: просто экранируем спецсимволы)
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


def _slug_tag(t: str) -> str:
    t = (t or "").strip().lower()
    t = re.sub(r"[^\w]+", "_", t, flags=re.UNICODE)
    t = re.sub(r"_+", "_", t).strip("_")
    return t


def _as_hashtags(tags) -> str:
    if not tags:
        return ""
    # tags может быть строкой "a, b, c" или списком
    if isinstance(tags, str):
        raw = [x.strip() for x in tags.split(",")]
    else:
        raw = [str(x).strip() for x in tags]

    cleaned = []
    for x in raw:
        s = _slug_tag(x)
        if s:
            cleaned.append(f"#{s}")
    # уникализируем сохраняя порядок
    out = []
    seen = set()
    for x in cleaned:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return " ".join(out)


def _render_channel_post_from_draft(news: News, draft: dict) -> str:
    headline = _sanitize_html_text(draft.get("headline") or news.title)
    bullets = draft.get("summary_bullets") or draft.get("bullets") or []
    meaning = _sanitize_html_text(draft.get("meaning") or "")
    tags = _as_hashtags(draft.get("tags") or [])

    parts = [f"🧠 <b>{headline}</b>"]

    if bullets:
        lines = []
        for b in bullets[:5]:
            b = _sanitize_html_text(str(b).strip())
            if b:
                lines.append(f"• {b}")
        if lines:
            parts.append("\n".join(lines))

    if meaning:
        parts.append(f"\n<i>Что это значит:</i> {meaning}")

    if tags:
        parts.append(f"\n{tags}")

    if news.url:
        parts.append(f'\n<a href="{news.url}">Source</a>')

    return "\n\n".join([p for p in parts if p])


class Publisher:
    def __init__(self, client: TelegramClient):
        self.client = client

    # ---------- selection logic ----------

    async def _get_next_candidate_for_review(self, db, source_filter: str = None) -> Optional[News]:
        """
        Берём следующую новость для ревью с опциональным фильтром по источнику.
        source_filter: None (all), 'github_only', 'exclude_github'
        """
        pub = aliased(Publication)

        stmt = (
            select(News)
            .where(News.is_published == False)  # noqa: E712
            .outerjoin(pub, pub.news_id == News.id)
            .where(pub.id.is_(None))
        )

        # Фильтр по источнику
        if source_filter == "github_only":
            stmt = stmt.where(News.title.ilike("%GitHub: %"))
        elif source_filter == "exclude_github":
            stmt = stmt.where(News.title.notilike("%GitHub: %"))

        stmt = stmt.order_by(News.created_at.asc()).limit(1)
        res = await db.execute(stmt)
        return res.scalars().first()

    async def _mark_in_review(self, db, news_id: int, status: str = PUB_REVIEW_RAW) -> None:
        db.add(Publication(news_id=news_id, status=status))
        await db.commit()

    async def _update_publication_status(self, db, news_id: int, status: str) -> None:
        stmt = (
            update(Publication)
            .where(Publication.news_id == news_id)
            .values(status=status)
        )
        await db.execute(stmt)
        await db.commit()

    # ---------- AI Draft methods ----------

    async def generate_ai_draft(
        self,
        news_id: int,
        admin_message_id: Optional[int] = None,
        addon_prompt: Optional[str] = None,
        lang: str = "ru",
    ) -> None:
        """Генерация AI драфта для новости

        Args:
            news_id: ID новости
            admin_message_id: ID сообщения в админ-чате (для обновления)
            addon_prompt: Дополнительная инструкция для AI
            lang: Язык генерации (ru или en)
        """
        from app.ai_editor import AIEditor

        async for db in get_session():
            # Получить новость с source
            stmt = (
                select(News)
                .where(News.id == news_id)
                .limit(1)
            )
            res = await db.execute(stmt)
            news = res.scalars().first()

            if not news:
                await self.client.send_message(
                    settings.telegram_admin_chat_id,
                    f"❌ Новость {news_id} не найдена."
                )
                return

            # Получаем source
            source_stmt = select(Source).where(Source.id == news.source_id).limit(1)
            source_res = await db.execute(source_stmt)
            source = source_res.scalars().first()
            source_name = source.name if source else "Unknown"

            # Генерация драфта
            editor = AIEditor()
            try:
                draft = await editor.create_draft(
                    title=news.title,
                    content=news.content or "",
                    url=news.url,
                    source=source_name,
                    lang=lang,
                    addon_prompt=addon_prompt,
                )
            finally:
                await editor.close()

            # Сохранить/обновить драфт в Publication
            pub_stmt = select(Publication).where(Publication.news_id == news_id).limit(1)
            pub_res = await db.execute(pub_stmt)
            pub = pub_res.scalars().first()

            if not pub:
                pub = Publication(news_id=news_id)
                db.add(pub)

            pub.draft_text = draft.get("final_post_html", "")
            pub.draft_json = json.dumps(draft, ensure_ascii=False)
            pub.ai_model = settings.openrouter_model_ru
            pub.status = PUB_AI_DRAFT_READY
            pub.draft_created_at = _now_utc()
            pub.draft_updated_at = _now_utc()

            if addon_prompt:
                pub.last_prompt_addon = addon_prompt

            await db.commit()

            # Отправить драфт админу
            await self._send_ai_draft_card(news, draft)

            # Обновить предыдущее сообщение
            if admin_message_id:
                try:
                    await self.client.edit_message(
                        settings.telegram_admin_chat_id,
                        admin_message_id,
                        "✨ AI Draft готов!",
                        buttons=None,
                    )
                except Exception:
                    pass

    async def _send_ai_draft_card(self, news: News, draft: dict) -> None:
        """Отправить AI драфт на модерацию"""

        headline = draft.get("headline", news.title)
        bullets = draft.get("summary_bullets", [])
        meaning = draft.get("meaning", "")
        tags = draft.get("tags", [])
        final_html = draft.get("final_post_html", "")

        # Формирование сообщения
        msg = f"✨ <b>AI Draft</b> (ID: {news.id})\n\n"

        # Показываем headline отдельно
        msg += f"<b>{_sanitize_html_text(headline)}</b>\n\n"

        if bullets:
            msg += "<b>Ключевые факты:</b>\n"
            for b in bullets[:5]:
                msg += f"• {_sanitize_html_text(str(b))}\n"
            msg += "\n"

        if meaning:
            msg += f"<b>Что это значит:</b>\n{_sanitize_html_text(meaning)}\n\n"

        if tags:
            msg += f"<b>Теги:</b> {_sanitize_html_text(_as_hashtags(tags))}\n\n"

        msg += f"<a href=\"{news.url}\">🔗 Source</a>"

        # Кнопки
        buttons = [
            [
                Button.inline("✅ Publish", data=f"publish:{news.id}".encode()),
                Button.inline("✏️ Edit", data=f"edit:{news.id}".encode()),
            ],
            [
                Button.inline("🔁 Regenerate", data=f"regen:{news.id}".encode()),
                Button.inline("❌ Reject", data=f"reject:{news.id}".encode()),
            ],
            [
                Button.url("🔗 Source", url=news.url),
            ],
        ]

        await self.client.send_message(
            settings.telegram_admin_chat_id,
            msg,
            buttons=buttons,
            parse_mode="html",
            link_preview=False,
        )

    async def regenerate_draft(
        self,
        news_id: int,
        addon_prompt: str,
    ) -> None:
        """Перегенерация драфта с доп. инструкцией"""
        await self.generate_ai_draft(news_id, addon_prompt=addon_prompt)

    async def edit_draft(self, news_id: int, new_text: str) -> None:
        """Ручное редактирование драфта"""
        async for db in get_session():
            pub_stmt = select(Publication).where(Publication.news_id == news_id).limit(1)
            pub_res = await db.execute(pub_stmt)
            pub = pub_res.scalars().first()

            if not pub:
                await self.client.send_message(
                    settings.telegram_admin_chat_id,
                    f"❌ Нет драфта для новости {news_id}"
                )
                return

            # Обновляем драфт
            pub.draft_text = new_text
            pub.draft_updated_at = _now_utc()

            # Парсим draft_json если нужно для обновления
            if pub.draft_json:
                try:
                    draft_data = json.loads(pub.draft_json)
                    draft_data["final_post_html"] = new_text
                    pub.draft_json = json.dumps(draft_data, ensure_ascii=False)
                except Exception:
                    pass

            await db.commit()

            await self.client.send_message(
                settings.telegram_admin_chat_id,
                f"✅ Драфт обновлён для новости {news_id}"
            )

            # Отправить обновлённую карточку
            news_stmt = select(News).where(News.id == news_id).limit(1)
            news_res = await db.execute(news_stmt)
            news = news_res.scalars().first()

            if news and pub.draft_json:
                draft = json.loads(pub.draft_json)
                await self._send_ai_draft_card(news, draft)

    # ---------- formatting ----------

    def _build_review_message(self, news: News) -> str:
        title = _sanitize_html_text(news.title)
        content = _sanitize_html_text(news.content or "")
        url = news.url

        # Сильно длинные тексты в админку не нужны
        content = _truncate(content, 1500)

        msg = (
            f"📝 <b>Черновик новости</b>\n"
            f"<b>ID:</b> {news.id}\n\n"
            f"<b>{title}</b>\n\n"
            f"{content}\n\n"
            f"<a href=\"{url}\">Source</a>"
        )
        return msg

    def _build_channel_post(self, news: News) -> str:
        title = _sanitize_html_text(news.title)
        content = _sanitize_html_text(news.content or "")
        url = news.url

        # для канала лучше короче
        content = _truncate(content, 1800)

        return (
            f"🧠 <b>{title}</b>\n\n"
            f"{content}\n\n"
            f"<a href=\"{url}\">Original Article</a>"
        )

    def _review_buttons(self, news_id: int):
        return [
            [
                Button.inline("✅ Publish", data=f"publish:{news_id}".encode()),
                Button.inline("❌ Reject", data=f"reject:{news_id}".encode()),
            ],
            [
                Button.inline("⏰ Postpone", data=f"postpone:{news_id}".encode()),
                Button.url("🔗 Source", url="https://example.com"),  # заменим ниже
            ],
        ]

    # ---------- public API ----------

    async def send_next_for_review(self, limit: Optional[int] = None, source_filter: str = None) -> None:
        """
        Отправляет сырую новость на модерацию в админ-чат.
        source_filter: None (all), 'github_only', 'exclude_github'
        """
        async for db in get_session():
            news = await self._get_next_candidate_for_review(db, source_filter=source_filter)
            if not news:
                label = "GitHub " if source_filter == "github_only" else ""
                await self.client.send_message(
                    settings.telegram_admin_chat_id,
                    f"Нет {label}новостей на модерацию."
                )
                return

            text = self._build_review_message(news)

            buttons = [
                [
                    Button.inline("✨ Make Draft (AI)", data=f"ai:{news.id}".encode()),
                    Button.inline("➡️ Next", data=b"next_raw"),
                ],
                [
                    Button.inline("❌ Reject", data=f"reject:{news.id}".encode()),
                    Button.inline("⏰ Postpone", data=f"postpone:{news.id}".encode()),
                ],
                [
                    Button.url("🔗 Source", url=news.url),
                ],
            ]

            # Отмечаем, что новость ушла в review
            await self._mark_in_review(db, news.id, status=PUB_REVIEW_RAW)

            await self.client.send_message(
                settings.telegram_admin_chat_id,
                text,
                buttons=buttons,
                parse_mode="html",
                link_preview=False,
            )
            return

    async def publish_news_id(self, news_id: int, admin_message_id: Optional[int] = None) -> None:
        """
        Публикует новость в канал:
        - ставит News.is_published = True
        - Publication.status = published
        - использует AI draft если есть, иначе сырой контент
        - уведомляет админа
        """
        async for db in get_session():
            res = await db.execute(select(News).where(News.id == news_id).limit(1))
            news = res.scalars().first()
            if not news:
                await self.client.send_message(settings.telegram_admin_chat_id, f"❌ Новость {news_id} не найдена.")
                return

            if news.is_published:
                await self.client.send_message(settings.telegram_admin_chat_id, f"⚠️ Новость {news_id} уже опубликована.")
                return

            # Проверяем есть ли AI draft
            pub_res = await db.execute(select(Publication).where(Publication.news_id == news_id).limit(1))
            pub = pub_res.scalars().first()

            # 1) Если есть draft_json — рендерим стабильный красивый пост из JSON
            draft_data = None
            if pub and pub.draft_json:
                try:
                    draft_data = json.loads(pub.draft_json)
                except Exception:
                    draft_data = None

            if draft_data:
                post_text = _render_channel_post_from_draft(news, draft_data)
                logger.info(f"Publishing with AI draft JSON for news {news_id}")
            else:
                # Fallback: если есть draft_text — используем его, иначе сырой
                if pub and pub.draft_text:
                    post_text = pub.draft_text
                    logger.info(f"Publishing with AI draft TEXT for news {news_id}")
                else:
                    post_text = self._build_channel_post(news)
                    logger.info(f"Publishing with raw content for news {news_id}")

            # 2) Публикуем: если есть image_url — отправляем как FILE с caption
            if news.image_url:
                msg = await self.client.send_file(
                    settings.telegram_channel_id,
                    file=news.image_url,
                    caption=post_text,
                    parse_mode="html",
                )
            else:
                msg = await self.client.send_message(
                    settings.telegram_channel_id,
                    post_text,
                    parse_mode="html",
                    link_preview=False,
                )

            await db.execute(
                update(News).where(News.id == news_id).values(is_published=True)
            )
            await db.commit()

            # Обновляем статус публикации
            if not pub:
                pub = Publication(news_id=news_id)
                db.add(pub)

            pub.telegram_message_id = msg.id
            pub.status = PUB_PUBLISHED
            await db.commit()

            await self.client.send_message(
                settings.telegram_admin_chat_id,
                f"✅ Опубликовано: {news.title[:50]}...\nChannel msg_id={msg.id}",
            )

            if admin_message_id:
                try:
                    await self.client.edit_message(
                        settings.telegram_admin_chat_id,
                        admin_message_id,
                        "✅ Уже опубликовано.",
                        buttons=None,
                        parse_mode="html",
                    )
                except Exception:
                    pass

    async def reject_news_id(self, news_id: int, admin_message_id: Optional[int] = None) -> None:
        async for db in get_session():
            # если нет publication — создадим, чтобы не возвращалась снова
            pub_res = await db.execute(select(Publication).where(Publication.news_id == news_id).limit(1))
            pub = pub_res.scalars().first()
            if not pub:
                db.add(Publication(news_id=news_id, status=PUB_REJECTED))
                await db.commit()
            else:
                await self._update_publication_status(db, news_id, PUB_REJECTED)

        if admin_message_id:
            await self.client.edit_message(
                settings.telegram_admin_chat_id,
                admin_message_id,
                f"❌ Отклонено. ID={news_id}",
                buttons=None,
                parse_mode="html",
            )

    async def postpone_news_id(self, news_id: int, admin_message_id: Optional[int] = None) -> None:
        async for db in get_session():
            pub_res = await db.execute(select(Publication).where(Publication.news_id == news_id).limit(1))
            pub = pub_res.scalars().first()
            if not pub:
                db.add(Publication(news_id=news_id, status=PUB_POSTPONED))
                await db.commit()
            else:
                await self._update_publication_status(db, news_id, PUB_POSTPONED)

        if admin_message_id:
            await self.client.edit_message(
                settings.telegram_admin_chat_id,
                admin_message_id,
                f"⏰ Отложено. ID={news_id}",
                buttons=None,
                parse_mode="html",
            )

    # optional: later
    async def unpostpone_all(self) -> None:
        """
        Хук на будущее: можно раз в день возвращать postponed в review.
        Сейчас не используется.
        """
        async for db in get_session():
            await db.execute(
                update(Publication)
                .where(Publication.status == PUB_POSTPONED)
                .values(status=PUB_REVIEW)
            )
            await db.commit()
            return
