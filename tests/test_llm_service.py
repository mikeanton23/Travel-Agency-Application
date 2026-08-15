# -*- coding: utf-8 -*-

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import AiMessage, Base
from app.services.llm.base import LLMError, Message
from app.services.llm.providers import (
    AnthropicProvider, GeminiProvider, OllamaProvider, OpenAIProvider,
)
from app.services.llm.service import LLMService


def sse(*payloads, done=True):
    body = "".join(f"data: {p}\n\n" for p in payloads)
    if done:
        body += "data: [DONE]\n\n"
    return body.encode()


@pytest.mark.asyncio
async def test_openai_complete_and_stream():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer sk-x"
        if b'"stream": true' in request.content or \
                b'"stream":true' in request.content:
            return httpx.Response(200, content=sse(
                '{"choices":[{"delta":{"content":"Hel"}}]}',
                '{"choices":[{"delta":{"content":"lo"}}]}',
            ), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "Hello"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        })

    provider = OpenAIProvider(
        api_key="sk-x", transport=httpx.MockTransport(handler)
    )
    result = await provider.complete("gpt-4o-mini", [Message("user", "hi")])
    assert result.text == "Hello" and result.output_tokens == 2

    chunks = [c async for c in provider.stream("gpt-4o-mini",
                                               [Message("user", "hi")])]
    assert "".join(chunks) == "Hello"


@pytest.mark.asyncio
async def test_anthropic_system_message_and_stream():
    def handler(request):
        import json
        body = json.loads(request.content)
        assert body.get("system") == "Be brief."
        assert all(m["role"] != "system" for m in body["messages"])
        if body.get("stream"):
            return httpx.Response(200, content=sse(
                '{"type":"content_block_delta","delta":{"text":"Hi "}}',
                '{"type":"content_block_delta","delta":{"text":"there"}}',
                '{"type":"message_stop"}',
                done=False,
            ), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "Hi there"}],
            "usage": {"input_tokens": 8, "output_tokens": 3},
        })

    provider = AnthropicProvider(
        api_key="key", transport=httpx.MockTransport(handler)
    )
    messages = [Message("system", "Be brief."), Message("user", "hello")]
    result = await provider.complete("claude-sonnet-4-6", messages)
    assert result.text == "Hi there"
    chunks = [c async for c in provider.stream("claude-sonnet-4-6",
                                               messages)]
    assert "".join(chunks) == "Hi there"


@pytest.mark.asyncio
async def test_gemini_and_ollama_streaming():
    def gem_handler(request):
        return httpx.Response(200, content=sse(
            '{"candidates":[{"content":{"parts":[{"text":"G1"}]}}]}',
            '{"candidates":[{"content":{"parts":[{"text":"G2"}]}}]}',
            done=False,
        ), headers={"content-type": "text/event-stream"})

    gem = GeminiProvider(api_key="k",
                         transport=httpx.MockTransport(gem_handler))
    chunks = [c async for c in gem.stream("gemini-2.0-flash",
                                          [Message("user", "x")])]
    assert chunks == ["G1", "G2"]

    def ollama_handler(request):
        lines = (b'{"message":{"content":"L1"},"done":false}\n'
                 b'{"message":{"content":"L2"},"done":false}\n'
                 b'{"done":true}\n')
        return httpx.Response(200, content=lines)

    oll = OllamaProvider(transport=httpx.MockTransport(ollama_handler))
    chunks = [c async for c in oll.stream("llama3", [Message("user", "x")])]
    assert chunks == ["L1", "L2"]


@pytest.mark.asyncio
async def test_service_conversation_memory_persists():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def handler(request):
        import json
        body = json.loads(request.content)
        # Second turn must include the persisted history.
        return httpx.Response(200, json={
            "choices": [{"message": {
                "content": f"turn with {len(body['messages'])} msgs"
            }}],
            "usage": {},
        })

    service = LLMService(
        session_factory=factory,
        key_resolver=lambda p: "sk-test",
        provider_overrides={"openai": OpenAIProvider(
            api_key="sk-test", transport=httpx.MockTransport(handler)
        )},
    )
    conv_id = service.start_conversation("openai", title="Trip chat")
    assert conv_id is not None

    r1 = await service.chat([Message("user", "hi")], "openai",
                            conversation_id=conv_id)
    assert r1.text == "turn with 1 msgs"
    r2 = await service.chat([Message("user", "again")], "openai",
                            conversation_id=conv_id)
    assert r2.text == "turn with 3 msgs"  # history(2) + new(1)

    session = factory()
    stored = session.query(AiMessage).filter_by(
        conversation_id=conv_id).count()
    session.close()
    assert stored == 4  # 2 user + 2 assistant


def test_unknown_provider_and_missing_key(monkeypatch):
    # Isolate from the developer's real .env keys.
    import app.utils.config as config
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    service = LLMService(key_resolver=lambda p: None)
    with pytest.raises(LLMError):
        service.get_provider("nonexistent")
    with pytest.raises(LLMError):
        service.get_provider("openai")
    assert service.available_providers() == ["ollama"]


def test_ollama_hidden_in_production(monkeypatch):
    """A localhost daemon cannot exist in a hosted container, so
    offering it guarantees a connection error for the user."""
    from app.utils import settings as settings_module

    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    service = LLMService(key_resolver=lambda p: None)
    assert "ollama" not in service.available_providers()
    assert service.available_providers() == []

    # A remote Ollama host is legitimate and stays listed.
    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.internal:11434")
    assert "ollama" in service.available_providers()
    settings_module.get_settings.cache_clear()


def test_ollama_offered_locally(monkeypatch):
    from app.utils import settings as settings_module

    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    service = LLMService(key_resolver=lambda p: None)
    assert service.available_providers() == ["ollama"]
    settings_module.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_unreachable_provider_gives_a_readable_error(monkeypatch):
    """A transport failure must surface as a clear message, never as a
    raw httpx traceback in the UI."""
    from app.services.llm.providers import OllamaProvider

    def handler(request):
        raise httpx.ConnectError("all connection attempts failed")

    service = LLMService(
        key_resolver=lambda p: None,
        provider_overrides={"ollama": OllamaProvider(
            transport=httpx.MockTransport(handler))},
    )
    with pytest.raises(LLMError) as excinfo:
        await service.chat([Message("user", "hi")], "ollama")
    assert "Ollama" in str(excinfo.value)
    assert "locally" in str(excinfo.value)
