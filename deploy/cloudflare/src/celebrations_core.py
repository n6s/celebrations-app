"""Cloudflare Worker-compatible celebration helpers.

This module intentionally mirrors a subset of the shared CLI helpers used by the
worker runtime so it avoids external dependencies (such as dateutil) that are
not available in Workers' Python environment.
"""

from collections import defaultdict
from datetime import datetime, timedelta


def all_entries_for_tenant(tenant):
    return list(tenant.get("birthdays", [])) + list(tenant.get("anniversaries", []))


def next_entry_id(entries, prefix):
    existing = {entry.get("id") for entry in entries if entry.get("id")}
    counter = 1
    while True:
        candidate = f"{prefix}-{counter:03d}"
        if candidate not in existing:
            return candidate
        counter += 1


def find_entry_by_id(tenant, entry_id):
    for bucket in ("birthdays", "anniversaries"):
        entries = tenant.get(bucket, [])
        for index, entry in enumerate(entries):
            if entry.get("id") == entry_id:
                return bucket, index, entry
    return None


def create_birthday_entry(tenant, name, birthdate, hint=None):
    tenant_bdays = tenant.setdefault("birthdays", [])
    new_entry = {
        "id": next_entry_id(tenant_bdays, "b"),
        "entry_type": "birthday",
        "name": name,
        "birthdate": birthdate,
    }
    if hint:
        new_entry["hint"] = hint
    tenant_bdays.append(new_entry)
    return new_entry


def create_anniversary_entry(
    tenant,
    name,
    anniversary_date,
    kind="wedding_anniversary",
    hint=None,
):
    tenant_anniversaries = tenant.setdefault("anniversaries", [])
    new_entry = {
        "id": next_entry_id(tenant_anniversaries, "a"),
        "entry_type": "anniversary",
        "name": name,
        "date": anniversary_date,
        "kind": kind,
    }
    if hint:
        new_entry["hint"] = hint
    tenant_anniversaries.append(new_entry)
    return new_entry


def delete_entry_by_id(tenant, entry_id):
    lookup = find_entry_by_id(tenant, entry_id)
    if not lookup:
        return None

    bucket, index, _ = lookup
    return tenant[bucket].pop(index)


def get_today(override_date=None):
    return datetime.strptime(override_date, "%Y-%m-%d").date() if override_date else datetime.now().date()


def _safe_monthday(year, month, day):
    try:
        return datetime(year, month, day).date()
    except ValueError:
        # For non-leap years and invalid day values (e.g. Feb 29), clamp to the
        # last valid day of the month.
        next_month = datetime(year, month % 12 + 1, 1)
        return (next_month - timedelta(days=1)).date()


def _ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _anniversary_kind_label(entry):
    return (entry.get("kind") or "anniversary").replace("_", " ")


def _message_for_birthday(person, event_date, today):
    birthdate = datetime.strptime(person["birthdate"], "%Y-%m-%d").date()
    if not birthdate:
        return None
    age = event_date.year - birthdate.year
    name = person.get("name", "Unknown")
    hint = person.get("hint")
    if event_date == today:
        suffix = ""
    else:
        suffix = ""
    base = f"🎂 {_ordinal(age)} Birthday, {name}!"
    if hint:
        base = f"🎂 {_ordinal(age)} Birthday ({hint}), {name}!"
    return base


def _message_for_anniversary(entry, event_date, today):
    kind = _anniversary_kind_label(entry)
    ann_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
    years = event_date.year - ann_date.year
    name = entry.get("name", "Unknown")
    short_name = entry.get("short_name")
    if short_name:
        name = short_name
    return f"💍 {_ordinal(years)} {kind.title()} ({name})!"


def _next_occurrence(entry, today):
    if entry.get("entry_type") == "anniversary":
        ann_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
        target = _safe_monthday(today.year, ann_date.month, ann_date.day)
        if target < today:
            target = _safe_monthday(today.year + 1, ann_date.month, ann_date.day)
        return target

    birthdate = datetime.strptime(entry["birthdate"], "%Y-%m-%d").date()
    target = _safe_monthday(today.year, birthdate.month, birthdate.day)
    if target < today:
        target = _safe_monthday(today.year + 1, birthdate.month, birthdate.day)
    return target


def _today_messages_for_day(data, target_dates):
    results = []
    for entry in data:
        if entry.get("entry_type") == "anniversary":
            if not entry.get("date"):
                continue
            date_text = entry.get("date")
            try:
                event_date = datetime.strptime(date_text, "%Y-%m-%d").date()
            except ValueError:
                continue
            if _next_occurrence(entry, target_dates) == target_dates:
                message = _message_for_anniversary(entry, event_date, target_dates)
                results.append((message, target_dates, entry, "celebration"))
        else:
            date_text = entry.get("birthdate")
            if not date_text:
                continue
            try:
                _ = datetime.strptime(date_text, "%Y-%m-%d").date()
            except ValueError:
                continue
            next_occurrence = _next_occurrence(entry, target_dates)
            if next_occurrence == target_dates:
                message = _message_for_birthday(entry, target_dates, target_dates)
                if message:
                    results.append((message, target_dates, entry, "celebration"))

    # Sort by name for deterministic output.
    return sorted(results, key=lambda item: (str(item[1]), str(item[2].get("name", ""))))


def calculate_all_celebrations(data, target_dates):
    target = target_dates
    if not hasattr(target, "isoformat"):
        return []
    celebrations = _today_messages_for_day(data, target)

    bucket = defaultdict(list)
    for message, date, person, category in celebrations:
        key = date.isoformat()
        bucket[key].append((message, date, person, category))

    merged = []
    for key in sorted(bucket.keys()):
        events = sorted(bucket[key], key=lambda item: str(item[2].get("name", "")).lower())
        merged.extend(events)
    return merged


def upcoming_celebrations(data, today, days_ahead=4):
    upcoming = []
    for offset in range(1, days_ahead + 1):
        future = today + timedelta(days=offset)
        future_msgs = calculate_all_celebrations(data, future)
        if future_msgs:
            upcoming.append((f"📅 [{future.isoformat()}]", future, None, "date_header"))
            for item in future_msgs:
                if isinstance(item, tuple) and len(item) == 4:
                    upcoming.append(item)
    return upcoming
