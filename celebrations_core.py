# celebrations_core.py
"""
Track and celebrate personal milestones based on birthdates.
Supports birthdays, centusdays (every 100 days), kilodays (every 1000 days),
monthday fractions (like half-birthdays), and life expectancy achievements.

Data is stored in ~/.config/celebrations/birthdays.json.

Intended for daily use via cron or systemd, optionally piping stdout to Telegram or similar.

Author: Roger 🧠🎉
"""

import json
import math
import sys
from calendar import monthrange
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from dateutil.relativedelta import relativedelta

LIFE_EXPECTANCY = {
    'm': 75.8,
    'f': 81.1
}
CONFIG_DIR = Path.home() / ".config/celebrations"
CONFIG_PATH = CONFIG_DIR / "birthdays.json"

# 📂 File and Config Helpers: load_birthdays, save_birthdays, get_today

def load_birthdays(path):
    if not path.exists():
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)

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

def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

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

# Shared Fraction Mapping
fraction_map = {3: '¼', 4: '⅓', 6: '½', 8: '⅔', 9: '¾'}
fraction_labels = {
    3: "Quarter Birthday", 9: "Quarter Birthday",
    4: "One-Third Birthday", 8: "Two-Thirds Birthday",
    6: "Half-Birthday"
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
                            person_messages[label].append(f"💸 Half-Birthday Check-in! If {shortname} starts investing ${abs(invest_per_month):,.2f} a month (or a one-time investment of ${one_time:,.2f}) at 15% annualized return for the next {years_to_go} years until age 59½ ({months_to_59_5} months), it could be worth $1,000,000! 🙃 But 15% is a stretch, and $1M only pays ~$40K/year. DYORDCAHODLFTW. 😎🧠💰🪙📈⏳🚀🌕")
                        except Exception:
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

    def _braille_char(byte): return chr(0x2800 + byte) if byte else "⠀"
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

    for frac_months in fraction_map:
        next_frac_month = ((age_months // 12) + 1) * 12 + frac_months
        milestone_date = fractional_month_anniversary(birthdate, next_frac_month)
        milestone_year = next_frac_month // 12
        label = f"📆 {milestone_year}{fraction_map[frac_months]} {fraction_labels.get(frac_months, 'Fractional Birthday')}"
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
        future_msgs = calculate_celebrations(data, future)
        if future_msgs:
            upcoming.append(("📅 [{}]".format(future.isoformat()), future, None, "date_header"))
            for item in future_msgs:
                if isinstance(item, tuple) and len(item) == 4:
                    upcoming.append(item)
                else:
                    # Log or skip malformed entries
                    print(f"[WARN] Skipping malformed celebration item: {item}")
    return upcoming

def today_celebrations(data, today):
    base = calculate_celebrations(data, today)
    return base if base else []

def upcoming_milestone_dates_for(person, today):
    """
    Return a list of upcoming celebration dates for a person.
    These will later be passed to `calculate_celebrations()`.
    """
    from datetime import timedelta

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
    this_year = safe_monthday(today.year, birthdate.month, birthdate.day)
    next_birthday = this_year if this_year >= today else safe_monthday(today.year + 1, birthdate.month, birthdate.day)
    dates.add(next_birthday)

    # 💯 Centusday
    next_centus = ((age_days // 100) + 1) * 100
    dates.add(birthdate + timedelta(days=next_centus))

    # 🏆 Kiloday
    next_kiloday = ((age_days // 1000) + 1) * 1000
    dates.add(birthdate + timedelta(days=next_kiloday))

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
    milestone_hours, milestone_date, _ = hour_milestone_info(birthdate, today)
    if milestone_date > today:
        dates.add(milestone_date)

    return sorted(dates)

def upcoming_milestone_celebrations(person, today, limit=20):
    milestones = next_milestones_for(person, today)
    results = []
    for label, date in milestones[:limit]:
        date_str = date.strftime("%Y-%m-%d")
        message = f"{date_str} – {label}"
        results.append((message, date, person, "celebration"))
    return results
