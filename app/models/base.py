from sqlalchemy import String, Integer, Boolean, ForeignKey, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from app.database import Base

class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(500))
    priority: Mapped[int] = mapped_column(default=1)
    last_parsed: Mapped[datetime] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)

class News(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(500), unique=True)
    image_url: Mapped[str] = mapped_column(String(500), nullable=True)
    publish_date: Mapped[datetime] = mapped_column(nullable=True)
    is_published: Mapped[bool] = mapped_column(default=False)
    is_breaking: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news.id"))
    telegram_message_id: Mapped[int] = mapped_column(nullable=True)
    published_at: Mapped[datetime] = mapped_column(server_default=func.now())
    status: Mapped[str] = mapped_column(default="pending")

    # AI Draft хранилище
    draft_text: Mapped[str] = mapped_column(Text, nullable=True)
    draft_json: Mapped[str] = mapped_column(Text, nullable=True)  # для structured output

    # AI метаданные
    ai_model: Mapped[str] = mapped_column(String(100), nullable=True)
    ai_version: Mapped[int] = mapped_column(Integer, nullable=True)
    last_prompt_addon: Mapped[str] = mapped_column(Text, nullable=True)

    # Таймстампы драфта
    draft_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    draft_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

class Analytics(Base):
    __tablename__ = "analytics"

    id: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news.id"))
    views: Mapped[int] = mapped_column(default=0)
    reactions: Mapped[int] = mapped_column(default=0)
    comments: Mapped[int] = mapped_column(default=0)
    reposts: Mapped[int] = mapped_column(default=0)
    click_rate: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

class PromptConfig(Base):
    """Хранилище промптов для AI Editor"""
    __tablename__ = "prompt_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)  # editor_ru, editor_en, extractor
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
