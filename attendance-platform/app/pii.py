"""PII masking. Used before data goes to the LLM, into audit logs, or into application logs."""

import re

EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
# Digits with optional single spaces/dashes between them, e.g. "+91 98765-43210".
# Only runs of 10+ digits are treated as phone numbers, so dates like 2026-10-09 are left alone.
PHONE_RE = re.compile(r"\+?\d(?:[\s-]?\d)+")


def mask_email(email: str) -> str:
    """john.doe@acme.com -> j***@acme.com"""
    return EMAIL_RE.sub(r"\1***@\2", email)


def mask_phone(phone: str) -> str:
    """+91 98765 43210 -> ******3210"""
    digits = re.sub(r"\D", "", phone)
    return "******" + digits[-4:]


def mask_text(text: str) -> str:
    """Mask any emails and phone numbers found inside free text."""
    text = EMAIL_RE.sub(r"\1***@\2", text)
    return PHONE_RE.sub(lambda m: mask_phone(m.group()) if _digit_count(m.group()) >= 10 else m.group(), text)


def _digit_count(text: str) -> int:
    return sum(ch.isdigit() for ch in text)


def mask_dict(data: dict) -> dict:
    """Mask known sensitive fields (and anything that looks like PII in other string values)."""
    masked = {}
    for key, value in data.items():
        if key == "password":
            masked[key] = "***"
        elif key == "email" and isinstance(value, str):
            masked[key] = mask_email(value)
        elif key == "phone" and isinstance(value, str):
            masked[key] = mask_phone(value)
        elif isinstance(value, str):
            masked[key] = mask_text(value)
        elif isinstance(value, dict):
            masked[key] = mask_dict(value)
        else:
            masked[key] = value
    return masked
