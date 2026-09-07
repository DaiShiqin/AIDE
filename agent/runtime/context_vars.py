from __future__ import annotations

import re
from datetime import date
from typing import Any


DATE_RE = re.compile(
    r"(?P<year>20\d{2})\s*(?:年|/|-)\s*(?P<month>\d{1,2})\s*(?:月|/|-)\s*(?P<day>\d{1,2})\s*(?:日|号)?"
)
MONTH_DAY_RE = re.compile(
    r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*(?:日|号)?"
)
DEFAULT_CONTEXT_YEAR = 2026


def extract_dialog_context(text: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    context = dict(previous or {})
    if _requests_full_period(text):
        for key in ("requested_start_time", "requested_end_time", "requested_time_text"):
            context.pop(key, None)
        return context
    time_context = extract_time_range(text)
    if time_context:
        context.update(time_context)
    return context


def extract_time_range(text: str) -> dict[str, str]:
    text = text or ""
    match = DATE_RE.search(text)
    if match:
        start = _date_from_match(match)
        end = _parse_range_end(text[match.end() : match.end() + 40], start) or start
        return _time_context(start, end)

    match = MONTH_DAY_RE.search(text)
    if not match:
        return {}
    start = date(DEFAULT_CONTEXT_YEAR, int(match.group("month")), int(match.group("day")))
    end = _parse_range_end(text[match.end() : match.end() + 40], start) or start
    return _time_context(start, end)


def format_context_variables(context: dict[str, Any] | None) -> str:
    if not context:
        return "无"
    preferred_keys = ["requested_start_time", "requested_end_time", "requested_time_text"]
    lines = [f"- {key}: {context[key]}" for key in preferred_keys if context.get(key)]
    for key, value in context.items():
        if key not in preferred_keys:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "无"


def _requests_full_period(text: str) -> bool:
    return any(token in (text or "") for token in ("全时段", "全部时段", "完整时段", "所有时间", "全时间"))


def _time_context(start: date, end: date) -> dict[str, str]:
    return {
        "requested_start_time": start.isoformat(),
        "requested_end_time": end.isoformat(),
        "requested_time_text": f"{start.isoformat()} to {end.isoformat()}",
    }


def _date_from_match(match: re.Match[str]) -> date:
    return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))


def _parse_range_end(fragment: str, start: date) -> date | None:
    cleaned = fragment.strip()
    if not re.match(r"^(?:-|~|—|–|至|到|to\b)", cleaned, flags=re.IGNORECASE):
        return None
    rest = re.sub(r"^(?:-|~|—|–|至|到|to\b)\s*", "", cleaned, flags=re.IGNORECASE)
    full_date = DATE_RE.match(rest)
    if full_date:
        return _date_from_match(full_date)
    partial = re.match(r"(?:(?P<month>\d{1,2})\s*月\s*)?(?P<day>\d{1,2})\s*(?:日|号)?", rest)
    if not partial:
        return None
    month = int(partial.group("month") or start.month)
    day = int(partial.group("day"))
    return date(start.year, month, day)
