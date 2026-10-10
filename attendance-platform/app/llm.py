"""Thin wrapper around any OpenAI-compatible chat API that supports tool calling (Groq by default)."""

from functools import lru_cache

import openai

from app.config import settings


class LLMError(Exception):
    """The language model could not be reached or returned an error."""


@lru_cache
def _client() -> openai.OpenAI:
    # The SDK retries timeouts, 429s and 5xx errors with backoff.
    return openai.OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
    )


def chat(messages: list[dict], tools: list[dict]):
    """One model turn. Returns the assistant message (which may contain tool calls)."""
    try:
        response = _client().chat.completions.create(
            model=settings.llm_model, messages=messages, tools=tools, temperature=0
        )
    except openai.OpenAIError as exc:
        raise LLMError(str(exc)) from exc
    return response.choices[0].message
