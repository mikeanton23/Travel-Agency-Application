# -*- coding: utf-8 -*-

"""LLM provider abstraction: uniform complete() and stream() over
OpenAI, Anthropic, Gemini, and Ollama (which also serves Mistral and
Llama models locally)."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx


@dataclass
class Message:
    role: str          # system / user / assistant
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class LLMError(Exception):
    pass


class LLMProvider(ABC):
    name: str = "base"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        timeout: float = 120.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport
        )

    @abstractmethod
    async def complete(self, model: str,
                       messages: List[Message]) -> Completion: ...

    @abstractmethod
    def stream(self, model: str,
               messages: List[Message]) -> AsyncIterator[str]: ...


async def iter_sse_data(response: httpx.Response) -> AsyncIterator[Any]:
    """Yield parsed JSON payloads from an SSE stream; skips keep-alives
    and stops on ``[DONE]``."""
    async for line in response.aiter_lines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue


def split_system(messages: List[Message]):
    """(system_text, non_system_messages) — Anthropic/Gemini need this."""
    system_parts = [m.content for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]
    return ("\n\n".join(system_parts) if system_parts else None), rest
