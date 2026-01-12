from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

# Создаем engine - SQLAlchemy сам определит тип БД по URL
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,  # Логируем SQL в режиме разработки
    future=True
)

# Создаем фабрику сессий
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    """Базовый класс для всех моделей"""
    pass


async def get_session() -> AsyncSession:
    """Асинхронный генератор для получения сессии"""
    async with AsyncSessionLocal() as session:
        yield session
