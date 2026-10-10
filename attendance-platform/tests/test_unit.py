"""Pure logic tests, no database needed."""

from datetime import date, datetime, time

from app.models import Shift
from app.pii import mask_dict, mask_email, mask_phone, mask_text
from app.services.attendance import is_late, tz
from app.services.reports import working_days


def test_mask_email_and_phone():
    assert mask_email("john.doe@acme.com") == "j***@acme.com"
    assert mask_phone("+91 98765 43210") == "******3210"


def test_mask_text_masks_pii_but_keeps_dates():
    text = "Call +91 98765 43210 or mail priya.nair@acme.com about 2026-10-09 at 09:30"
    assert mask_text(text) == "Call ******3210 or mail p***@acme.com about 2026-10-09 at 09:30"


def test_mask_dict():
    masked = mask_dict({"email": "a.b@x.com", "phone": "9876543210", "password": "secret", "name": "Ann"})
    assert masked == {"email": "a***@x.com", "phone": "******3210", "password": "***", "name": "Ann"}


def test_is_late_uses_grace_period():
    shift = Shift(name="Day", start_time=time(9, 30), end_time=time(18, 30), grace_minutes=10)
    at = lambda h, m: datetime(2026, 10, 9, h, m, tzinfo=tz())  # noqa: E731
    assert not is_late(at(9, 40), shift)
    assert is_late(at(9, 41), shift)
    assert not is_late(at(9, 41), None)  # no shift assigned -> never late


def test_working_days_skip_weekends():
    # 2026-10-05 is a Monday
    days = working_days(date(2026, 10, 5), date(2026, 10, 11))
    assert [d.weekday() for d in days] == [0, 1, 2, 3, 4]
