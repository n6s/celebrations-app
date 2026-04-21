# celebrations_core.py
"""
Track and celebrate personal milestones based on birthdates and anniversaries.
Supports birthdays, anniversaries, centusdays (every 100 days), kilodays
(every 1000 days), monthday fractions (like half-birthdays), and life
expectancy achievements.

Data is stored in ~/.config/celebrations/birthdays.json and anniversaries.json,
or in tenant-specific files under ~/.config/celebrations/tenants/<tenant>/.

Intended for daily use via cron or systemd, optionally piping stdout to Telegram or similar.

Author: Roger 🧠🎉
"""

import json
import math
import os
from calendar import monthrange
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from dateutil.relativedelta import relativedelta

LIFE_EXPECTANCY = {
    'm': 75.8,
    'f': 81.1
}
XDG_CONFIG_ROOT = Path(os.environ["XDG_CONFIG_HOME"]) if os.environ.get("XDG_CONFIG_HOME") else Path.home() / ".config"
CONFIG_DIR = XDG_CONFIG_ROOT / "celebrations"
CONFIG_PATH = CONFIG_DIR / "birthdays.json"
ANNIVERSARIES_PATH = CONFIG_DIR / "anniversaries.json"
TENANTS_DIR = CONFIG_DIR / "tenants"
MIN_SEQUENCE_LENGTH = 4
MATH_CONSTANT_PREFIXES = {
    "Pi": ("🥧", "31415926535897932384626433832795"),
    "Euler's Number": ("📈", "27182818284590452353602874713526"),
    "Golden Ratio": ("🌀", "16180339887498948482045868343656"),
    "Tau": ("🔵", "62831853071795864769252867665590"),
    "Square Root of 2": ("📐", "14142135623730950488016887242097"),
}

# 📂 File and Config Helpers: load_birthdays, load_anniversaries, save_birthdays, get_today

def load_json_entries(path):
    if not path.exists():
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def load_birthdays(path):
    return load_json_entries(path)

def load_anniversaries(path):
    return load_json_entries(path)

def normalize_tenant_name(tenant):
    if tenant is None:
        return None
    tenant_name = tenant.strip()
    return tenant_name or None

def tenant_config_dir(tenant):
    tenant_name = normalize_tenant_name(tenant)
    return TENANTS_DIR / tenant_name if tenant_name else CONFIG_DIR

def resolve_config_paths(birthdays_path=None, anniversaries_path=None, tenant=None):
    tenant_name = normalize_tenant_name(tenant)
    if birthdays_path:
        resolved_birthdays = Path(birthdays_path)
    elif tenant_name:
        resolved_birthdays = tenant_config_dir(tenant_name) / "birthdays.json"
    else:
        resolved_birthdays = CONFIG_PATH

    if anniversaries_path:
        resolved_anniversaries = Path(anniversaries_path)
    elif tenant_name:
        resolved_anniversaries = tenant_config_dir(tenant_name) / "anniversaries.json"
    else:
        resolved_anniversaries = ANNIVERSARIES_PATH

    return resolved_birthdays, resolved_anniversaries

def normalize_birthdays(data):
    return [{**entry, "entry_type": "birthday"} for entry in data]

def normalize_anniversaries(data):
    normalized = []
    for entry in data:
        name = (entry.get("name") or entry.get("couple_name") or "").strip()
        anniversary_date = entry.get("date") or entry.get("married_date")
        if not name or not anniversary_date:
            continue

        normalized_entry = {**entry}
        normalized_entry["name"] = name
        normalized_entry["date"] = anniversary_date
        normalized_entry["entry_type"] = "anniversary"
        normalized_entry["kind"] = normalized_entry.get("kind") or (
            "wedding_anniversary" if "married_date" in entry else "anniversary"
        )
        normalized.append(normalized_entry)
    return normalized

def load_all_celebrations(birthdays_path=None, anniversaries_path=None):
    resolved_birthdays, resolved_anniversaries = resolve_config_paths(
        birthdays_path=birthdays_path,
        anniversaries_path=anniversaries_path,
    )
    birthdays = normalize_birthdays(load_birthdays(resolved_birthdays))
    anniversaries = normalize_anniversaries(load_anniversaries(resolved_anniversaries))
    return birthdays + anniversaries

def save_birthdays(data, path):
    timestamp = datetime.now().strftime("%s")
    backup_path = path.with_name(path.name + f".{timestamp}")
    if path.exists():
        path.replace(backup_path)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def get_today(override_date=None):
    return datetime.strptime(override_date, "%Y-%m-%d").date() if override_date else datetime.today().date()

# 🗖️ Date Calculations

def month_window_end(start_date, months_ahead=1):
    if months_ahead < 1:
        raise ValueError("months_ahead must be at least 1")

    final_month = start_date.replace(day=1) + relativedelta(months=+(months_ahead - 1))
    last_day = monthrange(final_month.year, final_month.month)[1]
    return final_month.replace(day=last_day)

def fractional_month_anniversary(birthdate, months):
    target_date = birthdate + relativedelta(months=+months)
    day = min(birthdate.day, monthrange(target_date.year, target_date.month)[1])
    return target_date.replace(day=day)

def is_fractional_monthday(birthdate, today, age_months=None):
    if today < birthdate:
        return (False, None, None)

    if age_months is None:
        age_months = (today.year - birthdate.year) * 12 + (today.month - birthdate.month)

    expected_date = fractional_month_anniversary(birthdate, age_months)
    if today != expected_date:
        return (False, None, None)

    age_years = age_months // 12
    remainder_months = age_months % 12
    return (True, age_years, remainder_months)

def safe_monthday(year, month, day):
    try:
        return datetime(year, month, day).date()
    except ValueError:
        next_month = datetime(year, month % 12 + 1, 1)
        return (next_month - timedelta(days=1)).date()

def next_birthday_date(birthdate, today):
    this_year = safe_monthday(today.year, birthdate.month, birthdate.day)
    return this_year if this_year >= today else safe_monthday(today.year + 1, birthdate.month, birthdate.day)

def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

def celebration_sort_key(item):
    _, target_date, person, category = item
    category_order = {"label": 0, "celebration": 1}
    name = ""
    if isinstance(person, dict):
        name = person.get("name", "").lower()
    return (target_date, name, category_order.get(category, 99))

def merge_celebration_results(*result_sets):
    merged = []
    for result_set in result_sets:
        merged.extend(result_set)
    return sorted(merged, key=celebration_sort_key)

def get_percent_life_milestones(expectancy_years, max_percent=150):
    return {
        p: round(expectancy_years * 365.25 * p / 100)
        for p in range(101, max_percent + 1)
    }
PERCENT_MILESTONES = {
    g: get_percent_life_milestones(years)
    for g, years in LIFE_EXPECTANCY.items()
}

def should_include_investment_projection(age_years, age_remainder_months, gender, nonhuman, deceased):
    return (
        age_remainder_months == 6 and
        not nonhuman and
        not deceased and
        gender in ("m", "f") and
        age_years < 59
    )

def calculate_investment_projection(months_left, rate=0.15, target=1_000_000):
    monthly_investment = -1 * round((rate / 12 * target) / ((1 + rate / 12) ** months_left - 1), 2)
    lump_sum = round(target / ((1 + rate / 12) ** months_left), 2)
    return monthly_investment, lump_sum

def generate_sequence_milestones(min_length=MIN_SEQUENCE_LENGTH, max_length=7):
    milestones = []
    for length in range(min_length, max_length + 1):
        ascending = ''.join(str(digit) for digit in range(1, length + 1))
        descending = ''.join(str(digit) for digit in range(length, 0, -1))
        milestones.append((int(ascending), "Ascending Number Sequence"))
        milestones.append((int(descending), "Descending Number Sequence"))
    return sorted(milestones)

def generate_constant_day_milestones(min_length=4, max_length=6):
    milestones = []
    for label, (emoji, digits) in MATH_CONSTANT_PREFIXES.items():
        for length in range(min_length, max_length + 1):
            prefix_value = int(digits[:length])
            milestones.append((prefix_value, label, emoji, digits[:length]))
    return sorted(milestones)

SEQUENCE_DAY_MILESTONES = generate_sequence_milestones()
CONSTANT_DAY_MILESTONES = generate_constant_day_milestones()

def get_number_sequence_milestone(days_old):
    for milestone_day, label in SEQUENCE_DAY_MILESTONES:
        if milestone_day == days_old:
            return milestone_day, label
    return None

def get_constant_day_milestones(days_old):
    return [
        (milestone_day, label, emoji, prefix)
        for milestone_day, label, emoji, prefix in CONSTANT_DAY_MILESTONES
        if milestone_day == days_old
    ]

def next_sequence_day_milestones(days_old):
    upcoming = []
    seen_labels = set()
    for milestone_day, label in SEQUENCE_DAY_MILESTONES:
        if milestone_day > days_old and label not in seen_labels:
            upcoming.append((milestone_day, label))
            seen_labels.add(label)
    return upcoming

def next_constant_day_milestones(days_old):
    next_days = []
    seen_labels = set()
    for milestone_day, label, emoji, prefix in CONSTANT_DAY_MILESTONES:
        if milestone_day > days_old and label not in seen_labels:
            next_days.append((milestone_day, label, emoji, prefix))
            seen_labels.add(label)
    return next_days

# Shared Fraction Mapping
fraction_map = {3: '¼', 4: '⅓', 6: '½', 8: '⅔', 9: '¾'}
fraction_labels = {
    3: "Quarter Birthday", 9: "Quarter Birthday",
    4: "One-Third Birthday", 8: "Two-Thirds Birthday",
    6: "Half-Birthday"
}
ANNIVERSARY_LABELS = {
    "anniversary": "Anniversary",
    "wedding_anniversary": "Wedding Anniversary",
}
ANNIVERSARY_MILESTONES = {
    25: "Silver",
    50: "Golden",
    60: "Diamond",
}

# 🎉 Celebration Engines: calculate_celebrations, braille_life_line, lifespan_bar

def calculate_age_months(birthdate, today):
    """Calculate age in months, accounting for end-of-month birthdays."""
    if today < birthdate:
        return 0

    months_diff = (today.year - birthdate.year) * 12 + (today.month - birthdate.month)
    anniv_day = min(birthdate.day, monthrange(today.year, today.month)[1])
    if today.day < anniv_day:
        months_diff -= 1
    return months_diff

def is_centusmonthiversary(birthdate, today):
    months = calculate_age_months(birthdate, today)
    if months % 100 != 0 or months == 0:
        return False, None
    milestone_date = fractional_month_anniversary(birthdate, months)
    return today == milestone_date, months

def calculate_celebrations(data, target_dates):
    if not isinstance(target_dates, list):
        target_dates = [target_dates]

    results = []

    for target_date in target_dates:
        person_messages = defaultdict(list)
        person_lookup = {}

        for person in data:
            if not person.get("birthdate"):
                continue
            name = person['name']
            nickname = person.get('nickname', '').strip()
            shortname = nickname if nickname else name.split()[0]
            hint = person.get('hint', '')
            birthdate = datetime.strptime(person['birthdate'], "%Y-%m-%d").date()
            gender = (person.get("gender") or "").lower()
            gender_key = gender[:1]
            nonhuman = person.get('nonhuman', False)
            deceased = person.get('deceased', False)
            days_old = (target_date - birthdate).days
            age_months = calculate_age_months(birthdate, target_date)
            age_years = age_months // 12
            age_remainder_months = age_months % 12
            age_decimal = round(age_years + age_remainder_months / 12, 5)
            expectancy = LIFE_EXPECTANCY.get(gender_key)
            label = f"{name} ({hint})" if hint else f"{name}"
            person_lookup[label] = person

            is_birthday = birthdate.month == target_date.month and birthdate.day == target_date.day
            is_kiloday = days_old % 1000 == 0
            is_centusday = days_old % 100 == 0 and not is_kiloday
            is_monthday, age_years, remainder_months = is_fractional_monthday(birthdate, target_date)
            sequence_day = get_number_sequence_milestone(days_old)
            constant_days = get_constant_day_milestones(days_old)

            if deceased:
                if is_birthday:
                    person_messages[label].append(f"🎂 {shortname} would have been {age_years} years old today. Happy Heavenly Birthday!")
            else:
                if is_birthday:
                    person_messages[label].append(f"🎂 Happy {ordinal(age_years)} Birthday, {shortname}!")
                if is_monthday and remainder_months in fraction_map:
                    frac_str = fraction_map[remainder_months]
                    frac_label = fraction_labels.get(remainder_months, "Fractional Birthday")
                    person_messages[label].append(f"📆 Happy {age_years}{frac_str} {frac_label}, {shortname}!")
                    if remainder_months == 6 and should_include_investment_projection(age_years, remainder_months, gender, nonhuman, deceased):
                        try:
                            months_to_59_5 = max(0, int((59.5 * 12) - age_months))
                            invest_per_month, one_time = calculate_investment_projection(months_to_59_5)
                            years_to_go = round(months_to_59_5 / 12)
                            person_messages[label].append(f"💸 Half-Birthday Check-in! If {shortname} starts investing ${abs(invest_per_month):,.2f} a month (or a one-time investment of ${one_time:,.2f}) at 15% annualized return for the next {years_to_go} years until age 59½ ({months_to_59_5} months), it could be worth $1,000,000! 🙃 But 15% is a stretch, and even a 4% retirement withdrawal from $1M is only about $40K/year. Not a financial advisor. DYORDCAHODLFTW. 😎🧠💰🪙📈⏳🚀🌕")
                        except (OverflowError, ZeroDivisionError):
                            pass
                if is_centusday:
                    ordinal_num = ordinal(days_old // 100)
                    person_messages[label].append(f"💯 Happy {ordinal_num} Centusday ({days_old:,} days), {shortname}!")
                if is_kiloday:
                    kilo_count = days_old // 1000
                    centus_count = days_old // 100
                    centus_bar = "💯" * centus_count
                    ordinal_num = ordinal(kilo_count)
                    person_messages[label].append(f"🏆 Happy {ordinal_num} Kiloday ({days_old:,} days), {shortname}!")
                    person_messages[label].append(f"{shortname}'s life in {centus_count} Centusdays: {centus_bar}")
                if sequence_day:
                    _, sequence_label = sequence_day
                    person_messages[label].append(
                        f"🔢 Happy {sequence_label} ({days_old:,} days), {shortname}!"
                    )
                for _, constant_label, constant_emoji, prefix in constant_days:
                    person_messages[label].append(
                        f"{constant_emoji} Happy {constant_label} milestone: {prefix} days for {shortname}!"
                    )
                if not nonhuman:
                    milestones = PERCENT_MILESTONES.get(gender_key, {})
                    for percent, day in milestones.items():
                        if days_old == day and percent > 100:
                            progress_bar = lifespan_bar(percent)
                            a_lot = " by a lot" if percent >= 110 else ""
                            gender_label = "female" if gender == "f" else "male"
                            person_messages[label].append(f"🎯 At {age_decimal:.2f} years old, {shortname} has exceeded {expectancy:.1f}-year {gender_label} life expectancy{a_lot}! {progress_bar}")
                            person_messages[label].append("  🏅 Lifespan Exceeded: Achievement unlocked — Immortal Wanderer")
                            break
                weeks_old = days_old // 7
                if days_old % 700 == 0:
                    braille = braille_life_line(days_old)
                    centusweek_num = weeks_old // 100
                    person_messages[label].append(f"🧱 Centusweek {centusweek_num} unlocked — {weeks_old:,} weeks of {shortname}!")
                    person_messages[label].append(f"{shortname}'s life in {weeks_old:,} weeks: {braille}")

                # 🌟 Kilomonthiversary
                kilomonth_day = round((1000 / 12) * 365.25)
                if days_old == kilomonth_day:
                    person_messages[label].append(f"🌟 Happy once-in-a-lifetime Kilomonthiversary (1,000 months), {shortname}!")

                # 📅 Centusmonthiversary
                is_cm, months = is_centusmonthiversary(birthdate, target_date)
                if is_cm:
                    milestone_num = months // 100
                    person_messages[label].append(
                        f"📅 Happy {ordinal(milestone_num)} Centusmonthiversary ({months:,} months), {shortname}!"
                    )

                # 🕰️ Hour milestone
                milestone_hours, milestone_date, _ = hour_milestone_info(birthdate, target_date)
                if milestone_date == target_date:
                    person_messages[label].append(f"🕰️  {shortname} just logged {milestone_hours:,} lifetime hours! Time well spent?")

        for label, entries in sorted(person_messages.items()):
            person = person_lookup.get(label)
            if person:
                label_text = f"{person['name']} ({person.get('hint')})..." if person.get("hint") else f"{person['name']}..."
                results.append((label_text, target_date, person, "label"))
            for msg in entries:
                results.append((msg, target_date, person, "celebration"))

    return results

def anniversary_kind_label(entry):
    return ANNIVERSARY_LABELS.get(entry.get("kind"), "Anniversary")

def anniversary_short_name(entry):
    return (entry.get("short_name") or entry.get("name") or "").strip()

def anniversary_display_label(entry):
    hint = (entry.get("hint") or "").strip()
    name = entry["name"]
    return f"{name} ({hint})" if hint else name

def calculate_anniversary_celebrations(data, target_dates):
    if not isinstance(target_dates, list):
        target_dates = [target_dates]

    results = []

    for target_date in target_dates:
        anniversary_messages = defaultdict(list)
        anniversary_lookup = {}

        for entry in data:
            if entry.get("entry_type") != "anniversary":
                continue

            date_text = entry.get("date")
            if not date_text:
                continue

            anniversary_date = datetime.strptime(date_text, "%Y-%m-%d").date()
            if target_date < anniversary_date:
                continue

            observed_date = safe_monthday(target_date.year, anniversary_date.month, anniversary_date.day)
            years = target_date.year - anniversary_date.year
            if target_date != observed_date or years < 1:
                continue

            label = anniversary_display_label(entry)
            anniversary_lookup[label] = entry
            short_name = anniversary_short_name(entry)
            anniversary_type = anniversary_kind_label(entry)
            anniversary_messages[label].append(
                f"💍 Happy {ordinal(years)} {anniversary_type}, {short_name}!"
            )

            if years % 5 == 0:
                milestone_name = ANNIVERSARY_MILESTONES.get(years)
                if milestone_name:
                    anniversary_messages[label].append(
                        f"✨ {milestone_name} {anniversary_type} milestone!"
                    )
                else:
                    anniversary_messages[label].append(
                        f"✨ Milestone {anniversary_type}: {years} years!"
                    )

        for label, entries in sorted(anniversary_messages.items()):
            entry = anniversary_lookup.get(label)
            if entry:
                label_text = f"{entry['name']} ({entry.get('hint')})..." if entry.get("hint") else f"{entry['name']}..."
                results.append((label_text, target_date, entry, "label"))
            for msg in entries:
                results.append((msg, target_date, entry, "celebration"))

    return results

def calculate_all_celebrations(data, target_dates):
    birthdays = calculate_celebrations(data, target_dates)
    anniversaries = calculate_anniversary_celebrations(data, target_dates)
    return merge_celebration_results(birthdays, anniversaries)

def braille_life_line(days_old):
    """
    Convert age in days into a visual braille life timeline.
    Each cell represents 8 weeks. Raised dots mark passed weeks.
    """
    weeks_old = days_old // 7
    num_cells = math.ceil(weeks_old / 8)
    dots = [0] * num_cells

    for i in range(weeks_old):
        cell = i // 8
        dot = i % 8
        dots[cell] |= (1 << dot)

    def _braille_char(byte):
        return chr(0x2800 + byte) if byte else "⠀"

    return ''.join(_braille_char(b) for b in dots)

def lifespan_bar(percent, width=20):
    normal = min(percent, 100)
    overflow = max(0, percent - 100)

    filled_blocks = int((normal / 100) * width)
    extra_blocks = max(1, int((overflow / 100) * width)) if overflow > 0 else 0
    empty_blocks = width - filled_blocks

    progress_bar = "🟩" * filled_blocks + "⬜" * empty_blocks
    extra = "🟥" * extra_blocks + (" 💥" if overflow >= 10 else "")
    return f"[{progress_bar}]{extra} {percent}%"

def next_milestones_for(person, today):
    """
    Calculate the next milestone dates for a given person, including:
    - Birthday
    - Centusday (every 100 days)
    - Kiloday (every 1000 days)
    - Quarter/Third/Half Birthday
    - Investment Half-Birthday
    - Lifespan percent progress (past 100%)
    - Braille brick (every 700 days / 100 weeks)
    """
    birthdate = datetime.strptime(person['birthdate'], "%Y-%m-%d").date()
    gender = (person.get('gender') or '').lower()
    gender_key = gender[:1]
    nonhuman = person.get('nonhuman', False)
    deceased = person.get('deceased', False)
    milestones = []

    days_old = (today - birthdate).days
    age_months = calculate_age_months(birthdate, today)
    age_years = age_months // 12


    # 🎂 Birthday
    this_year = safe_monthday(today.year, birthdate.month, birthdate.day)
    next_birthday = this_year if this_year >= today else safe_monthday(today.year + 1, birthdate.month, birthdate.day)
    age_at_next = next_birthday.year - birthdate.year
    milestones.append((f"🎂 {ordinal(age_at_next)} Birthday", next_birthday))

    # 💯 Centusday
    next_centus = ((days_old // 100) + 1) * 100
    next_centus_date = birthdate + timedelta(days=next_centus)
    milestones.append((f"💯 {ordinal(next_centus // 100)} Centusday ({next_centus:,} days)", next_centus_date))

    # 🏆 Kiloday
    next_kiloday = ((days_old // 1000) + 1) * 1000
    next_kiloday_date = birthdate + timedelta(days=next_kiloday)
    milestones.append((f"🏆 {ordinal(next_kiloday // 1000)} Kiloday ({next_kiloday:,} days)", next_kiloday_date))

    # 🔢 Number Sequences
    for milestone_day, label in next_sequence_day_milestones(days_old):
        milestones.append((f"🔢 {label} ({milestone_day:,} days)", birthdate + timedelta(days=milestone_day)))

    # 🧮 Mathematical Constants
    for milestone_day, label, emoji, prefix in next_constant_day_milestones(days_old):
        milestones.append((f"{emoji} {label} milestone ({prefix} days)", birthdate + timedelta(days=milestone_day)))

    for frac_months, fraction_symbol in fraction_map.items():
        next_frac_month = ((age_months // 12) + 1) * 12 + frac_months
        milestone_date = fractional_month_anniversary(birthdate, next_frac_month)
        milestone_year = next_frac_month // 12
        label = f"📆 {milestone_year}{fraction_symbol} {fraction_labels.get(frac_months, 'Fractional Birthday')}"
        milestones.append((label, milestone_date))

        # 💸 Investment Check-in only on Half Birthday
        if frac_months == 6 and should_include_investment_projection(age_years, 6, gender, nonhuman, deceased):
            milestones.append(("💸 Investment Check-in", milestone_date))

    # 🧱 Braille Brick (every 700 days = 100 weeks)
    next_braille = ((days_old // 700) + 1) * 700
    braille_date = birthdate + timedelta(days=next_braille)
    weeks_total = next_braille // 7
    milestones.append((f"🧱 {ordinal(weeks_total // 100)} Centusweek ({weeks_total:,} weeks)", braille_date))

    # 🎯 Lifespan Progress Bar
    if gender_key in ("m", "f"):
        for pct, day in sorted(PERCENT_MILESTONES.get(gender_key, {}).items()):
            if pct > 100 and day > days_old:
                date = birthdate + timedelta(days=day)
                expectancy = LIFE_EXPECTANCY[gender_key]
                milestones.append((f"🎯 {pct}% Lifespan ({pct * expectancy / 100:.2f}/{expectancy:.1f})", date))
                break

    # 📅 Hundred-Monthiversaries
    next_100_month = ((age_months // 100) + 1) * 100
    next_100_month_date = fractional_month_anniversary(birthdate, next_100_month)
    milestones.append((f"📅 {ordinal(next_100_month // 100)} Centusmonthiversary ({next_100_month:,} months)", next_100_month_date))

    # 🌟 1000-Month Milestone (once-in-a-lifetime)
    if age_months < 1000:
        thousand_month_date = birthdate + timedelta(days=round((1000 / 12) * 365.25))
        milestones.append(("🌟 1st and only Kilomonthiversary (1,000 months)", thousand_month_date))

    # 🎯 Celebrate every 10,000 hours (but only if upcoming)
    milestone_hours, milestone_date, _ = hour_milestone_info(birthdate, today)
    if milestone_date > today:
        milestones.append((f"🕰️  ~{milestone_hours:,} hours milestone", milestone_date))

    return sorted(milestones, key=lambda tup: tup[1])

def upcoming_anniversary_milestone_dates_for(entry, today):
    anniversary_date = datetime.strptime(entry.get("date"), "%Y-%m-%d").date()
    if today < anniversary_date:
        return [anniversary_date]

    dates = set()
    this_year = safe_monthday(today.year, anniversary_date.month, anniversary_date.day)
    next_anniversary = this_year if this_year >= today else safe_monthday(
        today.year + 1, anniversary_date.month, anniversary_date.day
    )
    dates.add(next_anniversary)

    next_years = max(1, next_anniversary.year - anniversary_date.year)
    next_milestone_years = ((max(next_years, 1) - 1) // 5 + 1) * 5
    milestone_date = safe_monthday(
        anniversary_date.year + next_milestone_years,
        anniversary_date.month,
        anniversary_date.day,
    )
    if milestone_date >= today:
        dates.add(milestone_date)

    return sorted(dates)

# 10,000 hours
def hour_milestone_info(birthdate, today, interval=10_000):
    days_old = (today - birthdate).days
    total_hours = days_old * 24
    milestone_hours = ((total_hours + (interval - 1)) // interval) * interval

    milestone_days = round(milestone_hours / 24)
    milestone_date = birthdate + timedelta(days=milestone_days)

    is_today = today == milestone_date
    return milestone_hours, milestone_date, is_today

# 🎮 CLI Functions: main, upcoming_celebrations

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
                else:
                    # Log or skip malformed entries
                    print(f"[WARN] Skipping malformed celebration item: {item}")
    return upcoming

def upcoming_budget_birthdays(data, today, months_ahead=1):
    end_date = month_window_end(today, months_ahead=months_ahead)
    upcoming = []

    for person in data:
        birthdate_text = person.get("birthdate")
        if not birthdate_text or person.get("deceased", False):
            continue

        birthdate = datetime.strptime(birthdate_text, "%Y-%m-%d").date()
        birthday_date = next_birthday_date(birthdate, today)
        if today <= birthday_date <= end_date:
            upcoming.append((birthday_date, person, birthday_date.year - birthdate.year))

    return sorted(upcoming, key=lambda item: (item[0], item[1].get("name", "").lower()))

def today_celebrations(data, today):
    base = calculate_all_celebrations(data, today)
    return base if base else []

def upcoming_birthday_milestone_dates_for(person, today):
    """
    Return a list of upcoming celebration dates for a person.
    These will later be passed to `calculate_celebrations()`.
    """
    birthdate = datetime.strptime(person.get("birthdate"), "%Y-%m-%d").date()
    if not birthdate:
        return []

    gender = (person.get('gender') or '').lower()
    gender_key = gender[:1]
    nonhuman = person.get('nonhuman', False)
    deceased = person.get('deceased', False)
    age_days = (today - birthdate).days
    age_months = calculate_age_months(birthdate, today)
    age_years = age_months // 12

    dates = set()

    # 🎂 Next Birthday
    next_birthday = next_birthday_date(birthdate, today)
    dates.add(next_birthday)

    # 💯 Centusday
    next_centus = ((age_days // 100) + 1) * 100
    dates.add(birthdate + timedelta(days=next_centus))

    # 🏆 Kiloday
    next_kiloday = ((age_days // 1000) + 1) * 1000
    dates.add(birthdate + timedelta(days=next_kiloday))

    # 🔢 Number Sequences
    for milestone_day, _ in next_sequence_day_milestones(age_days):
        dates.add(birthdate + timedelta(days=milestone_day))

    # 🧮 Mathematical Constants
    for milestone_day, _, _, _ in next_constant_day_milestones(age_days):
        dates.add(birthdate + timedelta(days=milestone_day))

    # 📆 Fractional birthdays (quarter/third/half)
    for frac_months in fraction_map:
        next_frac_month = ((age_months // 12) + 1) * 12 + frac_months
        dates.add(fractional_month_anniversary(birthdate, next_frac_month))

        # 💸 Investment check-in (only on half-birthdays)
        if frac_months == 6 and should_include_investment_projection(age_years, 6, gender, nonhuman, deceased):
            dates.add(fractional_month_anniversary(birthdate, next_frac_month))

    # 🧱 Braille Brick
    next_braille = ((age_days // 700) + 1) * 700
    dates.add(birthdate + timedelta(days=next_braille))

    # 🎯 Lifespan percent
    if gender_key in ("m", "f"):
        for pct, day in sorted(PERCENT_MILESTONES.get(gender_key, {}).items()):
            if pct > 100 and day > age_days:
                dates.add(birthdate + timedelta(days=day))
                break

    # 📅 Hundred-Month
    next_100_month = ((age_months // 100) + 1) * 100
    dates.add(fractional_month_anniversary(birthdate, next_100_month))

    # 🌟 1000-Month
    if age_months < 1000:
        dates.add(birthdate + timedelta(days=round((1000 / 12) * 365.25)))

    # 🕰️ 10,000 hour
    _, milestone_date, _ = hour_milestone_info(birthdate, today)
    if milestone_date > today:
        dates.add(milestone_date)

    return sorted(dates)

def upcoming_milestone_dates_for(person, today):
    if person.get("entry_type") == "anniversary":
        return upcoming_anniversary_milestone_dates_for(person, today)
    return upcoming_birthday_milestone_dates_for(person, today)

def upcoming_milestone_celebrations(person, today, limit=20):
    milestones = next_milestones_for(person, today)
    results = []
    for label, date in milestones[:limit]:
        date_str = date.strftime("%Y-%m-%d")
        message = f"{date_str} – {label}"
        results.append((message, date, person, "celebration"))
    return results
