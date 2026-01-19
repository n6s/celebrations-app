#!/usr/bin/env python3
# pylint: disable=line-too-long,missing-function-docstring,too-many-locals,too-many-branches,too-many-statements
import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Add celebrations-app/ to path

from celebrations_core import (calculate_celebrations, get_today,
                               load_birthdays, save_birthdays,
                               upcoming_celebrations,
                               upcoming_milestone_dates_for)
from utils import extract_messages, generate_ical_text, get_celebration_output

CONFIG_PATH = Path.home() / ".config/celebrations/birthdays.json"

def main():
    parser = argparse.ArgumentParser(description="Celebrate birthdays, monthdays, and centusdays!")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--file", type=str)
    parser.add_argument("--add", action="store_true")
    parser.add_argument("--date", type=str)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--upcoming", nargs="?", const=4, type=int)
    parser.add_argument("--name", type=str)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--ical", action="store_true", help="Export upcoming milestones to an iCal file")
    parser.add_argument("--today", action="store_true", help="Show today’s celebrations (default behavior)")
    parser.add_argument("-v", "--version", action="store_true", help="Show version info")
    parser.add_argument("--test", action="store_true", help="Run internal celebration tests")

    args = parser.parse_args()

    filepath = Path(args.file) if args.file else CONFIG_PATH
    data = load_birthdays(filepath)

    if args.test:
        print("🧪 Running test mode...\n")
    
        data = load_birthdays(CONFIG_PATH)
        today = get_today()
    
        # Step 1: Pull actual upcoming data to find a real celebration
        _, upcoming = get_celebration_output(days_ahead=4, config_path=CONFIG_PATH)
        sample = next((t for t in upcoming if t[-1] == "celebration"), None)
    
        if not sample:
            print("❌ No upcoming celebrations in next 4 days. Try adding some test data.")
            return
    
        msg, sample_date, sample_person, _ = sample
        sample_name = sample_person["name"]
    
        # Define test cases with CLI-style headers
        test_cases = [
            ("$ celebrations.py", dict(date=today)),
            (f'$ celebrations.py --name "{sample_name}"', dict(name=sample_name)),
            (f'$ celebrations.py --upcoming 4 --name "{sample_name}"', dict(name=sample_name, days_ahead=4)),
            (f'$ celebrations.py --date {sample_date} --name "{sample_name}"', dict(name=sample_name, date=sample_date)),
        ]
    
        for cli_command, kwargs in test_cases:
            print("========================================")
            print(cli_command)
            messages, _ = get_celebration_output(config_path=CONFIG_PATH, **kwargs)
            print("\n".join(messages))
            print()
    
        print("========================================")
        print("✅ Test complete — all outputs above should contain real celebrations.\n")
        return

    if args.version:
        print("celebrations.py version 1.0.0")
        return

    try:
        today = get_today(args.date)
    except ValueError:
        print("❌ Invalid date format. Please use YYYY-MM-DD (e.g., 2024-10-31).")
        print("   You can also omit --date to use today’s date automatically.")
        return


    if args.init:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not filepath.exists():
            example_data = [
                {"name": "Example Name", "birthdate": "2000-01-01", "hint": "Sample hint", "gender": "f"},
                {"name": "Centus Test", "birthdate": "2024-12-16"}
            ]
            save_birthdays(example_data, filepath)
            print(f"Initialized config with example data at {filepath}")
        else:
            print(f"Config already exists at {filepath}")
        return

    if args.add:
        print("Interactive entry mode:")
        name = input("Name: ").strip()
        nickname = input("Nickname: ").strip()
        birthdate = input("Birthdate (YYYY-MM-DD): ").strip()
        hint = input("Hint (optional): ").strip()
        gender = input("Gender (m/f, optional): ").strip().lower()
        nonhuman = input("Is nonhuman? (y/N): ").strip().lower() == 'y'
        deceased = input("Is deceased? (y/N): ").strip().lower() == 'y'

        entry = {"name": name, "birthdate": birthdate}
        if hint:
            entry["hint"] = hint
        if nickname:
            entry["nickname"] = nickname
        if gender in ['m', 'f']:
            entry["gender"] = gender
        if nonhuman:
            entry["nonhuman"] = True
        if deceased:
            entry["deceased"] = True
        data.append(entry)
        save_birthdays(data, filepath)
        print(f"Added entry for {entry['name']}")
        return

    # For iCal Export
    if args.ical:
        messages, event_tuples = get_celebration_output(
            name=args.name,
            date=args.date,
            days_ahead=args.upcoming or 0,
            markup=False,
            ical_mode=True,
            config_path=filepath
        )
        if not event_tuples:
            print("No upcoming celebrations to export.")
        else:
            ical_text, count = generate_ical_text(event_tuples, days_ahead=args.upcoming)
            with open("celebrations.ics", "w", encoding="utf-8") as f:
                f.write(ical_text)
            print(f"✅ Exported {count} events to celebrations.ics")
        sys.exit(0)
    
    # Otherwise, show results in terminal
    messages, _ = get_celebration_output(
        name=args.name,
        date=args.date,
        days_ahead=args.upcoming or 0,
        markup=False,
        config_path=filepath
    )
    print("\n".join(messages))
    return

    if args.all:
        for row in data:
            print(row)

if __name__ == "__main__":
    main()
