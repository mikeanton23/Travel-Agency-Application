# -*- coding: utf-8 -*-

"""
LLM orchestration: selectable provider, streaming, and conversation
memory persisted to the Phase 1 ``ai_conversations`` / ``ai_messages``
tables.

Keys resolve through the encrypted key manager when available, falling
back to environment settings.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Type

from app.services.llm.base import Completion, LLMError, LLMProvider, Message
from app.services.llm.providers import (
    AnthropicProvider, GeminiProvider, OllamaProvider, OpenAIProvider,
)
from app.utils import config

logger = logging.getLogger(__name__)

PROVIDERS: Dict[str, Type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-6",
    "gemini": config.GEMINI_MODEL,
    "ollama": config.OLLAMA_MODEL,
}

ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


class LLMService:
    def __init__(
        self,
        session_factory: Optional[Callable[[], Any]] = None,
        key_resolver: Optional[Callable[[str], Optional[str]]] = None,
        provider_overrides: Optional[Dict[str, LLMProvider]] = None,
    ) -> None:
        self._session_factory = session_factory
        self._key_resolver = key_resolver
        self._overrides = provider_overrides or {}

    # ------------------------------------------------------------------
    # Provider resolution
    # ------------------------------------------------------------------

    def _resolve_key(self, provider: str) -> str:
        if provider == "ollama":
            return ""
        if self._key_resolver is not None:
            value = self._key_resolver(provider)
            if value:
                return value
        else:
            try:
                from app.services.key_manager import KeyManager
                value = KeyManager().get_key(provider)
                if value:
                    return value
            except Exception as exc:
                logger.debug("Key manager unavailable (%s); using env", exc)
        return getattr(config, ENV_KEYS.get(provider, ""), "")

    def get_provider(self, provider: str) -> LLMProvider:
        provider = provider.strip().lower()
        if provider in self._overrides:
            return self._overrides[provider]
        cls = PROVIDERS.get(provider)
        if cls is None:
            raise LLMError(
                f"Unknown provider '{provider}'. "
                f"Available: {', '.join(sorted(PROVIDERS))}"
            )
        key = self._resolve_key(provider)
        if provider == "ollama":
            return cls(base_url=config.OLLAMA_HOST)
        if not key:
            raise LLMError(
                f"No API key configured for '{provider}' — add one in "
                f"Settings or .env."
            )
        return cls(api_key=key)

    def available_providers(self) -> List[str]:
        out = ["ollama"]  # local, keyless
        for name in ("openai", "anthropic", "gemini"):
            if self._resolve_key(name):
                out.append(name)
        return sorted(out)

    # ------------------------------------------------------------------
    # Chat (with optional persistent memory)
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: List[Message],
        provider: str,
        model: Optional[str] = None,
        conversation_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Completion:
        model = model or DEFAULT_MODELS.get(provider, "")
        history = self._load_history(conversation_id)
        completion = await self.get_provider(provider).complete(
            model, history + messages
        )
        self._persist(conversation_id, user_id, provider, model,
                      messages, completion.text,
                      completion.output_tokens)
        return completion

    async def chat_stream(
        self,
        messages: List[Message],
        provider: str,
        model: Optional[str] = None,
        conversation_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Stream text deltas; persists the full exchange at the end."""
        model = model or DEFAULT_MODELS.get(provider, "")
        history = self._load_history(conversation_id)
        collected: List[str] = []
        async for delta in self.get_provider(provider).stream(
            model, history + messages
        ):
            collected.append(delta)
            yield delta
        self._persist(conversation_id, user_id, provider, model,
                      messages, "".join(collected), None)

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def start_conversation(
        self, provider: str, model: Optional[str] = None,
        title: Optional[str] = None, user_id: Optional[int] = None,
    ) -> Optional[int]:
        if self._session_factory is None:
            return None
        from app.db.models import AiConversation

        session = self._session_factory()
        try:
            conv = AiConversation(
                provider=provider,
                model=model or DEFAULT_MODELS.get(provider),
                title=title, user_id=user_id,
            )
            session.add(conv)
            session.commit()
            return conv.id
        finally:
            session.close()

    def _load_history(self, conversation_id: Optional[int]) -> List[Message]:
        if conversation_id is None or self._session_factory is None:
            return []
        from app.db.models import AiMessage

        session = self._session_factory()
        try:
            rows = (
                session.query(AiMessage)
                .filter(AiMessage.conversation_id == conversation_id)
                .order_by(AiMessage.id)
                .all()
            )
            return [Message(role=r.role, content=r.content) for r in rows]
        finally:
            session.close()

    def _persist(
        self, conversation_id: Optional[int], user_id: Optional[int],
        provider: str, model: str, user_messages: List[Message],
        assistant_text: str, output_tokens: Optional[int],
    ) -> None:
        if conversation_id is None or self._session_factory is None:
            return
        from app.db.models import AiMessage

        try:
            session = self._session_factory()
            try:
                for m in user_messages:
                    session.add(AiMessage(
                        conversation_id=conversation_id,
                        role=m.role, content=m.content,
                    ))
                session.add(AiMessage(
                    conversation_id=conversation_id,
                    role="assistant", content=assistant_text,
                    tokens=output_tokens,
                ))
                session.commit()
            finally:
                session.close()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not persist conversation %s: %s",
                           conversation_id, exc)


llm_service = LLMService()
