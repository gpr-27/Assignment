"""Thin wrapper around the official Anthropic Messages API (tool use)."""

import json
from types import SimpleNamespace

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


def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
    anthropic_tools: list[dict] = []
    for tool in tools:
        fn = tool["function"]
        anthropic_tools.append(
            {
                "name": fn["name"],
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return anthropic_tools


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
    )


def message_text(message) -> str:
    """Visible assistant text from an OpenAI-shaped assistant message object."""
    if message.content:
        return message.content
    return ""


def _parse_response(response) -> SimpleNamespace:
    text_parts: list[str] = []
    tool_calls: list[SimpleNamespace] = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(
                SimpleNamespace(
                    id=block.id,
                    function=SimpleNamespace(
                        name=block.name,
                        arguments=json.dumps(block.input),
                    ),
                )
            )
    content = "".join(text_parts) if text_parts else None
    return SimpleNamespace(content=content, tool_calls=tool_calls or None)


def chat(messages: list[dict], tools: list[dict]):
    """One model turn. Returns an assistant message (which may contain tool calls)."""
    system, body = _split_system(messages)
    kwargs: dict = {
        "model": settings.llm_model,
        "max_tokens": 4096,
        "messages": _to_anthropic_messages(body),
        "temperature": 0,
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = _to_anthropic_tools(tools)
    try:
        response = _client().messages.create(**kwargs)
    except anthropic.APIError as exc:
        raise LLMError(str(exc)) from exc
    if not response.content:
        raise LLMError("The model returned an empty response.")
    return _parse_response(response)
