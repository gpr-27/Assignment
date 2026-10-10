"""Ownership checks. A user may touch a namespace (and everything inside it) if they own it or are an admin.

We answer 404 rather than 403 for other people's data, so ids can't be probed.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import ChatSession, Collection, Document, Namespace, User


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def can_access(user: User, namespace: Namespace) -> bool:
    return user.role == "admin" or namespace.owner_id == user.id


def get_namespace(db: Session, user: User, namespace_id: int) -> Namespace:
    namespace = db.get(Namespace, namespace_id)
    if namespace is None or not can_access(user, namespace):
        raise _not_found("Namespace")
    return namespace


def get_collection(db: Session, user: User, collection_id: int) -> Collection:
    collection = db.get(Collection, collection_id)
    if collection is None or not can_access(user, db.get(Namespace, collection.namespace_id)):
        raise _not_found("Collection")
    return collection


def get_document(db: Session, user: User, document_id: int) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise _not_found("Document")
    get_collection(db, user, document.collection_id)
    return document


def get_chat_session(db: Session, user: User, session_id: int) -> ChatSession:
    # Chat history is private: only the person who started the session can read it.
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise _not_found("Chat session")
    return session
