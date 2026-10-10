import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import llm
from app.db import get_db
from app.models import User
from app.pii import mask_text
from app.schemas import ChatIn, ChatOut
from app.security import get_current_user
from app.services import audit, chatbot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatOut)
def chat(body: ChatIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ask an attendance question in plain English, e.g. "Who was absent yesterday?"."""
    try:
        answer, tools_used = chatbot.answer(db, user, body.message)
    except llm.LLMError:
        logger.exception("llm call failed")
        raise HTTPException(status_code=503, detail="The AI assistant is unavailable right now. Please try again.")
    audit.record(db, request, user, "chat.query", "chat", None,
                 {"question": mask_text(body.message), "tools_used": tools_used})
    db.commit()
    return ChatOut(answer=answer, tools_used=tools_used)
