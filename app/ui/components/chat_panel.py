# -*- coding: utf-8 -*-

"""AI Copilot: selectable provider, streaming responses, persistent
conversation memory (Phase 3 LLM service)."""

import asyncio

from nicegui import ui

from app.services.llm.base import LLMError, Message
from app.services.llm.service import DEFAULT_MODELS, LLMService


def chat_panel(llm: LLMService) -> None:
    providers = llm.available_providers()
    if not providers:
        with ui.card().classes("tv-glass w-full p-5 gap-2"):
            ui.icon("sym_r_info").classes("text-2xl text-primary")
            ui.label("No AI provider is configured").classes(
                "font-medium")
            ui.label(
                "Add an OpenAI, Anthropic or Gemini API key in "
                "Settings to enable the Copilot. Ollama is only "
                "available when you run this app on your own machine."
            ).classes("text-sm tv-muted")
        return
    state = {"conversation_id": None, "busy": False}

    with ui.card().classes("tv-glass w-full p-4 gap-3"):
        with ui.row().classes("w-full items-center gap-3"):
            provider_select = ui.select(
                providers, value=providers[0], label="Provider"
            ).classes("w-40")
            model_input = ui.input(
                "Model",
                value=DEFAULT_MODELS.get(providers[0], ""),
            ).classes("w-56")
            provider_select.on_value_change(
                lambda e: model_input.set_value(
                    DEFAULT_MODELS.get(e.value, "")
                )
            )
            ui.space()
            ui.button(
                "New chat",
                on_click=lambda: (
                    state.update(conversation_id=None),
                    messages_column.clear(),
                ),
            ).props("flat icon=refresh")

        messages_column = ui.column().classes(
            "w-full gap-2 min-h-64 max-h-[55vh] overflow-y-auto"
        )

        async def send() -> None:
            text = prompt_input.value.strip()
            if not text or state["busy"]:
                return
            prompt_input.set_value("")
            state["busy"] = True
            provider = provider_select.value
            model = model_input.value or None
            if state["conversation_id"] is None:
                state["conversation_id"] = await asyncio.to_thread(
                    llm.start_conversation, provider, model, text[:60]
                )
            with messages_column:
                ui.chat_message(text, name="You", sent=True)
                reply = ui.chat_message(name=provider)
                with reply:
                    stream_label = ui.markdown("")
            collected = ""
            try:
                async for delta in llm.chat_stream(
                    [Message("user", text)], provider=provider,
                    model=model,
                    conversation_id=state["conversation_id"],
                ):
                    collected += delta
                    stream_label.set_content(collected)
            except LLMError as exc:
                stream_label.set_content(f"**{exc}**")
            except Exception as exc:      # never leak a traceback
                stream_label.set_content(
                    f"**Something went wrong talking to {provider}:** "
                    f"{type(exc).__name__}")
            finally:
                state["busy"] = False

        with ui.row().classes("w-full items-center gap-2"):
            prompt_input = ui.input(
                placeholder="Ask about destinations, plans, budgets..."
            ).classes("flex-grow").on("keydown.enter", send)
            ui.button(on_click=send).props(
                "round color=primary icon=send"
            )
