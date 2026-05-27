#!/usr/bin/env python3
# pylint: disable=line-too-long,missing-function-docstring,too-many-locals,too-many-branches,too-many-statements
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Add celebrations-app/ to path

def main():
    from celebrations_core import (get_today,
                                   all_entries_for_tenant,
                                   create_anniversary_entry,
                                   create_birthday_entry,
                                   delete_entry_by_id,
                                   find_entry_by_id,
                                   load_all_celebrations, load_anniversaries,
                                   load_birthdays,
                                   resolve_config_paths,
                                   save_birthdays)
    from utils import generate_ical_text, get_celebration_output, get_monthly_budget_output

    parser = argparse.ArgumentParser(description="Celebrate birthdays, anniversaries, monthdays, and centusdays!")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--tenant", type=str, help="Use tenant-specific data from ~/.config/celebrations/tenants/<tenant>/")
    parser.add_argument("--file", type=str)
    parser.add_argument("--anniversaries-file", type=str)
    parser.add_argument("--add", action="store_true")
    parser.add_argument("--add-anniversary", action="store_true")
    parser.add_argument("--date", type=str)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--upcoming", nargs="?", const=4, type=int)
    parser.add_argument(
        "--monthly-budget",
        nargs="?",
        const=1,
        type=int,
        help="Show upcoming birthdays remaining this month, or across N months, for budgeting",
    )
    parser.add_argument("--name", type=str)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--ical", action="store_true", help="Export upcoming milestones to an iCal file")
    parser.add_argument("--today", action="store_true", help="Show today’s celebrations (default behavior)")
    parser.add_argument("-v", "--version", action="store_true", help="Show version info")
    parser.add_argument("--test", action="store_true", help="Run internal celebration tests")

    args = parser.parse_args()

    filepath, anniversaries_filepath = resolve_config_paths(
        birthdays_path=args.file,
        anniversaries_path=args.anniversaries_file,
        tenant=args.tenant,
    )
    data = load_birthdays(filepath)

    if args.add and args.add_anniversary:
        print("❌ Choose either --add or --add-anniversary, not both.")
        return

    if args.test:
        print("🧪 Running test mode...\n")

        today = get_today()

        def _run_fixture_crud_checks():
            tenant = {
                "id": "tenant-fixture",
                "name": "Fixture Tenant",
                "birthdays": [],
                "anniversaries": [],
            }
            print("🧪 Fixture CRUD checks (in-memory):")
            birthday = create_birthday_entry(tenant, "Fixture Birthday", "1999-01-02", hint="fixture")
            anniversary = create_anniversary_entry(
                tenant,
                "Fixture Anniversary",
                "2010-04-15",
                kind="wedding_anniversary",
                hint="fixture",
            )

            found_birthday = find_entry_by_id(tenant, birthday["id"])
            found_anniversary = find_entry_by_id(tenant, anniversary["id"])
            if not (found_birthday and found_anniversary):
                print("❌ Fixture find failed.")
                return False

            print(f"✅ Added/found entries: {birthday['id']} + {anniversary['id']}")

            delete_entry_by_id(tenant, birthday["id"])
            delete_entry_by_id(tenant, anniversary["id"])
            if all_entries_for_tenant(tenant):
                print("❌ Fixture cleanup failed.")
                return False
            print("✅ Fixture CRUD checks passed.")
            return True

        if not _run_fixture_crud_checks():
            sys.exit(1)

        # Step 1: Pull actual upcoming data to find a real celebration
        _, upcoming = get_celebration_output(
            days_ahead=366,
            tenant=args.tenant,
            config_path=filepath,
            anniversaries_path=anniversaries_filepath,
        )
        sample = next((t for t in upcoming if t[-1] == "celebration"), None)

        if not sample:
            print("❌ No upcoming celebrations in the next year. Try adding some test data.")
            return

        _, sample_date, sample_person, _ = sample
        sample_name = sample_person["name"]
        sample_days = (sample_date - today).days

        # Define test cases with CLI-style headers
        test_cases = [
            (f"$ celebrations.py --date {sample_date}", {"date": sample_date}),
            (f'$ celebrations.py --name "{sample_name}"', {"name": sample_name}),
            (f'$ celebrations.py --upcoming {sample_days} --name "{sample_name}"', {"name": sample_name, "days_ahead": sample_days}),
            (f'$ celebrations.py --date {sample_date} --name "{sample_name}"', {"name": sample_name, "date": sample_date}),
        ]

        for cli_command, kwargs in test_cases:
            print("========================================")
            print(cli_command)
            messages, _ = get_celebration_output(
                tenant=args.tenant,
                config_path=filepath,
                anniversaries_path=anniversaries_filepath,
                **kwargs,
            )
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
        filepath.parent.mkdir(parents=True, exist_ok=True)
        anniversaries_filepath.parent.mkdir(parents=True, exist_ok=True)
        created = []
        if not filepath.exists():
            example_data = [
                {"name": "Example Name", "birthdate": "2000-01-01", "hint": "Sample hint", "gender": "f"},
                {"name": "Centus Test", "birthdate": "2024-12-16"}
            ]
            save_birthdays(example_data, filepath)
            created.append(filepath)
        if not anniversaries_filepath.exists():
            anniversary_data = [
                {
                    "name": "Example Couple",
                    "date": "2015-06-20",
                    "kind": "wedding_anniversary",
                    "short_name": "Example Couple",
                }
            ]
            save_birthdays(anniversary_data, anniversaries_filepath)
            created.append(anniversaries_filepath)
        if created:
            for created_path in created:
                print(f"Initialized config with example data at {created_path}")
        else:
            print(f"Configs already exist at {filepath} and {anniversaries_filepath}")
        return

    if args.add:
        print("Interactive birthday entry mode:")
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

    if args.add_anniversary:
        print("Interactive anniversary entry mode:")
        name = input("Couple or celebration name: ").strip()
        anniversary_date = input("Date (YYYY-MM-DD): ").strip()
        short_name = input("Short name (optional): ").strip()
        hint = input("Hint (optional): ").strip()
        kind = input("Kind [wedding_anniversary]: ").strip() or "wedding_anniversary"

        entry = {"name": name, "date": anniversary_date, "kind": kind}
        if short_name:
            entry["short_name"] = short_name
        if hint:
            entry["hint"] = hint

        anniversaries = load_anniversaries(anniversaries_filepath)
        anniversaries.append(entry)
        save_birthdays(anniversaries, anniversaries_filepath)
        print(f"Added anniversary for {entry['name']}")
        return

    if args.all:
        for row in load_all_celebrations(filepath, anniversaries_filepath):
            print(row)
        return

    # For iCal Export
    if args.ical:
        messages, event_tuples = get_celebration_output(
            name=args.name,
            date=args.date,
            days_ahead=args.upcoming or 0,
            markup=False,
            ical_mode=True,
            tenant=args.tenant,
            config_path=filepath,
            anniversaries_path=anniversaries_filepath,
        )
        if not event_tuples:
            print("No upcoming celebrations to export.")
        else:
            ical_text, count = generate_ical_text(event_tuples, days_ahead=args.upcoming)
            with open("celebrations.ics", "w", encoding="utf-8") as f:
                f.write(ical_text)
            print(f"✅ Exported {count} events to celebrations.ics")
        sys.exit(0)

    if args.monthly_budget is not None:
        messages = get_monthly_budget_output(
            name=args.name,
            date=args.date,
            months_ahead=args.monthly_budget,
            tenant=args.tenant,
            config_path=filepath,
        )
        print("\n".join(messages))
        return

    # Otherwise, show results in terminal
    messages, _ = get_celebration_output(
        name=args.name,
        date=args.date,
        days_ahead=args.upcoming or 0,
        markup=False,
        tenant=args.tenant,
        config_path=filepath,
        anniversaries_path=anniversaries_filepath,
    )
    print("\n".join(messages))

if __name__ == "__main__":
    main()
