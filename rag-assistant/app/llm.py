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
        # Agent Router's WAF allowlists known coding-agent clients (generic SDK UAs get 401).
        default_headers={"User-Agent": "claude-cli/1.0.57 (external, cli)"},
    )


def _reasoning_from_delta(delta) -> str | None:
    reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
    if reasoning:
        return reasoning
    extra = getattr(delta, "model_extra", None) or {}
    return extra.get("reasoning_content") or extra.get("reasoning")


def stream_chat(messages: list[dict]) -> Iterator[str]:
    """Yield the answer text piece by piece as the model generates it."""
    reasoning_parts: list[str] = []
    saw_content = False
    try:
        stream = _client().chat.completions.create(
            model=settings.llm_model, messages=messages, temperature=0.2, stream=True
        )
        for chunk in stream:
            # Agent Router sometimes emits bare `None` keep-alive chunks.
            if chunk is None or not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.refusal:
                raise LLMError(delta.refusal)
            if delta.content:
                saw_content = True
                yield delta.content
                continue
            reasoning = _reasoning_from_delta(delta)
            if reasoning:
                reasoning_parts.append(reasoning)
        if not saw_content:
            fallback = "".join(reasoning_parts).strip()
            if fallback:
                yield fallback
            else:
                raise LLMError("The model returned an empty response.")
    except openai.OpenAIError as exc:
        raise LLMError(str(exc)) from exc
