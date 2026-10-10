"""Thin wrapper around Agent Router (Axon) OpenAI-compatible chat API."""

from collections.abc import Iterator
from functools import lru_cache

import openai

from app.config import settings


class LLMError(Exception):
    """The language model could not be reached or returned an error."""


def _openai_base_url() -> str:
    base = settings.llm_base_url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


@lru_cache
def _client() -> openai.OpenAI:
    # The SDK retries timeouts, 429s and 5xx errors with backoff.
    return openai.OpenAI(
        base_url=_openai_base_url(),
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        default_headers={"User-Agent": "rag-assistant/1.0"},
    )


def stream_chat(messages: list[dict]) -> Iterator[str]:
    """Yield the answer text piece by piece as the model generates it."""
    try:
        stream = _client().chat.completions.create(
            model=settings.llm_model, messages=messages, temperature=0.2, stream=True
        )
        for chunk in stream:
            # Some models also stream hidden "reasoning"; we only forward the real answer text.
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except openai.OpenAIError as exc:
        raise LLMError(str(exc)) from exc
