"""Builds the RAG prompt and streams the answer as Server-Sent Events (SSE)."""

import json
import logging
import re
from collections.abc import Iterator

from app import llm
from app.db import SessionLocal
from app.models import ChatMessage
from app.services.retrieval import Source

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an assistant that answers questions using ONLY the numbered sources provided.
Rules:
- Cite every fact with its source number in square brackets, like [1] or [2][3].
- If the sources do not contain the answer, say "I couldn't find that in the documents."
- Never invent facts or citations. Be clear and concise."""

NO_SOURCES_ANSWER = "I couldn't find that in the documents. Upload documents to this namespace and try again."


def build_messages(history: list[ChatMessage], sources: list[Source], question: str) -> list[dict]:
    context = "\n\n".join(
        f"[{s.number}] (file: {s.filename}, page: {s.page or '-'})\n{s.content}" for s in sources
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": m.role, "content": m.content} for m in history]  # conversational memory
    messages.append({"role": "user", "content": f"Sources:\n{context}\n\nQuestion: {question}"})
    return messages


def used_citations(answer: str, sources: list[Source]) -> list[dict]:
    """Keep only the sources the model actually cited in its answer.

    Accepts [1] and the full-width 【1】 that some chat models emit.
    """
    cited = {int(n) for n in re.findall(r"[\[【](\d+)[\]】]", answer)}
    return [s.as_citation() for s in sources if s.number in cited]


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def stream_answer(session_id: int, messages: list[dict], sources: list[Source]) -> Iterator[str]:
    """Events: many `token` events, then `citations`, then `done` (or a single `error`)."""
    parts: list[str] = []
    try:
        if not sources:
            parts.append(NO_SOURCES_ANSWER)
            yield sse("token", {"text": NO_SOURCES_ANSWER})
        else:
            for text in llm.stream_chat(messages):
                parts.append(text)
                yield sse("token", {"text": text})
    except llm.LLMError as exc:
        logger.exception("llm call failed", extra={"session_id": session_id})
        detail = str(exc).strip() or "The AI model is unavailable right now. Please try again."
        yield sse("error", {"detail": detail})
        return
    except Exception:
        logger.exception("unexpected error while streaming answer", extra={"session_id": session_id})
        yield sse("error", {"detail": "Something went wrong while generating the answer. Please try again."})
        return

    answer = "".join(parts).strip()
    if not answer:
        yield sse("error", {"detail": "The AI model returned an empty response. Please try again."})
        return
    citations = used_citations(answer, sources)
    # The request's DB session is gone by the time streaming ends, so open a fresh one.
    with SessionLocal() as db:
        message = ChatMessage(session_id=session_id, role="assistant", content=answer, citations=citations)
        db.add(message)
        db.commit()
    logger.info("answer streamed", extra={"session_id": session_id, "sources": len(sources), "cited": len(citations)})
    yield sse("citations", citations)
    yield sse("done", {"message_id": message.id})
