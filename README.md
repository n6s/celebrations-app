TO DO:

KNOWN ISSUES/LIMITATIONS:
* Android soft keyboard quirks (Gboard / gesture typing not supported).
* Emojis fail to render in app, but works in Copy and iCal export, and in CLI.

DONE:
* Add interactive CLI support for `--add-anniversary`
* Add wedding anniversary support via ~/.config/celebrations/anniversaries.json and shared CLI/iCal output
* Add tenant-aware CLI support via `--tenant`, using ~/.config/celebrations/tenants/<tenant>/
* Move notifier and systemd templates into the repo, with install script and example tenant env files
* Add Upcoming Celebrations Button
* Person Lookup
* Date lookup, filter by person
* Data Editor / Entry Form
* Android Deployment
* Add Export Config button to copy birthdays.json to /sdcard/Download
* add a Toast or Popup like “Copied config to /Download for external editing” before launching the intent
* Fix bug for app crash when using Open Config
* Waste enormous time and energy splitting code.
* Get Import Config to work for once and for all.
* Desktop version stable
* Fix crash on Add: Guard against invalid or empty data before calling calculate_celebrations.
* Fix Upcoming screen blank: Investigate why calculate_celebrations() returns nothing.
* Display error popups on bad/missing birthdates in Add screen, instead of letting invalid records get saved.
* Fix narrow text column layout in scroll views.
* Fix past date lookup bug: e.g., unsupported operand type(s) for %: 'NoneType' and 'int' from CLI/GUI.
* Fix Export Config behavior: Add confirmation popup and verify file copy worked.
* Add refresh/reload after Import Config: Reload birthdays.json data and update the view dynamically.
* Fix soft keyboard issue: Ensure form fields remain visible.
* Fix height of fields and buttons on Add screen.
* Fix height of fields and buttons on Lookup screen.
* Fix height of buttons on Today screen.
* Fix height of fields and buttons on Lookup screen.
* Import and Export config confirmation message should fit the screen.
* Keep CLI + GUI celebration logic in sync
* Add feedback for Copy action.
* Upcoming Screen = 365 Days by Default
* In Upcoming, Add Third Button: 📤 Export iCal.
* Add a Nickname field to the Add screen.
* Refactor celebrations to output a tuple to make iCal export less buggy.
* Patch ~/bin/celebrations.py to leverage the new tuples for --upcoming
* Revisit export_ical_file() to leverage the new tuples
* iCal Export Notes, eg. "Export Complete ✅\n📅 celebrations.ics saved to /Download\n✔️ Birthdays repeat every year\n⚠️ Other events included only for the next 365 days"
* Remove repeating logic to fix celebrating same age yearly.
* Append a final hurrah to the iCal letting them know its time to re-export.
* On Upcoming screen let user choose how many days to show/export.
* iCal export confirmation message should match number of upcoming days specified.
* Wider ical confirmation popup on android
* Put the hint variable into the iCal notes field, eg. "Tim's son"
* Only export celebrations to ICS, not date headers, not labels
* Major rewrite to add category to celebrations for finer output control needed for iCal.
* Add newline before group labels in Lookup by date
* Create slimmed down celebrations.py CLI tool that simply imports functions from celebrations_core.py
* Add --ical flag to CLI
* Add --today alias to CLI
* Add -v shorthand for --version
* Smarter error handling for bad --date inputs
* Pretty-print group labels in blue (or gendered colors)
* Add header to Lookup screen
* Put a header row on screens, eg. "🎉 Today's Celebrations", "📅 Upcoming - Next 365 Days", "🔍 Lookup - Search by name, date, or both", "➕ Add a New Birthday"
* Back button should return to main/Today screen instead of exit.
* Improve iCal export: show primary celebration in SUMMARY, move extras to DESCRIPTION
* Android: Automatically launches share intent after .ics export, allowing users to send calendar files via email, Drive, etc.
* Test long-range exports: Learn not to exceed 500 events for Google Calendar
* Refactored GUI iCal export to use shared generate_ical_text() function from utils.py, eliminating duplicated logic.
* iCal Export: Show warning when exporting over 500 events (Google Calendar import limit)
* Go down the rabbit hole to find a font that renders emojis in Kivy and failing.
* Clean up celebrations_core.py with help from pylint.
* Go down the rabbit hole for hours trying to get iCal export to share the file to an email draft and failed and gave up.
* Replaced next_milestones_for() with a unique-date generator to enable milestone lookups to flow through calculate_celebrations(), unifying output and supporting .ics export.
* Updated calculate_celebrations() to support date lists, unifying logic across single and multi-day views.
* Refactored name-only lookup in CLI and GUI to use milestone dates, enabling full celebration details with dates.
* Added date_header entries to milestone outputs for better readability and .ics export compatibility.
* Unified name-only lookup with .ics export logic, ensuring rich, accurate calendar output and avoiding special-case handling.
* Improved .ics export confirmation messaging to reflect actual export range and avoid misleading reminders.
* Added "Days Ahead" field and "Reset" button to the Lookup screen to unify interface with Upcoming screen.
* Rewrote Lookup logic to route through upcoming_celebrations() when Days > 0, allowing combined name/date filters.
* Ensured self.lookup_results is populated for all lookup types, enabling Copy and Export iCal support.
* Grouped Lookup results by date header with newline for readability.
* Avoided duplicate date headers in multi-date views (no longer inserts [2025-04-05] + 2025-04-05).
* Fixed issue where “Time to re-export iCal” reminder was added even for name-only or fixed-date exports.
* Lookup screen: Combine Days Ahead + Name
* Restore pretty markup and colors in name-only and multi-day Lookup results.
* Unified CLI and GUI output through get_celebration_output() for DRY celebration logic across name, date, and upcoming filters.
* Fix Android Lookup screen — now loads birthdays correctly and filters as expected.
* Add realistic CLI --test mode — uses live upcoming data to validate name/date lookups.
* Add bottom-row buttons to Lookup screen in preparation for promotion to new homepage.
* Debug Android specific Lookup screen quirks ahead of homepage cutover.
* Create new problems by changing function names in calls without updating actual function names. Revert those changes after endless frustration. Swear off any new function name changes until code cleanup after stable.
* Test all use cases on the unified screen — Confirms no regressions (Today, Name, Date, Days Ahead, combos).
* Auto-fill today’s date and run lookup on entry — Mimics Today screen behavior without extra UI.
* Make Lookup the default screen — It already does everything; no need for a separate Today screen.
* Remove Today and Upcoming screens — They're redundant now; Lookup handles all cases.
* Fix back button behavior on Add screen so it returns to the new lookup screen instead of the removed today screen.
* Replace Today button on Add screen now that Today screen is removed.
* Remove switch_to_today() from lookup.py

Repo-managed notifier files:
* Canonical notifier script: `scripts/celebration-notifier.sh`
* Monthly budget notifier script: `scripts/monthly-budget-notifier.sh`
* User systemd templates: `deploy/systemd/celebration-notifier.service` and `deploy/systemd/celebration-notifier.timer`
* Monthly budget systemd templates: `deploy/systemd/celebration-budget-notifier.service` and `deploy/systemd/celebration-budget-notifier.timer`
* Installer: `scripts/install-user-files.sh [symlink|copy]`
* Example tenant notifier config: `config/tenants/<tenant>/notifier.env.example`

Recommended local deployment split:
* Symlink or copy the script and systemd units from the repo into `~/bin` and `~/.config/systemd/user`
* Keep real `notifier.env`, `birthdays.json`, and `anniversaries.json` under `~/.config/celebrations/tenants/`
* Do not commit real tenant data or bot tokens
