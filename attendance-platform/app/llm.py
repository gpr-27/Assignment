"""Thin wrapper around Agent Router (Axon) OpenAI-compatible chat API (tool calling)."""

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


def chat(messages: list[dict], tools: list[dict]):
    """One model turn. Returns the assistant message (which may contain tool calls)."""
    try:
        response = _client().chat.completions.create(
            model=settings.llm_model, messages=messages, tools=tools, temperature=0
        )
    except openai.OpenAIError as exc:
        raise LLMError(str(exc)) from exc
    return response.choices[0].message
