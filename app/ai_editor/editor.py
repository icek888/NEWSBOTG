import json
from typing import Optional
import httpx

from app.config import settings
from .prompts import PromptManager

from app.utils.logger import setup_logger
logger = setup_logger(__name__)


class AIEditor:
    """AI Editor на базе OpenRouter API"""

    def __init__(self):
        self.prompt_manager = PromptManager()
        self.client = httpx.AsyncClient(timeout=settings.ai_timeout)

    async def close(self):
        """Закрыть HTTP клиент"""
        await self.client.aclose()

    async def _call_openrouter(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> str:
        """Вызов OpenRouter API"""

        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY не настроен в .env")

        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/karle/NewsAutoTG",
        }

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": settings.ai_temperature,
            "max_tokens": settings.ai_max_tokens,
        }

        # Для моделей, поддерживающих JSON response format
        # Если модель не поддерживает, AI всё равно должен вернуть JSON
        try:
            payload["response_format"] = {"type": "json_object"}
        except Exception:
            pass  # Некоторые модели не поддерживают этот параметр

        logger.info(f"Calling OpenRouter with model: {model}")

        response = await self.client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
        )

        if response.status_code != 200:
            logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
            response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def create_draft(
        self,
        title: str,
        content: str,
        url: str,
        source: str,
        lang: str = "ru",
        addon_prompt: Optional[str] = None,
    ) -> dict:
        """Создать AI draft из сырой новости

        Returns:
            dict с ключами: headline, summary_bullets, meaning, tags, final_post_html
        """

        prompt_key = f"editor_{lang}"
        system_prompt = await self.prompt_manager.get_prompt(prompt_key)

        if not system_prompt:
            raise ValueError(f"Промпт не найден для ключа: {prompt_key}")

        # Формируем user prompt
        user_prompt = f"""News to process:

Title: {title}

Content: {content if content else "No content available"}

URL: {url}

Source: {source}
"""

        if addon_prompt:
            user_prompt += f"\n\nAdditional instructions: {addon_prompt}"

        model = (
            settings.openrouter_model_ru
            if lang == "ru"
            else settings.openrouter_model_en
        )

        try:
            result_text = await self._call_openrouter(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
            )

            # Парсим JSON ответ
            result = json.loads(result_text)

            # Валидация обязательных полей
            required_fields = ["headline", "summary_bullets", "meaning", "tags", "final_post_html"]
            for field in required_fields:
                if field not in result:
                    logger.warning(f"Missing field in AI response: {field}")
                    # Заполняем дефолтными значениями
                    if field == "headline":
                        result[field] = title
                    elif field == "summary_bullets":
                        result[field] = [content[:200]] if content else ["No content"]
                    elif field == "meaning":
                        result[field] = "AI explanation not available"
                    elif field == "tags":
                        result[field] = ["ai", "news"]
                    elif field == "final_post_html":
                        result[field] = f"<b>{title}</b>\n\n{content[:500]}" if content else f"<b>{title}</b>"

            logger.info(f"AI draft created for {url}")
            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"OpenRouter API HTTP error: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from AI: {e}")
            logger.error(f"Response text: {result_text[:500]}")
            raise
        except Exception as e:
            logger.exception(f"AI draft creation failed: {e}")
            raise
