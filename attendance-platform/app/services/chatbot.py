"""Natural-language attendance assistant.

The LLM never writes SQL or sees the database. It can only call the fixed "tools" below, and the
tools available depend on the caller's role: employees can only ask about themselves.
Everything sent to the LLM (the question and tool results) is PII-masked first.
"""

import json
import logging
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.models import User
from app.pii import mask_text
from app.services import reports
from app.services.attendance import now

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4

_DATE = {"type": "string", "description": "Date in YYYY-MM-DD format"}
_RANGE = {"type": "object", "properties": {"start_date": _DATE, "end_date": _DATE}, "required": ["start_date", "end_date"]}


def _tool(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


EMPLOYEE_TOOLS = [
    _tool("get_my_attendance", "The current user's own attendance records and summary for a date range.", _RANGE),
]
ADMIN_TOOLS = EMPLOYEE_TOOLS + [
    _tool("get_daily_summary", "Per working day: number of employees present, late and absent.", _RANGE),
    _tool("get_absenteeism_report", "Per employee absent days, late days and absence rate, worst first.", _RANGE),
    _tool("get_absentees", "Employees who were absent on one specific day.",
          {"type": "object", "properties": {"day": _DATE}, "required": ["day"]}),
    _tool("get_late_arrivals", "Every late punch-in within a date range.", _RANGE),
    _tool("get_employee_attendance", "One employee's attendance records and summary, by employee code.",
          {"type": "object", "properties": {"employee_code": {"type": "string"}, **_RANGE["properties"]},
           "required": ["employee_code", "start_date", "end_date"]}),
]

SYSTEM_PROMPT = """You are an attendance assistant. You are talking to {name} (role: {role}).
Today is {today} ({weekday}).
- Always use the tools to get data. Never guess or invent numbers.
- Convert relative dates like "yesterday", "last week" or "this month" into exact dates yourself.
- If a question is not about attendance, or needs data you have no tool for, say so briefly.
- Answer in short, clear sentences. Use a small table or list when showing several people."""


def tools_for(user: User) -> list[dict]:
    return ADMIN_TOOLS if user.role == "admin" else EMPLOYEE_TOOLS


def run_tool(db: Session, user: User, name: str, args: dict):
    """Execute one tool call. Errors are returned to the LLM as data so it can explain them."""
    if name not in {t["function"]["name"] for t in tools_for(user)}:
        return {"error": "You don't have permission to access this information."}

    def day(key: str) -> date:
        return date.fromisoformat(args[key])

    try:
        if name == "get_my_attendance":
            return reports.employee_attendance(db, user, day("start_date"), day("end_date"))
        if name == "get_daily_summary":
            return reports.daily_summary(db, day("start_date"), day("end_date"))
        if name == "get_absenteeism_report":
            return reports.absenteeism(db, day("start_date"), day("end_date"))
        if name == "get_absentees":
            return reports.absentees_on(db, day("day"))
        if name == "get_late_arrivals":
            return reports.late_arrivals(db, day("start_date"), day("end_date"))
        if name == "get_employee_attendance":
            employee = db.scalar(select(User).where(User.employee_code == args["employee_code"]))
            if employee is None:
                return {"error": f"No employee with code {args['employee_code']}"}
            return reports.employee_attendance(db, employee, day("start_date"), day("end_date"))
    except (KeyError, ValueError) as exc:
        return {"error": f"Invalid arguments: {exc}"}
    except HTTPException as exc:
        return {"error": exc.detail}
    return {"error": f"Unknown tool {name}"}


def answer(db: Session, user: User, question: str) -> tuple[str, list[str]]:
    """Returns (answer, names of tools used). Loop: ask model -> run requested tools -> repeat."""
    today = now().date()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(
            name=user.full_name, role=user.role, today=today.isoformat(), weekday=today.strftime("%A"))},
        {"role": "user", "content": mask_text(question)},
    ]
    tools_used: list[str] = []

    for _ in range(MAX_TOOL_ROUNDS):
        reply = llm.chat(messages, tools_for(user))
        if not reply.tool_calls:
            return reply.content or "", tools_used

        messages.append({
            "role": "assistant",
            "content": reply.content or "",
            "tool_calls": [{"id": c.id, "type": "function",
                            "function": {"name": c.function.name, "arguments": c.function.arguments}}
                           for c in reply.tool_calls],
        })
        for call in reply.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = run_tool(db, user, call.function.name, args)
            tools_used.append(call.function.name)
            logger.info("chat tool called", extra={"tool": call.function.name, "user_id": user.id})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": mask_text(json.dumps(result))})

    return "Sorry, I couldn't work that out. Please try asking in a simpler way.", tools_used
