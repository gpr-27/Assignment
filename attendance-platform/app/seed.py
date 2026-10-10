"""Fills the database with demo data: 2 shifts, 8 employees and ~6 weeks of attendance.

Run once:  python -m app.seed
Every employee's password is "password123".
"""

import random
from datetime import datetime, time, timedelta

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.main import create_admin_if_missing
from app.models import Attendance, Shift, User
from app.security import hash_password
from app.services.attendance import is_late, now, tz

EMPLOYEES = [
    ("E001", "Aarav Sharma", "Engineering", "+91 98765 43210", 0.03),  # last value = chance of absence
    ("E002", "Priya Nair", "Engineering", "+91 98765 43211", 0.05),
    ("E003", "Rohan Gupta", "Engineering", "+91 98765 43212", 0.20),
    ("E004", "Ananya Iyer", "Sales", "+91 98765 43213", 0.08),
    ("E005", "Vikram Singh", "Sales", "+91 98765 43214", 0.15),
    ("E006", "Meera Reddy", "Support", "+91 98765 43215", 0.04),
    ("E007", "Kabir Khan", "Support", "+91 98765 43216", 0.10),
    ("E008", "Sneha Patel", "HR", "+91 98765 43217", 0.02),
]
DAYS = 42


def seed() -> None:
    init_db()
    create_admin_if_missing()
    random.seed(7)
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.employee_code == "E001")):
            print("Demo data already present, nothing to do.")
            return

        day_shift = Shift(name="Day", start_time=time(9, 30), end_time=time(18, 30), grace_minutes=10)
        early_shift = Shift(name="Early", start_time=time(7, 0), end_time=time(16, 0), grace_minutes=10)
        db.add_all([day_shift, early_shift])
        db.flush()

        today = now().date()
        joined = datetime.combine(today - timedelta(days=DAYS + 1), time(9), tzinfo=tz())
        password = hash_password("password123")
        for i, (code, name, dept, phone, absence_chance) in enumerate(EMPLOYEES):
            shift = early_shift if dept == "Support" else day_shift
            user = User(
                employee_code=code, full_name=name, department=dept, phone=phone, role="employee",
                email=name.lower().replace(" ", ".") + "@acme.com", password_hash=password,
                shift_id=shift.id, created_at=joined,
            )
            db.add(user)
            db.flush()

            for offset in range(DAYS, 0, -1):  # up to yesterday; today is left for a live demo
                day = today - timedelta(days=offset)
                if day.weekday() >= 5 or random.random() < absence_chance:
                    continue
                start = datetime.combine(day, shift.start_time, tzinfo=tz())
                punch_in = start + timedelta(minutes=random.choice([-15, -5, 0, 5, 8, 20, 35]) if i % 3 == 2
                                             else random.randint(-20, 12))
                punch_out = punch_in + timedelta(hours=9, minutes=random.randint(-30, 45))
                db.add(Attendance(user_id=user.id, work_date=day, punch_in=punch_in, punch_out=punch_out,
                                  is_late=is_late(punch_in, shift)))
        db.commit()
    print(f"Seeded {len(EMPLOYEES)} employees with {DAYS} days of attendance. Password: password123")


if __name__ == "__main__":
    seed()
