"""Namespaces and the collections inside them."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import storage
from app.db import get_db
from app.models import Collection, Document, Namespace, User
from app.schemas import CollectionIn, CollectionOut, NamespaceIn, NamespaceOut
from app.security import get_current_user
from app.services import access

router = APIRouter(tags=["namespaces & collections"])


def _commit_or_conflict(db: Session, what: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"A {what} with this name already exists")


def _delete_files(db: Session, *conditions) -> None:
    """Rows are removed by ON DELETE CASCADE, but files on disk must be removed by us."""
    for doc_id in db.scalars(select(Document.id).join(Collection).where(*conditions)):
        storage.delete_file(doc_id)


@router.post("/namespaces", response_model=NamespaceOut, status_code=status.HTTP_201_CREATED)
def create_namespace(body: NamespaceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    namespace = Namespace(name=body.name, owner_id=user.id)
    db.add(namespace)
    _commit_or_conflict(db, "namespace")
    return namespace


@router.get("/namespaces", response_model=list[NamespaceOut])
def list_namespaces(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Namespace).order_by(Namespace.name)
    if user.role != "admin":
        stmt = stmt.where(Namespace.owner_id == user.id)
    return db.scalars(stmt).all()


@router.delete("/namespaces/{namespace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_namespace(namespace_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    namespace = access.get_namespace(db, user, namespace_id)
    _delete_files(db, Collection.namespace_id == namespace.id)
    db.delete(namespace)
    db.commit()


@router.post(
    "/namespaces/{namespace_id}/collections", response_model=CollectionOut, status_code=status.HTTP_201_CREATED
)
def create_collection(
    namespace_id: int, body: CollectionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    namespace = access.get_namespace(db, user, namespace_id)
    collection = Collection(namespace_id=namespace.id, name=body.name, description=body.description)
    db.add(collection)
    _commit_or_conflict(db, "collection")
    return collection


@router.get("/namespaces/{namespace_id}/collections", response_model=list[CollectionOut])
def list_collections(namespace_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    namespace = access.get_namespace(db, user, namespace_id)
    return db.scalars(select(Collection).where(Collection.namespace_id == namespace.id).order_by(Collection.name)).all()


@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection(collection_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    collection = access.get_collection(db, user, collection_id)
    _delete_files(db, Collection.id == collection.id)
    db.delete(collection)
    db.commit()
