"""Thin wrapper around the official Anthropic Messages API (streaming)."""

import json
from collections.abc import Iterator

import anthropic

from app.config import settings


class LLMError(Exception):
    """The language model could not be reached or returned an error."""


def _split_system(messages: list[dict]) -> tuple[str | None, list[dict]]:
    system_parts: list[str] = []
    rest: list[dict] = []
    for message in messages:
        if message["role"] == "system":
            system_parts.append(message["content"])
        else:
            rest.append(message)
    system = "\n\n".join(system_parts).strip() if system_parts else None
    return system, rest


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Convert internal OpenAI-style history to Anthropic message format."""
    out: list[dict] = []
    for message in messages:
        role = message["role"]
        if role == "user":
            out.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            blocks: list[dict] = []
            if message.get("content"):
                blocks.append({"type": "text", "text": message["content"]})
            for call in message.get("tool_calls") or []:
                fn = call["function"]
                try:
                    tool_input = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    tool_input = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": fn["name"],
                        "input": tool_input,
                    }
                )
            out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message["tool_call_id"],
                            "content": message["content"],
                        }
                    ],
                }
            )
    return out


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
    )


def stream_chat(messages: list[dict]) -> Iterator[str]:
    """Yield the answer text piece by piece as the model generates it."""
    system, body = _split_system(messages)
    kwargs: dict = {
        "model": settings.llm_model,
        "max_tokens": 4096,
        "messages": _to_anthropic_messages(body),
        "temperature": 0.2,
    }
    if system:
        kwargs["system"] = system
    saw_content = False
    try:
        with _client().messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                if text:
                    saw_content = True
                    yield text
        if not saw_content:
            raise LLMError("The model returned an empty response.")
    except anthropic.APIError as exc:
        raise LLMError(str(exc)) from exc
