# Repository Guidelines

## Project Structure & Module Organization
New development should start at `cli/celebrations.py`. That script is the primary entrypoint and wires CLI flags to shared logic in `celebrations_core.py` and `utils.py`. Keep date calculations, milestone rules, and JSON persistence in `celebrations_core.py`; keep output formatting and iCal generation in `utils.py`. The checked-in `birthdays.json` is sample data only. Real user data lives in `~/.config/celebrations/birthdays.json`. Kivy files such as `main.py`, `screens/`, `android_helpers.py`, and `buildozer.spec` are legacy support code and should not drive new feature design unless the task explicitly targets the old app.

## Build, Test, and Development Commands
Run the CLI directly:

```bash
python3 cli/celebrations.py
python3 cli/celebrations.py --date 2026-03-22
python3 cli/celebrations.py --upcoming 30 --name "Roger"
python3 cli/celebrations.py --ical --upcoming 30
```

Use `python3 cli/celebrations.py --test` for the project's built-in smoke test. Lint with:

```bash
python3 -m pylint cli/celebrations.py celebrations_core.py utils.py
```

Only use Buildozer commands when intentionally working on the legacy Android app.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, snake_case for functions and variables, and small focused helpers. Pylint is configured in `.pylintrc` with a 120-character line limit and several Kivy/Android exceptions already disabled; do not re-enable those as part of CLI work. Prefer extending shared helpers over duplicating business logic in the CLI.

## Testing Guidelines
There is no dedicated `tests/` directory yet, so every change should include a CLI validation pass. Exercise the exact flag path you changed, plus `--test` when possible. When fixing date logic, verify a concrete example date and include it in the PR notes.

## Commit & Pull Request Guidelines
Recent commits use short, imperative subjects such as `Fix fractional monthday duplicates on end-of-month`. Keep commits focused and descriptive. PRs should include a summary, sample commands run, and note any changes to JSON structure or generated output. Include screenshots only for legacy GUI work.

## Data & Artifacts
Do not commit personal birthday data, generated `celebrations.ics`, or APK artifacts from `bin/`.
