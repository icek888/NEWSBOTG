import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import settings
from app.utils.logger import setup_logger
from app.database import engine, Base, AsyncSessionLocal
from app.models.base import Source, News # Убедись, что импорты моделей верны
from app.telegram.bot import NewsBot
from app.parsers.techcrunch_parser import TechCrunchParser
from app.parsers.theverge_parser import TheVergeParser

# Настройка логирования, чтобы видеть ВСЁ
logging.basicConfig(level=logging.INFO)
logger = setup_logger(__name__)

# Инициализируем планировщик и бота
scheduler = AsyncIOScheduler()
telegram_bot = NewsBot()


async def init_db_data():
    """Наполнение базы начальными данными, если она пуста"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Source))
        if not result.scalars().first():
            logger.info("🌱 База пуста. Добавляю стандартные источники...")
            sources = [
                Source(name="TechCrunch", url="https://techcrunch.com/category/artificial-intelligence/"),
                Source(name="The Verge", url="https://www.theverge.com/ai-artificial-intelligence")
            ]
            session.add_all(sources)
            await session.commit()
            logger.info("✅ Источники добавлены.")


async def parse_all_sources():
    logger.info("🚀 Начинаю цикл парсинга источников...")

    async with AsyncSessionLocal() as session:
        stmt = select(Source).where(Source.is_active == True)
        result = await session.execute(stmt)
        sources = result.scalars().all()

    if not sources:
        logger.warning("⚠️ Нет активных источников для парсинга.")
        return

    total_new = 0

    for source in sources:
        parser = None
        try:
            if "TechCrunch" in source.name:
                parser = TechCrunchParser(source)
            elif "The Verge" in source.name:
                parser = TheVergeParser(source)

            if not parser:
                logger.error(f"❌ Нет реализации парсера для источника: {source.name}")
                continue

            articles = await parser.parse()
            logger.info(f"📡 {source.name}: Найдено {len(articles)} статей.")

            # Сохраняем и считаем только реально новые
            for article in articles:
                created = await parser.save_article(article)  # <-- см. пункт 2 ниже
                if created:
                    total_new += 1

        except Exception as e:
            logger.error(f"❌ Ошибка при работе парсера {source.name}: {e}", exc_info=True)

        finally:
            # если ты добавишь BaseParser.close() (как я предлагал), это важно
            if parser and hasattr(parser, "close"):
                try:
                    await parser.close()
                except Exception:
                    pass

    logger.info(f"✅ Парсинг завершен. Новых статей: {total_new}")

    # Авто-показ в админке: если есть новые статьи — кинем 1 черновик
    if total_new > 0:
        try:
            # метод должен жить в Publisher: send_next_for_review()
            await telegram_bot.publisher.send_next_for_review()
        except Exception as e:
            logger.error(f"❌ Не удалось отправить черновик в админ-чат: {e}", exc_info=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    logger.info("🛠 Инициализация приложения...")
    
    try:
        # 1. Создаем таблицы, если их нет
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # 2. Наполняем базу начальными данными
        await init_db_data()

        # 3. Запуск Telegram бота
        # Используем create_task, чтобы не блокировать основной поток
        asyncio.create_task(telegram_bot.run())
        logger.info("🤖 Telegram Bot запущен.")

        # 4. Настройка планировщика
        scheduler.add_job(
            parse_all_sources,
            'interval',
            seconds=settings.parsing_interval,
            id="parsing_job"
        )
        scheduler.start()
        logger.info(f"📅 Планировщик запущен (интервал: {settings.parsing_interval} сек).")

        # 5. Первый запуск парсинга сразу после старта
        asyncio.create_task(parse_all_sources())

    except Exception as e:
        logger.critical(f"💥 Критическая ошибка при старте: {e}", exc_info=True)
        sys.exit(1)

    yield
    
    # --- SHUTDOWN ---
    logger.info("🛑 Остановка приложения...")
    scheduler.shutdown()

app = FastAPI(title="AI News Hub API", lifespan=lifespan)

@app.get("/")
async def read_root():
    return {
        "status": "working", 
        "jobs": [str(j) for j in scheduler.get_jobs()]
    }

if __name__ == "__main__":
    # Явный запуск через uvicorn внутри скрипта
    uvicorn.run(app, host="0.0.0.0", port=8000)