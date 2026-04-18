import asyncio
from telethon import TelegramClient, events
from app.config import settings
from app.publisher.publisher import Publisher
from app.analytics.analytics import AnalyticsTracker
from app.utils.logger import setup_logger
logger = setup_logger(__name__)


class NewsBot:
    def __init__(self):
        self.client = TelegramClient(
            "bot_session",
            api_id=settings.api_id,
            api_hash=settings.api_hash,
        )

        # Сигнал готовности (важно для main.py)
        self.ready = asyncio.Event()

        self.publisher = Publisher(self.client)
        self.analytics = AnalyticsTracker()

        # State management для edit/regen режимов
        # {user_id: {"mode": "edit"|"regen", "news_id": 123}}
        self._user_states: dict[int, dict] = {}

        # Языковые предпочтения пользователей
        # {user_id: "ru" | "en"}
        self._user_languages: dict[int, str] = {}

        self.setup_handlers()

    def setup_handlers(self):
        @self.client.on(events.NewMessage(pattern=r"^/start$"))
        async def start_handler(event: events.NewMessage.Event):
            current_lang = self._get_user_language(event.sender_id)
            await event.respond(
                "🤖 AI News Hub\n\n"
                "Команды:\n"
                "/review — показать новость на модерацию\n"
                "/review N — показать N новостей\n"
                "/stats 7 — статистика за 7 дней\n"
                "/pending — сколько на модерации\n"
                "/lang ru — русский\n"
                "/lang en — английский\n"
                f"\nТекущий язык: {current_lang.upper()}"
            )

        @self.client.on(events.NewMessage(pattern=r"^/lang\s+(ru|en)$"))
        async def lang_handler(event: events.NewMessage.Event):
            """Установка языка для AI генерации"""
            lang = event.pattern_match.group(1)
            user_id = event.sender_id
            self._user_languages[user_id] = lang
            await event.respond(f"✅ Язык изменён на {lang.upper()}")

        @self.client.on(events.NewMessage(pattern=r"^/review(\s+(\d+))?$"))
        async def review_handler(event: events.NewMessage.Event):
            # Ограничиваем до админ-чата
            if str(event.chat_id) != str(settings.telegram_admin_chat_id):
                await event.respond("⛔ Команда доступна только в админ-чате.")
                return

            # Парсим количество (пока не используется для batch)
            limit = None
            if event.pattern_match.group(2):
                limit = int(event.pattern_match.group(2))

            await self.publisher.send_next_for_review(limit=limit)

        @self.client.on(events.CallbackQuery())
        async def callback_handler(event: events.CallbackQuery.Event):
            data = event.data.decode("utf-8")

            # Обработка без news_id
            if data == "next_raw":
                await self.publisher.send_next_for_review()
                await event.answer("Следующая")
                return

            # Парсим action:news_id
            try:
                action, news_id_str = data.split(":", 1)
                news_id = int(news_id_str)
            except Exception:
                await event.answer("Некорректные данные кнопки", alert=True)
                return

            # AI Actions
            if action == "ai":
                await event.answer("Генерирую AI draft...")
                try:
                    lang = self._get_user_language(event.sender_id)
                    await self.publisher.generate_ai_draft(news_id, event.message_id, lang=lang)
                except Exception as e:
                    logger.exception("AI draft generation failed: %s", e)
                    await event.answer("Ошибка генерации", alert=True)
                return

            if action == "regen":
                # Запрашиваем доп. инструкцию
                user_id = event.sender_id
                self._user_states[user_id] = {"mode": "regen", "news_id": news_id}
                await event.answer(
                    "Пришли инструкцию для перегенерации (1 сообщение).\n"
                    "Например: сделай короче, добавь 2 bullets, стиль более нейтральный"
                )
                return

            if action == "edit":
                # Режим редактирования
                user_id = event.sender_id
                self._user_states[user_id] = {"mode": "edit", "news_id": news_id}
                await event.answer(
                    "Пришли новый текст драфта (1 сообщение).\n"
                    "/cancel чтобы отменить."
                )
                return

            # Стандартные действия
            actions = {
                "publish": self.publisher.publish_news_id,
                "reject": self.publisher.reject_news_id,
                "postpone": self.publisher.postpone_news_id,
            }

            fn = actions.get(action)
            if not fn:
                await event.answer("Неизвестное действие", alert=True)
                return

            try:
                await fn(news_id=news_id, admin_message_id=event.message_id)
                await event.answer("Готово")
            except Exception as e:
                logger.exception("Callback error: %s", e)
                await event.answer("Ошибка выполнения", alert=True)

        @self.client.on(events.NewMessage(pattern=r"^/cancel$"))
        async def cancel_handler(event: events.NewMessage.Event):
            """Отмена режима редактирования/регенерации"""
            user_id = event.sender_id
            if user_id in self._user_states:
                del self._user_states[user_id]
                await event.respond("✅ Операция отменена")
            else:
                await event.respond("Нет активной операции")

        @self.client.on(events.NewMessage(pattern=r"^/stats(\s+(\d+))?$"))
        async def stats_handler(event: events.NewMessage.Event):
            """Показать статистику"""
            if str(event.chat_id) != str(settings.telegram_admin_chat_id):
                return
            days = int(event.pattern_match.group(2) or 7)
            msg = await self.analytics.format_stats_message(days)
            await event.respond(msg, parse_mode="html")

        @self.client.on(events.NewMessage(pattern=r"^/pending$"))
        async def pending_handler(event: events.NewMessage.Event):
            """Показать сколько новостей ждёт модерации"""
            if str(event.chat_id) != str(settings.telegram_admin_chat_id):
                return
            stats = await self.analytics.get_stats(days=30)
            await event.respond(
                f"⏳ На модерации: <b>{stats['pending_review']}</b> новостей",
                parse_mode="html"
            )

        @self.client.on(events.NewMessage(pattern=r"^/parse$"))
        async def parse_handler(event: events.NewMessage.Event):
            """Запустить парсинг всех источников вручную"""
            if str(event.chat_id) != str(settings.telegram_admin_chat_id):
                return
            await event.respond("🔄 Запускаю парсинг...")
            try:
                from app.main import parse_all_sources
                await parse_all_sources()
                await event.respond("✅ Парсинг завершён")
            except Exception as e:
                await event.respond(f"❌ Ошибка: {e}")

        @self.client.on(events.NewMessage(pattern=r"^/github$"))
        async def github_handler(event: events.NewMessage.Event):
            """Запустить парсинг GitHub вручную"""
            if str(event.chat_id) != str(settings.telegram_admin_chat_id):
                return
            await event.respond("🔧 Ищу trending GitHub репозитории...")
            try:
                from app.database import AsyncSessionLocal
                from app.models.base import Source
                from app.parsers.github_trending_parser import GitHubTrendingParser
                from sqlalchemy import select

                async with AsyncSessionLocal() as s:
                    res = await s.execute(
                        select(Source).where(Source.name == "GitHub Trending")
                    )
                    src = res.scalars().first()

                if not src:
                    await event.respond("❌ Источник GitHub Trending не найден в БД")
                    return

                parser = GitHubTrendingParser(src)
                articles = await parser.parse(max_repos=5)
                await parser.close()

                if not articles:
                    await event.respond("📭 Нет новых репозиториев")
                    return

                for a in articles:
                    await event.respond(
                        f"🔧 <b>{a['title']}</b>\n\n{a['content'][:500]}\n\n🔗 {a['url']}",
                        parse_mode="html"
                    )
                await event.respond(f"✅ Найдено {len(articles)} репозиториев")
            except Exception as e:
                import traceback
                await event.respond(f"❌ Ошибка: {e}\n{traceback.format_exc()[-500:]}")

        @self.client.on(events.NewMessage())
        async def text_handler(event: events.NewMessage.Event):
            """Обработка текстовых сообщений для edit/regen режимов"""
            # Только от админа
            if str(event.chat_id) != str(settings.telegram_admin_chat_id):
                return

            # Пропускаем команды
            if event.message.text.startswith("/"):
                return

            user_id = event.sender_id
            state = self._user_states.get(user_id)

            if not state:
                return

            news_id = state["news_id"]
            mode = state["mode"]

            try:
                if mode == "edit":
                    # Ручное редактирование драфта
                    await self.publisher.edit_draft(news_id, event.message.text)
                    del self._user_states[user_id]

                elif mode == "regen":
                    # Перегенерация с доп. инструкцией
                    await event.respond("🔄 Перегенерирую...")
                    await self.publisher.regenerate_draft(news_id, event.message.text)
                    del self._user_states[user_id]

            except Exception as e:
                logger.exception("State handler error: %s", e)
                await event.respond(f"❌ Ошибка: {e}")
                del self._user_states[user_id]

    def _get_user_language(self, user_id: int) -> str:
        """Получить язык пользователя или дефолтный"""
        return self._user_languages.get(user_id, settings.ai_default_language)

    async def run(self):
        """
        Запуск бота. Важно: выставляем ready после успешного start().
        """
        logger.info("Starting Telegram bot...")

        try:
            await self.client.start(bot_token=settings.telegram_bot_token)
            self.ready.set()
            logger.info("Bot started (READY).")

            # Пинг в админ-чат для проверки, что chat_id и права верные
            try:
                await self.client.send_message(
                    settings.telegram_admin_chat_id,
                    "✅ Bot started and ready.",
                )
            except Exception:
                logger.exception("Failed to send ping to admin chat. Check chat_id and bot permissions.")

            await self.client.run_until_disconnected()

        except Exception:
            logger.exception("Bot failed to start")
            raise

    async def stop(self):
        try:
            await self.client.disconnect()
        except Exception:
            pass
