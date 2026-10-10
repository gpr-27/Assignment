from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import ChatMessage, ChatSession, Collection, User
from app.schemas import AskIn, MessageOut, SessionIn, SessionOut
from app.security import get_current_user
from app.services import access
from app.services.chat import build_messages, stream_answer
from app.services.retrieval import search

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(body: SessionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    access.get_namespace(db, user, body.namespace_id)
    session = ChatSession(user_id=user.id, namespace_id=body.namespace_id, title=body.title)
    db.add(session)
    db.commit()
    return session


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.created_at.desc())
    ).all()


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
def list_messages(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = access.get_chat_session(db, user, session_id)
    return db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.id)
    ).all()


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(access.get_chat_session(db, user, session_id))
    db.commit()


@router.post("/sessions/{session_id}/ask")
def ask(session_id: int, body: AskIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ask a question. The answer is streamed back as Server-Sent Events:

    - `token`     {"text": "..."}       many times, as the answer is generated
    - `citations` [{number, filename, page, snippet, ...}]
    - `done`      {"message_id": 123}
    - `error`     {"detail": "..."}     instead of the above if the AI model fails
    """
    session = access.get_chat_session(db, user, session_id)

    if body.collection_ids:
        valid = set(db.scalars(select(Collection.id).where(
            Collection.namespace_id == session.namespace_id, Collection.id.in_(body.collection_ids)
        )))
        if valid != set(body.collection_ids):
            raise HTTPException(status_code=400, detail="Some collections are not in this chat's namespace")

    # Conversational memory: the last few messages of this session.
    history = list(reversed(db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id.desc()).limit(settings.history_messages)
    ).all()))

    # Follow-ups like "and what about the second one?" retrieve poorly on their own,
    # so we search with the previous question as extra context.
    last_question = next((m.content for m in reversed(history) if m.role == "user"), "")
    sources = search(db, session.namespace_id, f"{last_question}\n{body.question}".strip(),
                     body.collection_ids, settings.top_k)

    db.add(ChatMessage(session_id=session.id, role="user", content=body.question))
    if not session.title:
        session.title = body.question[:60]
    db.commit()

    messages = build_messages(history, sources, body.question)
    return StreamingResponse(
        stream_answer(session.id, messages, sources),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
