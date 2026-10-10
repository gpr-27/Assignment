"""Request/response shapes. Pydantic validates every input before it reaches our code."""

from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, computed_field, field_serializer

from app.config import settings


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Users ----------
class UserCreate(BaseModel):
    employee_code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9-]+$")
    full_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, pattern=r"^\+?[\d\s-]{7,20}$")
    department: str | None = Field(default=None, max_length=50)
    role: Literal["employee", "admin"] = "employee"
    password: str = Field(min_length=8, max_length=72)  # bcrypt only uses the first 72 bytes
    shift_id: int | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, pattern=r"^\+?[\d\s-]{7,20}$")
    department: str | None = Field(default=None, max_length=50)
    role: Literal["employee", "admin"] | None = None
    password: str | None = Field(default=None, min_length=8, max_length=72)
    shift_id: int | None = None
    is_active: bool | None = None


class UserOut(ORMModel):
    id: int
    employee_code: str
    full_name: str
    email: str
    phone: str | None
    department: str | None
    role: str
    shift_id: int | None
    is_active: bool


# ---------- Shifts ----------
class ShiftIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    start_time: time
    end_time: time
    grace_minutes: int = Field(default=10, ge=0, le=120)


class ShiftOut(ORMModel):
    id: int
    name: str
    start_time: time
    end_time: time
    grace_minutes: int


# ---------- Attendance ----------
class AttendanceOut(ORMModel):
    id: int
    user_id: int
    work_date: date
    punch_in: datetime
    punch_out: datetime | None
    is_late: bool
    notes: str | None

    @computed_field
    @property
    def hours_worked(self) -> float | None:
        if self.punch_out is None:
            return None
        return round((self.punch_out - self.punch_in).total_seconds() / 3600, 2)

    @field_serializer("punch_in", "punch_out")
    def _local_time(self, value: datetime | None):
        # Show times in the company's timezone rather than UTC.
        return value.astimezone(ZoneInfo(settings.timezone)) if value else None


class AttendanceUpdate(BaseModel):
    """Admin correction of a record (e.g. employee forgot to punch out)."""

    punch_in: AwareDatetime | None = None  # must include a timezone, e.g. 2026-10-09T09:30:00+05:30
    punch_out: AwareDatetime | None = None
    notes: str | None = Field(default=None, max_length=500)


# ---------- Audit ----------
class AuditLogOut(ORMModel):
    id: int
    actor_id: int | None
    action: str
    entity: str
    entity_id: int | None
    details: dict | None
    ip_address: str | None
    created_at: datetime


# ---------- Chat ----------
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class ChatOut(BaseModel):
    answer: str
    tools_used: list[str]
