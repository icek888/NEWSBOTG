from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # Указываем валидацию. Если в .env пусто — будет ошибка при старте.
    api_id: int
    api_hash: str

    # Pydantic автоматически сопоставит TELEGRAM_BOT_TOKEN из .env с этим полем
    telegram_bot_token: str
    telegram_channel_id: int
    telegram_admin_chat_id: int

    database_url: str = "sqlite+aiosqlite:///./ai_news.db"

    # Источники
    techcrunch_url: str = "https://techcrunch.com"
    theverge_url: str = "https://www.theverge.com"
    hiai_url: str = "https://t.me/hiaimedia"
    points_url: str = "https://t.me/points_ii"

    # Интервалы
    parsing_interval: int = 3600
    publication_interval: int = 1800

    # OpenRouter API
    openrouter_api_key: str = ""
    openrouter_model_ru: str = "anthropic/claude-3-haiku"
    openrouter_model_en: str = "anthropic/claude-3-haiku"
    ai_temperature: float = 0.7
    ai_max_tokens: int = 2000
    ai_timeout: int = 30
    ai_default_language: str = "ru"  # ru | en

    # Review настройки
    review_batch_size: int = 1  # сколько новостей показывать за раз

    # Фильтры парсинга
    parser_max_articles: int = 20
    parser_min_age_hours: int = 0  # 0 = отключено
    parser_max_age_hours: int = 168  # 7 дней
    parser_require_image: bool = False
    parser_block_keywords: str = ""  # через запятую

    # Фильтры публикации
    publish_daily_limit: int = 10
    publish_require_ai_draft: bool = True

    # Логирование
    log_level: str = "INFO"
    debug: bool = False

    # Если файл называется не .env, а например .env.local, укажи это здесь
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

try:
    settings = Settings()
    print("✅ Конфигурация успешно загружена")
except Exception as e:
    print(f"❌ Ошибка валидации конфига: {e}")
    # Это выведет, какого именно поля не хватает или где не совпал тип
    exit(1)