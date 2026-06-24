# utils.py
from collections import defaultdict
from datetime import date as dt_date
from datetime import datetime, timedelta

from celebrations_core import (calculate_all_celebrations, get_today,
                               load_all_celebrations,
                               load_birthdays,
                               resolve_config_paths,
                               tenant_display_name,
                               upcoming_budget_birthdays,
                               upcoming_celebrations,
                               upcoming_milestone_dates_for)

def render_output(entries):
    lines = []
    for entry in entries:
        if isinstance(entry, tuple):
            message = entry[0]
            lines.append(message)
        elif isinstance(entry, str):
            lines.append(entry)
    return "\n".join(lines) if lines else "No celebrations found."


def extract_messages(entries, category_filter=None, markup=False):
    if category_filter is None:
        filtered = entries
    elif isinstance(category_filter, (list, tuple, set)):
        filtered = [entry for entry in entries if entry[-1] in category_filter]
    else:
        filtered = [entry for entry in entries if entry[-1] == category_filter]

    output = []
    for msg, _date, person, category in filtered:
        if category in ("label", "date_header"):
            output.append("")  # newline
        if category == "label" and person:
            gender = (person.get("gender") or "").lower()
            if markup:
                if person.get("entry_type") == "anniversary":
                    color = "cc8800"
                else:
                    color = "ff66cc" if gender == "f" else "3399ff"  # magenta / blue
                msg = f"[color={color}]{msg}[/color]"
        output.append(msg)
    return output

def generate_ical_text(events, days_ahead=None):

    def sanitize(text):
        return text.replace(",", "\\,").replace("\n", "\\n")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "PRODID:-//Celebrations App//EN"
    ]

    # Group events by (person_name, date)
    grouped = defaultdict(list)
    for event in events:
        if not isinstance(event, tuple) or len(event) < 4:
            continue
        message, date, person, category = event
        if category != "celebration" or not isinstance(message, str) or not isinstance(date, dt_date):
            continue
        person_name = person.get("name") if isinstance(person, dict) else "Unknown"
        grouped[(person_name, date)].append(event)

    count = 0
    for (_name, date), group in grouped.items():
        primary = group[0]
        extras = group[1:]

        msg, _, person, _ = primary
        uid = f"{date.strftime('%Y%m%d')}-{hash(msg) & 0xFFFF}@celebrations"

        lines.append("BEGIN:VEVENT")
        lines.append(f"SUMMARY:{sanitize(msg)}")
        lines.append(f"DTSTART;VALUE=DATE:{date.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{(date + timedelta(days=1)).strftime('%Y%m%d')}")
        lines.append(f"UID:{uid}")
        lines.append("STATUS:CONFIRMED")

        if person and isinstance(person, dict):
            hint = person.get("hint")
            desc_lines = [f"{person['name']} ({hint})" if hint else person['name']]
            for extra_event in extras:
                extra_msg = extra_event[0]
                if isinstance(extra_msg, str):
                    desc_lines.append(sanitize(extra_msg))
            desc = "\\n".join(desc_lines)
            lines.append(f"DESCRIPTION:{desc}")

        lines.append("END:VEVENT")
        count += 1

    # Add final reminder to re-export — only for fixed date-range exports
    if days_ahead is not None:
        today = get_today()
        final_date = today + timedelta(days=days_ahead)
        final_label = "🔁 Time to re-export Celebrations iCal!"
        uid = f"{final_date.strftime('%Y%m%d')}-99999@celebrations"
        lines.extend([
            "BEGIN:VEVENT",
            f"SUMMARY:{sanitize(final_label)}",
            f"DTSTART;VALUE=DATE:{final_date.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(final_date + timedelta(days=1)).strftime('%Y%m%d')}",
            f"UID:{uid}",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ])

    # Always close the calendar
    lines.append("END:VCALENDAR")

    return "\n".join(lines), count

def get_monthly_budget_output(
    name=None,
    date=None,
    months_ahead=1,
    tenant=None,
    config_path=None,
):
    path, _anniversary_path = resolve_config_paths(
        birthdays_path=config_path,
        tenant=tenant,
    )
    data = load_birthdays(path)

    if isinstance(date, str):
        try:
            date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return [f"❌ Invalid date format: {date}. Please use YYYY-MM-DD."]

    if months_ahead < 1:
        return ["❌ Monthly budget range must be at least 1 month."]

    today = date or get_today()
    tenant_label = tenant_display_name(tenant) if tenant else None

    matches = []
    if name:
        matches = [person for person in data if name.lower() in person["name"].lower()]
        if not matches:
            return [f"No match found for '{name}'"]

    people = matches if matches else data
    budget_birthdays = upcoming_budget_birthdays(people, today, months_ahead=months_ahead)

    if not budget_birthdays:
        if months_ahead == 1:
            return ["💸 No upcoming birthdays remain in this month."]
        return [f"💸 No upcoming birthdays found in the next {months_ahead} months."]

    if name and len(matches) == 1:
        header = f"💸 Monthly birthday budget heads-up for {matches[0]['name']}:\n"
    elif months_ahead == 1:
        subject = f" for {tenant_label}" if tenant_label else ""
        header = f"💸 Monthly birthday budget heads-up{subject} for the rest of this month:\n"
    else:
        subject = f" for {tenant_label}" if tenant_label else ""
        header = f"💸 Monthly birthday budget heads-up{subject} for the next {months_ahead} months:\n"

    messages = [header]
    current_month = None

    for birthday_date, person, age in budget_birthdays:
        month_label = birthday_date.strftime("%B %Y")
        if month_label != current_month:
            messages.append("")
            messages.append(f"📅 {month_label}")
            current_month = month_label

        display_name = person["name"]
        if person.get("hint"):
            display_name = f"{display_name} ({person['hint']})"

        messages.append(
            f"🎂 {birthday_date.strftime('%a')} {birthday_date.day} - {display_name} turns {age}"
        )

    return messages

def get_celebration_output(
    name=None,
    date=None,
    days_ahead=0,
    markup=False,
    ical_mode=False,
    tenant=None,
    config_path=None,
    anniversaries_path=None,
):
    """
    Shared logic for CLI and GUI to get celebration output.
    Returns (messages: list of strings, tuples: raw event tuples)
    """

    path, anniversary_path = resolve_config_paths(
        birthdays_path=config_path,
        anniversaries_path=anniversaries_path,
        tenant=tenant,
    )
    data = load_all_celebrations(path, anniversary_path)

    if isinstance(date, str):
        try:
            date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return [f"❌ Invalid date format: {date}. Please use YYYY-MM-DD."], []

    today = get_today()
    tenant_label = tenant_display_name(tenant) if tenant else None

    date = date or today
    messages = []
    results = []

    # Name filtering
    matches = []
    if name:
        matches = [p for p in data if name.lower() in p["name"].lower()]
        if not matches:
            return [f"No match found for '{name}'"], []

        if len(matches) > 1 and not days_ahead and date == today:
            # Only warn on ambiguous name if no further filtering is supplied
            names = "\n".join(f" - {p['name']}" for p in matches)
            return [f"Multiple matches:\n{names}"], []

    people = matches if matches else data

    # 📅 UPCOMING
    if days_ahead > 0:
        results = upcoming_celebrations(people, date, days_ahead=days_ahead)
        name_label = f" for {people[0]['name']}" if name and len(matches) == 1 else ""
        tenant_subject = f" in {tenant_label}" if tenant_label and not name_label else ""
        header = f"🎈 Upcoming celebrations{tenant_subject} in the next {days_ahead} days{name_label}:\n"
        messages.append(header)
        messages += extract_messages(results, category_filter=("date_header", "label", "celebration"), markup=markup)
        return messages, results

    # 🧠 NAME-ONLY: pull milestone dates and group output
    if name and len(matches) == 1 and date == today:
        person = matches[0]
        milestone_dates = upcoming_milestone_dates_for(person, today)
        results = calculate_all_celebrations([person], milestone_dates)

        if ical_mode:
            return [], results  # Skip pretty messages for iCal mode

        # Group by date
        grouped = defaultdict(list)
        for tup in results:
            _msg, dt, _, category = tup
            if category in ("label", "celebration"):
                grouped[dt].append(tup)

        if person.get("entry_type") == "anniversary":
            messages.append(f"🔍 Upcoming Milestones for {person['name']}, celebrated from {person['date']}:\n")
        else:
            messages.append(f"🔍 Upcoming Milestones for {person['name']}, born {person['birthdate']}:\n")
        for dt in sorted(grouped):
            messages.append(f"\n📅 {dt}")
            entries = extract_messages(grouped[dt], markup=markup)
            messages.extend(entries)
        return messages, results

    # 🗓️ DATE (+ optional name filter)
    results = calculate_all_celebrations(people, date)
    messages = extract_messages(results, category_filter=("date_header", "label", "celebration"), markup=markup)

    if name and matches:
        header = f"🔍 Celebrations on {date} for {matches[0]['name']}:\n"
        messages.insert(0, header)
    elif date != today:
        subject = f" for {tenant_label}" if tenant_label else ""
        messages.insert(0, f"🔍 Celebrations on {date}{subject}:\n")
    else:
        subject = f" ({tenant_label})" if tenant_label else ""
        messages.insert(0, f"🎉 Today's Celebrations{subject}:\n")

    return messages, results
