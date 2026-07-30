# -*- coding: utf-8 -*-

"""Concrete LLM providers. All speak plain REST via httpx so every one
is testable offline with ``httpx.MockTransport``."""

from __future__ import annotations

import json
from typing import AsyncIterator, List

import httpx

from app.services.llm.base import (
    Completion, LLMError, LLMProvider, Message, iter_sse_data, split_system,
)


def _raise_for_status(response: httpx.Response, provider: str) -> None:
    if response.is_error:
        raise LLMError(
            f"{provider} returned {response.status_code}: "
            f"{response.text[:300]}"
        )


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str = "",
                 base_url: str = "https://api.openai.com", **kw) -> None:
        super().__init__(api_key=api_key, base_url=base_url, **kw)

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    async def complete(self, model, messages) -> Completion:
        async with self._client() as client:
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json={"model": model,
                      "messages": [m.to_dict() for m in messages]},
            )
        _raise_for_status(resp, self.name)
        data = resp.json()
        usage = data.get("usage", {})
        return Completion(
            text=data["choices"][0]["message"]["content"],
            provider=self.name, model=model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    async def stream(self, model, messages) -> AsyncIterator[str]:
        async with self._client() as client:
            async with client.stream(
                "POST", f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json={"model": model, "stream": True,
                      "messages": [m.to_dict() for m in messages]},
            ) as resp:
                if resp.is_error:
                    await resp.aread()
                    _raise_for_status(resp, self.name)
                async for chunk in iter_sse_data(resp):
                    delta = (chunk.get("choices") or [{}])[0] \
                        .get("delta", {}).get("content")
                    if delta:
                        yield delta


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str = "",
                 base_url: str = "https://api.anthropic.com", **kw) -> None:
        super().__init__(api_key=api_key, base_url=base_url, **kw)

    def _headers(self):
        return {"x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"}

    def _body(self, model: str, messages: List[Message], stream: bool):
        system, rest = split_system(messages)
        body = {"model": model, "max_tokens": 2048,
                "messages": [m.to_dict() for m in rest]}
        if system:
            body["system"] = system
        if stream:
            body["stream"] = True
        return body

    async def complete(self, model, messages) -> Completion:
        async with self._client() as client:
            resp = await client.post(
                f"{self.base_url}/v1/messages",
                headers=self._headers(),
                json=self._body(model, messages, stream=False),
            )
        _raise_for_status(resp, self.name)
        data = resp.json()
        text = "".join(
            block.get("text", "") for block in data.get("content", [])
            if block.get("type") == "text"
        )
        usage = data.get("usage", {})
        return Completion(
            text=text, provider=self.name, model=model,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

    async def stream(self, model, messages) -> AsyncIterator[str]:
        async with self._client() as client:
            async with client.stream(
                "POST", f"{self.base_url}/v1/messages",
                headers=self._headers(),
                json=self._body(model, messages, stream=True),
            ) as resp:
                if resp.is_error:
                    await resp.aread()
                    _raise_for_status(resp, self.name)
                async for event in iter_sse_data(resp):
                    if event.get("type") == "content_block_delta":
                        text = event.get("delta", {}).get("text")
                        if text:
                            yield text


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self, api_key: str = "",
        base_url: str = "https://generativelanguage.googleapis.com", **kw,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, **kw)

    def _body(self, messages: List[Message]):
        system, rest = split_system(messages)
        body = {"contents": [
            {"role": "model" if m.role == "assistant" else "user",
             "parts": [{"text": m.content}]}
            for m in rest
        ]}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    @staticmethod
    def _extract(chunk) -> str:
        try:
            parts = chunk["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError):
            return ""

    async def complete(self, model, messages) -> Completion:
        async with self._client() as client:
            resp = await client.post(
                f"{self.base_url}/v1beta/models/{model}:generateContent",
                params={"key": self.api_key},
                json=self._body(messages),
            )
        _raise_for_status(resp, self.name)
        data = resp.json()
        usage = data.get("usageMetadata", {})
        return Completion(
            text=self._extract(data), provider=self.name, model=model,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )

    async def stream(self, model, messages) -> AsyncIterator[str]:
        async with self._client() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1beta/models/{model}:"
                f"streamGenerateContent",
                params={"key": self.api_key, "alt": "sse"},
                json=self._body(messages),
            ) as resp:
                if resp.is_error:
                    await resp.aread()
                    _raise_for_status(resp, self.name)
                async for chunk in iter_sse_data(resp):
                    text = self._extract(chunk)
                    if text:
                        yield text


class OllamaProvider(LLMProvider):
    """Local models — llama3, mistral, and anything else Ollama serves.
    No API key required."""

    name = "ollama"

    def __init__(self, api_key: str = "",
                 base_url: str = "http://localhost:11434", **kw) -> None:
        super().__init__(api_key=api_key, base_url=base_url, **kw)

    async def complete(self, model, messages) -> Completion:
        async with self._client() as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json={"model": model, "stream": False,
                      "messages": [m.to_dict() for m in messages]},
            )
        _raise_for_status(resp, self.name)
        data = resp.json()
        return Completion(
            text=data.get("message", {}).get("content", ""),
            provider=self.name, model=model,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
        )

    async def stream(self, model, messages) -> AsyncIterator[str]:
        async with self._client() as client:
            async with client.stream(
                "POST", f"{self.base_url}/api/chat",
                json={"model": model, "stream": True,
                      "messages": [m.to_dict() for m in messages]},
            ) as resp:
                if resp.is_error:
                    await resp.aread()
                    _raise_for_status(resp, self.name)
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("done"):
                        return
                    text = chunk.get("message", {}).get("content")
                    if text:
                        yield text
