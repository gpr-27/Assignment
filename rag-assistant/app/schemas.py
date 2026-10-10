"""Request/response shapes. Pydantic validates every input before it reaches our code."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Letters, numbers, spaces, dashes and underscores.
NAME_PATTERN = r"^[\w\- ]+$"


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # bcrypt only uses the first 72 bytes


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: int
    email: str
    role: str


class NamespaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)


class NamespaceOut(ORMModel):
    id: int
    name: str
    owner_id: int
    created_at: datetime


class CollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    description: str | None = Field(default=None, max_length=1000)


class CollectionOut(ORMModel):
    id: int
    namespace_id: int
    name: str
    description: str | None
    created_at: datetime


class DocumentOut(ORMModel):
    id: int
    collection_id: int
    filename: str
    size_bytes: int
    status: str
    error: str | None
    num_chunks: int
    created_at: datetime
    updated_at: datetime


class SessionIn(BaseModel):
    namespace_id: int
    title: str | None = Field(default=None, max_length=200)


class SessionOut(ORMModel):
    id: int
    namespace_id: int
    title: str | None
    created_at: datetime


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # Optional: search only these collections. Default is the whole namespace.
    collection_ids: list[int] | None = None


class Citation(BaseModel):
    number: int
    document_id: int
    filename: str
    page: int | None
    snippet: str


class MessageOut(ORMModel):
    id: int
    role: str
    content: str
    citations: list[Citation] | None
    created_at: datetime
