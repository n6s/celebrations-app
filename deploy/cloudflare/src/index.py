from __future__ import annotations

import copy
import hmac
import json
from collections import deque
from datetime import datetime, timezone
from json import JSONDecodeError
import uuid
import traceback
from urllib.parse import parse_qs, urlparse

from js import Object, fetch
from pyodide.ffi import to_js as _to_js
from workers import Response, WorkerEntrypoint

from celebrations_core import calculate_all_celebrations, get_today, upcoming_celebrations
from celebrations_core import (
    all_entries_for_tenant,
    create_anniversary_entry,
    create_birthday_entry,
    delete_entry_by_id,
    find_entry_by_id,
)


WEBHOOK_SECRET_HEADER = "x-telegram-bot-api-secret-token"
ADMIN_AUTH_HEADER = "authorization"
DEFAULT_UPCOMING_DAYS = 30
TELEGRAM_SEND_FAIL_MESSAGE = "⚠️ Message queued locally, but Telegram send failed."
REPLAY_TTL_SECONDS = 7 * 24 * 60 * 60
REPLAY_RETRY_WINDOW_SECONDS = 5 * 60
PENDING_DELETE_TTL_SECONDS = 7 * 24 * 60 * 60
PARTYMATH_DB_BINDING = "PARTYMATH_DB"
PARTYMATH_REPLAY_TABLE = "partymath_replays"
PARTYMATH_TENANTS_TABLE = "partymath_tenants"
PARTYMATH_ENTRIES_TABLE = "partymath_tenant_entries"
PARTYMATH_PENDING_DELETES_TABLE = "partymath_pending_deletes"
PARTYMATH_TENANT_MEMBERSHIPS_TABLE = "partymath_tenant_memberships"
PARTYMATH_CHAT_SETTINGS_TABLE = "partymath_chat_settings"
PARTYMATH_DELIVERY_LEDGER_TABLE = "partymath_delivery_ledger"
PARTYMATH_ENTRIES_TENANT_ID = "tenant_id"
PARTYMATH_ENTRIES_ID = "entry_id"
_SCHEMA_READY = False

BASE_TENANT_BIRTHDAYS = [
    {
        "id": "b-001",
        "entry_type": "birthday",
        "name": "Alex Dayley",
        "birthdate": "1990-10-12",
        "hint": "Demo record",
        "gender": "m",
    },
    {
        "id": "b-002",
        "entry_type": "birthday",
        "name": "Sam Example",
        "birthdate": "1988-03-02",
        "hint": "Demo record",
        "gender": "f",
    },
]

BASE_TENANT_ANNIVERSARIES = [
    {
        "id": "a-001",
        "entry_type": "anniversary",
        "name": "Alex and Sam",
        "date": "2015-06-19",
        "kind": "wedding_anniversary",
        "short_name": "Alex + Sam",
        "hint": "Demo record",
    }
]

BASE_TENANTS = {}
TENANT_CHAT_SETTINGS = {}
REPLAY_TRACKER = deque(maxlen=128)
REPLAY_SEEN = set()
PENDING_DELETES = {}

TENANT_LABELS = {
    "-1001111111111": "Demo Family Group",
    "1111111111": "Demo Private Chat",
}


def _json_response(payload: dict, status: int = 200) -> Response:
    return Response.json(payload, status=status)


def _to_js_object(value: dict):
    return _to_js(value, dict_converter=Object.fromEntries)


def _extract_update_type(update: dict) -> str:
    for key in (
        "message",
        "edited_message",
        "callback_query",
        "channel_post",
        "inline_query",
        "shipping_query",
        "pre_checkout_query",
        "poll",
        "poll_answer",
    ):
        if key in update:
            return key
    return "unknown"


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _db_key(value):
    if value is None:
        return None

    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            pass

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized or normalized.lower() in ("undefined", "none"):
            return None
        return normalized

    try:
        normalized = str(value).strip()
    except Exception:
        return None

    if not normalized or normalized.lower() in ("undefined", "none"):
        return None
    return normalized


def _db_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        if value.strip().lower() in ("undefined", "none"):
            return ""
        return value
    return str(value)


def _new_tenant(chat_id: int) -> dict:
    key = str(chat_id)
    label = _tenant_name_for_chat(key)
    return {
        "id": key,
        "name": label,
        "birthdays": copy.deepcopy(BASE_TENANT_BIRTHDAYS),
        "anniversaries": copy.deepcopy(BASE_TENANT_ANNIVERSARIES),
    }


def _tenant_name_for_chat(chat_key):
    return TENANT_LABELS.get(str(chat_key), f"Tenant Workspace {chat_key}")


def _get_db(env):
    return getattr(env, PARTYMATH_DB_BINDING, None)


def _row_value(row, key):
    if row is None:
        return None
    try:
        return row.get(key)
    except Exception:
        pass

    try:
        return row[key]
    except Exception:
        pass

    return getattr(row, key, None)


def _row_dict(row):
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        pass
    return {name: _row_value(row, name) for name in [
        "id",
        "name",
        "chat_id",
        "tenant_id",
        "tenant_name",
        "notify_hour",
        "notify_minute",
        "is_enabled",
        "entry_type",
        "entry_id",
        "birthdate",
        "date",
        "kind",
        "hint",
        "short_name",
    ]}


def _utc_datetime_from_epoch(value):
    epoch = _safe_int(value)
    if epoch is None:
        return None

    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def _notify_time_from_epoch(value):
    timestamp = _safe_int(value)
    when = _utc_datetime_from_epoch(timestamp) or datetime.now(timezone.utc)
    return when.hour, when.minute


def _now_utc_timestamp():
    return int(datetime.now(timezone.utc).timestamp())


def _delivery_date_for_now(now=None):
    return (now or datetime.now(timezone.utc)).date().isoformat()


async def _has_column(db, table_name, column_name):
    rows = await db.prepare(f"PRAGMA table_info({table_name})").all()
    for row in getattr(rows, "results", []):
        if _row_value(row, "name") == column_name:
            return True
    return False


async def _ensure_storage_schema_once(db):
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    await _ensure_storage_schema(db)
    _SCHEMA_READY = True


async def _ensure_storage_schema(db):
    pending_deletes_exists = await _has_column(db, PARTYMATH_PENDING_DELETES_TABLE, "chat_id")
    pending_deletes_has_tenant_id = await _has_column(
        db, PARTYMATH_PENDING_DELETES_TABLE, "tenant_id"
    )

    if pending_deletes_exists and not pending_deletes_has_tenant_id:
        await db.prepare(f"DROP TABLE {PARTYMATH_PENDING_DELETES_TABLE}").run()

    statements = [
        (
            f"CREATE TABLE IF NOT EXISTS {PARTYMATH_TENANTS_TABLE} ("
            "tenant_id TEXT PRIMARY KEY, "
            "tenant_name TEXT NOT NULL)"
        ),
        (
            f"CREATE TABLE IF NOT EXISTS {PARTYMATH_ENTRIES_TABLE} ("
            "tenant_id TEXT NOT NULL, "
            "entry_id TEXT NOT NULL, "
            "entry_type TEXT NOT NULL, "
            "name TEXT NOT NULL, "
            "birthdate TEXT, "
            "date TEXT, "
            "kind TEXT, "
            "hint TEXT, "
            "short_name TEXT, "
            "PRIMARY KEY (tenant_id, entry_id))"
        ),
        (
            f"CREATE TABLE IF NOT EXISTS {PARTYMATH_REPLAY_TABLE} ("
            "update_id INTEGER PRIMARY KEY, "
            "seen_at INTEGER NOT NULL)"
        ),
        (
            f"CREATE TABLE IF NOT EXISTS {PARTYMATH_PENDING_DELETES_TABLE} ("
            "chat_id TEXT NOT NULL, "
            "tenant_id TEXT NOT NULL, "
            "entry_id TEXT NOT NULL, "
            "requested_at INTEGER NOT NULL, "
            "PRIMARY KEY (chat_id, tenant_id))"
        ),
        (
            f"CREATE TABLE IF NOT EXISTS {PARTYMATH_TENANT_MEMBERSHIPS_TABLE} ("
            "chat_id TEXT NOT NULL, "
            "tenant_id TEXT NOT NULL, "
            "is_default INTEGER NOT NULL DEFAULT 0, "
            "created_at INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY (chat_id, tenant_id))"
        ),
        (
            f"CREATE TABLE IF NOT EXISTS {PARTYMATH_CHAT_SETTINGS_TABLE} ("
            "chat_id TEXT PRIMARY KEY, "
            "notify_hour INTEGER NOT NULL, "
            "notify_minute INTEGER NOT NULL, "
            "is_enabled INTEGER NOT NULL DEFAULT 1, "
            "created_at INTEGER NOT NULL, "
            "updated_at INTEGER NOT NULL)"
        ),
        (
            f"CREATE TABLE IF NOT EXISTS {PARTYMATH_DELIVERY_LEDGER_TABLE} ("
            "chat_id TEXT NOT NULL, "
            "tenant_id TEXT NOT NULL, "
            "delivery_date TEXT NOT NULL, "
            "sent_at INTEGER NOT NULL, "
            "success INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY (chat_id, tenant_id, delivery_date))"
        ),
        (
            f"CREATE INDEX IF NOT EXISTS idx_{PARTYMATH_TENANT_MEMBERSHIPS_TABLE}_chat"
            f" ON {PARTYMATH_TENANT_MEMBERSHIPS_TABLE}(chat_id)"
        ),
        (
            f"CREATE INDEX IF NOT EXISTS idx_{PARTYMATH_TENANT_MEMBERSHIPS_TABLE}_default "
            f"ON {PARTYMATH_TENANT_MEMBERSHIPS_TABLE}(chat_id, is_default)"
        ),
        (
            f"CREATE INDEX IF NOT EXISTS idx_{PARTYMATH_PENDING_DELETES_TABLE}_chat_tenant "
            f"ON {PARTYMATH_PENDING_DELETES_TABLE}(chat_id, tenant_id)"
        ),
        (
            f"CREATE INDEX IF NOT EXISTS idx_{PARTYMATH_CHAT_SETTINGS_TABLE}_due "
            f"ON {PARTYMATH_CHAT_SETTINGS_TABLE}(notify_hour, notify_minute, is_enabled)"
        ),
        (
            f"CREATE INDEX IF NOT EXISTS idx_{PARTYMATH_DELIVERY_LEDGER_TABLE}_lookup "
            f"ON {PARTYMATH_DELIVERY_LEDGER_TABLE}(chat_id, tenant_id, delivery_date)"
        ),
    ]
    for statement in statements:
        await db.prepare(statement).run()


def _entry_to_row(tenant_key, entry):
    entry_id = _db_key(entry.get("entry_id"))
    if entry_id is None:
        entry_id = _db_key(entry.get("id"))
    if entry_id is None:
        entry_id = str(uuid.uuid4())
    return {
        "tenant_id": tenant_key,
        "entry_id": entry_id,
        "entry_type": entry.get("entry_type"),
        "name": entry.get("name"),
        "birthdate": entry.get("birthdate"),
        "date": entry.get("date"),
        "kind": entry.get("kind"),
        "hint": entry.get("hint"),
        "short_name": entry.get("short_name"),
    }


def _row_to_entry(row):
    normalized = _row_dict(row)
    return {
        "id": normalized.get("entry_id"),
        "entry_type": normalized.get("entry_type"),
        "name": normalized.get("name"),
        "birthdate": normalized.get("birthdate"),
        "date": normalized.get("date"),
        "kind": normalized.get("kind"),
        "hint": normalized.get("hint"),
        "short_name": normalized.get("short_name"),
    }


async def _seed_tenant_defaults(db, tenant_key, tenant_name, include_default_entries=True):
    tenant_key = _db_key(tenant_key)
    if tenant_key is None:
        print("[partymath] _seed_tenant_defaults skipped because tenant_key is undefined")
        return
    tenant_name = _db_key(tenant_name) or f"Tenant {tenant_key}"

    await db.prepare(
        f"INSERT OR REPLACE INTO {PARTYMATH_TENANTS_TABLE}(tenant_id, tenant_name) "
        "VALUES(?1, ?2)"
    ).bind(tenant_key, tenant_name).run()

    if not include_default_entries:
        return

    entries = []
    for entry in BASE_TENANT_BIRTHDAYS + BASE_TENANT_ANNIVERSARIES:
        row = _entry_to_row(tenant_key, copy.deepcopy(entry))
        row["tenant_id"] = _db_key(row.get("tenant_id"))
        row["entry_id"] = _db_key(row.get("entry_id"))
        if (
            not row.get("tenant_id")
            or not row.get("entry_id")
            or not row.get("entry_type")
            or not row.get("name")
        ):
            print(
                f"[partymath] _seed_tenant_defaults skipping malformed tenant_id={row.get('tenant_id')} "
                f"entry_id={row.get('entry_id')}"
            )
            continue
        entries.append(row)

    for row in entries:
        await db.prepare(
            f"INSERT OR IGNORE INTO {PARTYMATH_ENTRIES_TABLE} "
            "(tenant_id, entry_id, entry_type, name, birthdate, date, kind, hint, short_name) "
            "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)"
        ).bind(
            row.get("tenant_id"),
            row.get("entry_id"),
            row.get("entry_type"),
            row.get("name"),
            _db_text(row.get("birthdate")),
            _db_text(row.get("date")),
            _db_text(row.get("kind")),
            _db_text(row.get("hint")),
            _db_text(row.get("short_name")),
        ).run()


def _chat_settings_key(chat_key):
    return str(chat_key)


def _chat_settings_for_memory(chat_key):
    return TENANT_CHAT_SETTINGS.get(_chat_settings_key(chat_key))


def _set_chat_settings_memory(chat_key, notify_hour, notify_minute):
    key = _chat_settings_key(chat_key)
    current = _chat_settings_for_memory(key)
    if current:
        return current

    now = _now_utc_timestamp()
    payload = {
        "chat_id": key,
        "notify_hour": notify_hour,
        "notify_minute": notify_minute,
        "is_enabled": 1,
        "created_at": now,
        "updated_at": now,
    }
    TENANT_CHAT_SETTINGS[key] = payload
    return payload


async def _chat_settings_from_db(db, chat_key):
    return await db.prepare(
        f"SELECT chat_id, notify_hour, notify_minute, is_enabled "
        f"FROM {PARTYMATH_CHAT_SETTINGS_TABLE} WHERE chat_id = ?1"
    ).bind(chat_key).first()


async def _set_default_chat_schedule_db(db, chat_key, message_timestamp=None):
    if chat_key is None:
        print("[partymath] _set_default_chat_schedule_db skipped because chat_key is None")
        return None

    existing = await _chat_settings_from_db(db, chat_key)
    if existing:
        return existing

    notify_hour, notify_minute = _notify_time_from_epoch(message_timestamp)
    if notify_hour is None or notify_minute is None:
        print(
            "[partymath] _set_default_chat_schedule_db missing schedule time "
            f"for chat_id={chat_key} message_timestamp={message_timestamp}"
        )
        return None

    now_ts = _now_utc_timestamp()
    if now_ts is None:
        now_ts = int(datetime.now().timestamp())

    await db.prepare(
        f"INSERT INTO {PARTYMATH_CHAT_SETTINGS_TABLE} "
        "(chat_id, notify_hour, notify_minute, is_enabled, created_at, updated_at) "
        "VALUES (?1, ?2, ?3, 1, ?4, ?4)"
    ).bind(chat_key, int(notify_hour), int(notify_minute), now_ts).run()
    return await _chat_settings_from_db(db, chat_key)


async def _ensure_chat_schedule(env, chat_key, message_timestamp=None):
    db = _get_db(env)
    if not db:
        notify_hour, notify_minute = _notify_time_from_epoch(message_timestamp)
        return _set_chat_settings_memory(chat_key, notify_hour, notify_minute)

    try:
        await _ensure_storage_schema_once(db)
        schedule = await _set_default_chat_schedule_db(db, chat_key, message_timestamp)
    except Exception as exc:
        print(
            f"[partymath] failed to ensure chat schedule for chat_id={chat_key}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None
    if schedule:
        return _row_dict(schedule)
    return None


async def _list_due_chat_tenant_rows(db, now):
    rows = await db.prepare(
        f"SELECT m.chat_id, m.tenant_id, t.tenant_name "
        f"FROM {PARTYMATH_TENANT_MEMBERSHIPS_TABLE} m "
        f"JOIN {PARTYMATH_CHAT_SETTINGS_TABLE} s ON s.chat_id = m.chat_id "
        f"LEFT JOIN {PARTYMATH_TENANTS_TABLE} t ON m.tenant_id = t.tenant_id "
        f"WHERE s.notify_hour = ?1 AND s.notify_minute = ?2 AND s.is_enabled = 1"
    ).bind(now.hour, now.minute).all()

    due = []
    for row in getattr(rows, "results", []):
        due.append({
            "chat_id": _row_value(row, "chat_id"),
            "tenant_id": _row_value(row, "tenant_id"),
            "tenant_name": _row_value(row, "tenant_name"),
        })
    return due


async def _has_delivered_today(db, chat_key, tenant_id, delivery_date):
    row = await db.prepare(
        f"SELECT 1 FROM {PARTYMATH_DELIVERY_LEDGER_TABLE} "
        "WHERE chat_id = ?1 AND tenant_id = ?2 AND delivery_date = ?3 AND success = 1"
    ).bind(chat_key, tenant_id, delivery_date).first()
    return row is not None


async def _mark_delivery(db, chat_key, tenant_id, delivery_date, success, sent_at=None):
    if sent_at is None:
        sent_at = _now_utc_timestamp()
    await db.prepare(
        f"INSERT INTO {PARTYMATH_DELIVERY_LEDGER_TABLE} "
        "(chat_id, tenant_id, delivery_date, sent_at, success) "
        "VALUES (?1, ?2, ?3, ?4, ?5) "
        "ON CONFLICT(chat_id, tenant_id, delivery_date) "
        "DO UPDATE SET sent_at = excluded.sent_at, success = excluded.success"
    ).bind(chat_key, tenant_id, delivery_date, sent_at, 1 if success else 0).run()


def _tenant_today_lines_for_date(tenant, target_date):
    all_entries = _all_entries(tenant)
    celebration_items = calculate_all_celebrations(all_entries, target_date)
    if not celebration_items:
        return []

    lines = [f"🎉 Today's celebrations for {tenant['name']} ({target_date}):"]
    lines.extend(_format_celebration_messages(celebration_items))
    return lines


async def _load_tenant_from_db(db, chat_key):
    tenant_key = _db_key(chat_key)
    if tenant_key is None:
        return None

    tenant_row = await db.prepare(
        f"SELECT tenant_name FROM {PARTYMATH_TENANTS_TABLE} WHERE tenant_id = ?1"
    ).bind(tenant_key).first()

    if not tenant_row:
        return None

    tenant_name = _row_value(tenant_row, "tenant_name")
    rows = await db.prepare(
        f"SELECT * FROM {PARTYMATH_ENTRIES_TABLE} WHERE tenant_id = ?1"
    ).bind(tenant_key).all()

    entries = [_row_to_entry(row) for row in rows.results] if getattr(rows, "results", None) else []

    birthdays = []
    anniversaries = []
    for entry in entries:
        if entry.get("entry_type") == "anniversary":
            anniversaries.append(entry)
        else:
            birthdays.append(entry)

    return {"id": chat_key, "name": tenant_name, "birthdays": birthdays, "anniversaries": anniversaries}


def _tenant_membership_key(chat_key, tenant_id):
    return f"{chat_key}:{tenant_id}"


async def _tenant_id_for_chat(db, chat_key):
    chat_key = _db_key(chat_key)
    if chat_key is None:
        print("[partymath] _tenant_id_for_chat skipped because chat_key is undefined")
        return None

    membership = await db.prepare(
        f"SELECT tenant_id FROM {PARTYMATH_TENANT_MEMBERSHIPS_TABLE} "
        f"WHERE chat_id = ?1 AND is_default = 1 LIMIT 1"
    ).bind(chat_key).first()
    if membership:
        tenant_id = _db_key(_row_value(membership, "tenant_id"))
        if tenant_id:
            return tenant_id

    fallback = await db.prepare(
        f"SELECT tenant_id FROM {PARTYMATH_TENANT_MEMBERSHIPS_TABLE} "
        f"WHERE chat_id = ?1 ORDER BY tenant_id LIMIT 1"
    ).bind(chat_key).first()
    if fallback:
        tenant_id = _db_key(_row_value(fallback, "tenant_id"))
        if tenant_id:
            await db.prepare(
                f"UPDATE {PARTYMATH_TENANT_MEMBERSHIPS_TABLE} "
                f"SET is_default = CASE WHEN tenant_id = ?2 THEN 1 ELSE 0 END "
                f"WHERE chat_id = ?1"
            ).bind(chat_key, tenant_id).run()
            return tenant_id

    tenant_id = chat_key
    await _seed_tenant_defaults(db, tenant_id, _tenant_name_for_chat(chat_key), include_default_entries=True)
    tenant_id = _db_key(tenant_id)
    if tenant_id is None:
        return None
    await db.prepare(
        f"INSERT OR REPLACE INTO {PARTYMATH_TENANT_MEMBERSHIPS_TABLE}"
        "(chat_id, tenant_id, is_default, created_at) VALUES (?1, ?2, 1, ?3)"
    ).bind(chat_key, tenant_id, int(datetime.now().timestamp())).run()
    return tenant_id


async def _create_tenant_record(db, tenant_name, include_default_entries=False):
    tenant_id = f"tenant_{uuid.uuid4().hex}"
    await _seed_tenant_defaults(db, tenant_id, tenant_name, include_default_entries=include_default_entries)
    tenant = await _load_tenant_from_db(db, tenant_id)
    if tenant is not None:
        return tenant

    return {
        "id": tenant_id,
        "name": tenant_name,
        "birthdays": [],
        "anniversaries": [],
    }


async def _attach_tenant_to_chat(db, chat_key, tenant_id, make_default=False):
    chat_key = _db_key(chat_key)
    tenant_id = _db_key(tenant_id)
    if chat_key is None or tenant_id is None:
        print(
            f"[partymath] _attach_tenant_to_chat skipped chat_id={chat_key} tenant_id={tenant_id}"
        )
        return

    await db.prepare(
        f"INSERT OR IGNORE INTO {PARTYMATH_TENANT_MEMBERSHIPS_TABLE}"
        "(chat_id, tenant_id, is_default, created_at) VALUES (?1, ?2, 0, ?3)"
    ).bind(chat_key, tenant_id, int(datetime.now().timestamp())).run()

    if make_default:
        await db.prepare(
            f"UPDATE {PARTYMATH_TENANT_MEMBERSHIPS_TABLE} SET is_default = 0 "
            f"WHERE chat_id = ?1"
        ).bind(chat_key).run()
        await db.prepare(
            f"UPDATE {PARTYMATH_TENANT_MEMBERSHIPS_TABLE} "
            f"SET is_default = 1 WHERE chat_id = ?1 AND tenant_id = ?2"
        ).bind(chat_key, tenant_id).run()


async def _set_default_tenant_for_chat(db, chat_key, tenant_id):
    chat_key = _db_key(chat_key)
    tenant_id = _db_key(tenant_id)
    if chat_key is None or tenant_id is None:
        print(
            f"[partymath] _set_default_tenant_for_chat skipped chat_id={chat_key} tenant_id={tenant_id}"
        )
        return False

    row = await db.prepare(
        f"SELECT tenant_id FROM {PARTYMATH_TENANTS_TABLE} WHERE tenant_id = ?1"
    ).bind(tenant_id).first()
    if not row:
        return False

    await _attach_tenant_to_chat(db, chat_key, tenant_id, make_default=True)
    return True


async def _list_chat_tenants(db, chat_key):
    chat_key = _db_key(chat_key)
    if chat_key is None:
        print("[partymath] _list_chat_tenants skipped because chat_key is undefined")
        return []

    rows = await db.prepare(
        f"SELECT m.tenant_id, m.is_default, t.tenant_name, "
        f"(SELECT COUNT(*) FROM {PARTYMATH_ENTRIES_TABLE} WHERE tenant_id = m.tenant_id) "
        f"AS entry_count "
        f"FROM {PARTYMATH_TENANT_MEMBERSHIPS_TABLE} m "
        f"LEFT JOIN {PARTYMATH_TENANTS_TABLE} t ON m.tenant_id = t.tenant_id "
        "WHERE m.chat_id = ?1 ORDER BY m.is_default DESC, m.tenant_id"
    ).bind(chat_key).all()
    tenants = []
    for row in getattr(rows, "results", []):
        tenant_id = _row_value(row, "tenant_id")
        tenants.append({
            "tenant_id": tenant_id,
            "tenant_name": _row_value(row, "tenant_name"),
            "is_default": bool(_row_value(row, "is_default")),
            "entry_count": _row_value(row, "entry_count") or 0,
        })
    return tenants


async def _save_entry_to_db(db, tenant_id, entry):
    row = _entry_to_row(tenant_id, entry)
    await db.prepare(
        f"INSERT OR REPLACE INTO {PARTYMATH_ENTRIES_TABLE} "
        "(tenant_id, entry_id, entry_type, name, birthdate, date, kind, hint, short_name) "
        "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)"
    ).bind(
        row.get("tenant_id"),
        row.get("entry_id"),
        row.get("entry_type"),
        row.get("name"),
        row.get("birthdate"),
        row.get("date"),
        row.get("kind"),
        row.get("hint"),
        row.get("short_name"),
    ).run()


async def _delete_entry_from_db(db, tenant_id, entry_id):
    await db.prepare(
        f"DELETE FROM {PARTYMATH_ENTRIES_TABLE} "
        f"WHERE tenant_id = ?1 AND entry_id = ?2"
    ).bind(tenant_id, entry_id).run()


def _tenant_for_chat_memory(chat_id: int) -> dict:
    key = str(chat_id)
    tenant = BASE_TENANTS.get(key)
    if tenant is None:
        tenant = _new_tenant(chat_id)
        BASE_TENANTS[key] = tenant
    return tenant


async def _tenant_for_chat(chat_id: int, env) -> dict:
    db = _get_db(env)
    if not db:
        return _tenant_for_chat_memory(chat_id)

    safe_chat_key = _db_key(chat_id)
    if safe_chat_key is None:
        print(f"[partymath] tenant lookup skipped, invalid chat_id={chat_id}")
        return _tenant_for_chat_memory(chat_id)

    try:
        await _ensure_storage_schema_once(db)
        chat_key = safe_chat_key
        tenant_id = await _tenant_id_for_chat(db, chat_key)
        if tenant_id is None:
            print(f"[partymath] tenant id missing after query for chat_id={chat_id}, using memory defaults")
            return _tenant_for_chat_memory(chat_id)

        tenant = await _load_tenant_from_db(db, tenant_id)
        if tenant is not None:
            return tenant

        tenant_name = _tenant_name_for_chat(chat_key)
        await _seed_tenant_defaults(db, tenant_id, tenant_name, include_default_entries=True)
        seeded = await _load_tenant_from_db(db, tenant_id)
        if seeded is not None:
            return seeded
    except Exception as exc:
        print(
            f"[partymath] tenant db path failed for chat_id={chat_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        print(f"[partymath] tenant db traceback: {traceback.format_exc()}")
        return _tenant_for_chat_memory(chat_id)

    return _tenant_for_chat_memory(chat_id)


def _all_entries(tenant: dict) -> list:
    return all_entries_for_tenant(tenant)


def _parse_command_and_args(text: str) -> tuple[str | None, str]:
    if not isinstance(text, str):
        return None, ""
    text = text.strip()
    if not text.startswith("/"):
        return None, ""

    parts = text.split(maxsplit=1)
    command_token = parts[0]
    args = parts[1].strip() if len(parts) > 1 else ""
    if "@" in command_token:
        command_token = command_token.split("@", 1)[0]
    return command_token[1:].lower(), args


def _extract_chat_and_text(update: dict) -> tuple[int | None, str | None, int | None]:
    if not isinstance(update, dict):
        return None, None, None

    for key in ("message", "edited_message", "channel_post"):
        payload = update.get(key)
        if isinstance(payload, dict):
            chat = payload.get("chat")
            if isinstance(chat, dict):
                return chat.get("id"), payload.get("text"), payload.get("date")

    if isinstance(update.get("callback_query"), dict):
        callback = update.get("callback_query")
        message = callback.get("message", {})
        if isinstance(message, dict):
            chat = message.get("chat")
            if isinstance(chat, dict):
                return chat.get("id"), callback.get("data"), message.get("date")
    return None, None, None


def _normalize_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _format_entry_line(entry: dict) -> str:
    entry_type = entry.get("entry_type", "birthday")
    if entry_type == "anniversary":
        icon = "💍"
        date_text = entry.get("date", "unknown")
        kind = entry.get("kind", "anniversary")
        suffix = f" • {kind}"
    else:
        icon = "🎂"
        date_text = entry.get("birthdate", "unknown")
        suffix = ""

    name = (entry.get("name") or "Unknown").strip()
    hint = entry.get("hint", "").strip()
    hint_text = f" ({hint})" if hint else ""
    return f"{icon} [{entry.get('id')}] {name}{hint_text}{suffix} — {date_text}"


def _format_celebration_messages(items: list) -> list[str]:
    lines = []
    for item in items:
        if not isinstance(item, tuple) or len(item) != 4:
            continue
        message, _date, _person, category = item
        if category in ("label", "date_header"):
            lines.append("")
        lines.append(str(message))
    return lines


def _handle_start():
    return {
        "text": (
            "🎉 Partymath is online.\n"
            "Commands:\n"
            "/tenant\n"
            "/tenant list\n"
            "/tenant create <name>\n"
            "/tenant use <tenant-id>\n"
            "/tenant default\n"
            "/today\n"
            "/upcoming [N]\n"
            "/list\n"
            "/find <name>\n"
            "/add birthday Name | YYYY-MM-DD | Hint\n"
            "/add anniversary Name | YYYY-MM-DD | Kind | Hint\n"
            "/delete <id>\n"
            "/delete <id> confirm"
        )
    }


def _message_for_list(tenant: dict):
    entries = _all_entries(tenant)
    if not entries:
        return {"text": f"📋 No celebrations configured for {tenant['name']}."}

    lines = [f"📋 Celebrations in {tenant['name']}:"]
    for entry in sorted(entries, key=lambda item: (item.get("entry_type", ""), item.get("name", "").lower())):
        lines.append(_format_entry_line(entry))
    return {"text": "\n".join(lines)}


def _message_for_find(tenant: dict, args: str):
    if not args:
        return {"text": "🔍 Usage: /find <name>"}

    query = args.lower()
    matches = []
    for entry in _all_entries(tenant):
        haystack = " ".join(
            filter(
                None,
                (
                    entry.get("name", ""),
                    entry.get("hint", ""),
                    entry.get("short_name", ""),
                    entry.get("kind", ""),
                ),
            )
        ).lower()
        if query in haystack:
            matches.append(entry)

    if not matches:
        return {"text": f"No matches found for '{args}'."}

    lines = [f"🔍 Matches for '{args}' in {tenant['name']}:"]
    for entry in sorted(matches, key=lambda item: item.get("name", "").lower()):
        lines.append(_format_entry_line(entry))
    return {"text": "\n".join(lines)}


def _message_for_tenant_today(tenant: dict, target_date=None):
    today = target_date or get_today()
    celebration_lines = _tenant_today_lines_for_date(tenant, today)
    if not celebration_lines:
        return {"text": f"🎉 No celebrations today for {tenant['name']}."}
    return {"text": "\n".join(celebration_lines)}


def _message_for_upcoming(tenant: dict, args: str):
    days = _safe_int(args) or DEFAULT_UPCOMING_DAYS
    if args and (not isinstance(days, int) or days < 1):
        return {"text": "⚠️ /upcoming expects a positive day count, e.g. /upcoming 7"}

    today = get_today()
    all_entries = _all_entries(tenant)
    celebration_items = upcoming_celebrations(all_entries, today, days_ahead=days)
    if not celebration_items:
        return {"text": f"📅 No celebrations in the next {days} days for {tenant['name']}."}

    lines = [f"📅 Upcoming celebrations in the next {days} days for {tenant['name']}:"]
    lines.extend(_format_celebration_messages(celebration_items))
    return {"text": "\n".join(lines)}


async def _message_for_add(env, tenant: dict, args: str):
    if not args:
        return {"text": "Use: /add birthday Name | YYYY-MM-DD | Hint"}

    subparts = args.split("|", maxsplit=1)
    if len(subparts) < 2:
        return {"text": "Use: /add birthday|anniversary Name | YYYY-MM-DD | ..."}

    subtype_and_name = subparts[0].strip()
    rest = [item.strip() for item in subparts[1].split("|")]
    subtype_parts = subtype_and_name.split(maxsplit=1)
    if not subtype_parts:
        return {"text": "Use: /add birthday Name | YYYY-MM-DD | Hint"}

    subtype = subtype_parts[0].lower()
    name = subtype_parts[1].strip() if len(subtype_parts) > 1 else ""
    if subtype not in ("birthday", "anniversary"):
        return {"text": "Unknown type. Use '/add birthday ...' or '/add anniversary ...'."}

    if not name or not rest:
        return {"text": f"Use: /add {subtype} Name | YYYY-MM-DD | Hint"}

    event_date = rest[0]
    if not _normalize_date(event_date):
        return {"text": "Date must be YYYY-MM-DD."}

    if subtype == "birthday":
        entry = create_birthday_entry(tenant, name, event_date, rest[1] if len(rest) > 1 else None)
        db = _get_db(env)
        if db:
            await _ensure_storage_schema_once(db)
            await _save_entry_to_db(db, tenant["id"], entry)
        return {"text": f"✅ Added birthday '{name}' with id {entry['id']} for {tenant['name']}."}

    kind = rest[1] if len(rest) > 1 and rest[1] else "wedding_anniversary"
    entry = create_anniversary_entry(
        tenant,
        name,
        event_date,
        kind=kind,
        hint=rest[2] if len(rest) > 2 else None,
    )
    db = _get_db(env)
    if db:
        await _ensure_storage_schema_once(db)
        await _save_entry_to_db(db, tenant["id"], entry)
    return {"text": f"✅ Added anniversary '{name}' with id {entry['id']} for {tenant['name']}."}


async def _is_duplicate_update_db(db, update_id: int | None) -> bool:
    if update_id is None:
        return False

    now_ts = int(datetime.now().timestamp())

    await db.prepare(
        f"DELETE FROM {PARTYMATH_REPLAY_TABLE} WHERE seen_at < ?1"
    ).bind(now_ts - REPLAY_TTL_SECONDS).run()

    row = await db.prepare(
        f"SELECT update_id, seen_at FROM {PARTYMATH_REPLAY_TABLE} WHERE update_id = ?1"
    ).bind(update_id).first()
    if not row:
        return False

    seen_at = _safe_int(_row_value(row, "seen_at")) or now_ts
    if now_ts - seen_at <= REPLAY_RETRY_WINDOW_SECONDS:
        print(
            f"[partymath] duplicate update suppressed update_id={update_id} "
            f"age_seconds={max(0, now_ts - seen_at)}"
        )
        return True

    await db.prepare(
        f"DELETE FROM {PARTYMATH_REPLAY_TABLE} WHERE update_id = ?1"
    ).bind(update_id).run()
    print(f"[partymath] cleared stale replay row for update_id={update_id}")
    return False


async def _mark_update_seen_db(db, update_id: int | None) -> None:
    if update_id is None:
        return

    await db.prepare(
        f"INSERT INTO {PARTYMATH_REPLAY_TABLE}(update_id, seen_at) VALUES (?1, ?2)"
    ).bind(update_id, int(datetime.now().timestamp())).run()


async def _mark_update_seen(env, update_id):
    db = _get_db(env)
    print(
        f"[partymath] mark_update_seen using "
        f"{'d1' if db else 'memory'} for update_id={update_id}"
    )
    if not db:
        _mark_update_seen_memory(update_id)
        return
    await _ensure_storage_schema_once(db)
    await _mark_update_seen_db(db, update_id)


def _mark_update_seen_memory(update_id):
    if update_id is None:
        return

    _cleanup_update_ids_memory()
    REPLAY_SEEN.add(update_id)
    REPLAY_TRACKER.append(update_id)


def _is_duplicate_update_memory(update_id: int | None) -> bool:
    if update_id is None:
        return False

    _cleanup_update_ids_memory()
    return update_id in REPLAY_SEEN


async def _is_duplicate_update(env, update_id: int | None) -> bool:
    db = _get_db(env)
    print(f"[partymath] is_duplicate_update using {'d1' if db else 'memory'} for update_id={update_id}")
    if not db:
        return _is_duplicate_update_memory(update_id)
    await _ensure_storage_schema_once(db)
    return await _is_duplicate_update_db(db, update_id)


async def _clear_replays_db(db, update_id=None, older_than_seconds=None, clear_all=False):
    if clear_all:
        await db.prepare(f"DELETE FROM {PARTYMATH_REPLAY_TABLE}").run()
        return {"action": "clear_all"}

    if update_id is not None:
        await db.prepare(
            f"DELETE FROM {PARTYMATH_REPLAY_TABLE} WHERE update_id = ?1"
        ).bind(update_id).run()
        return {"action": "clear_by_update_id", "update_id": update_id}

    if older_than_seconds is not None:
        cutoff = int(datetime.now().timestamp()) - older_than_seconds
        await db.prepare(
            f"DELETE FROM {PARTYMATH_REPLAY_TABLE} WHERE seen_at < ?1"
        ).bind(cutoff).run()
        return {
            "action": "clear_older_than_seconds",
            "older_than_seconds": older_than_seconds,
        }

    return {"action": "none"}


def _clear_replays_memory(update_id=None, clear_all=False):
    if clear_all:
        REPLAY_TRACKER.clear()
        REPLAY_SEEN.clear()
        return {"action": "clear_all"}

    if update_id is not None:
        REPLAY_SEEN.discard(update_id)
        filtered = deque(item for item in REPLAY_TRACKER if item != update_id)
        REPLAY_TRACKER.clear()
        REPLAY_TRACKER.extend(filtered)
        return {"action": "clear_by_update_id", "update_id": update_id}

    return {"action": "none"}


async def _clear_replays(env, update_id=None, older_than_seconds=None, clear_all=False):
    db = _get_db(env)
    if not db:
        return _clear_replays_memory(update_id=update_id, clear_all=clear_all)
    await _ensure_storage_schema_once(db)
    return await _clear_replays_db(
        db,
        update_id=update_id,
        older_than_seconds=older_than_seconds,
        clear_all=clear_all,
    )


def _cleanup_update_ids_memory():
    while len(REPLAY_SEEN) > REPLAY_TRACKER.maxlen:
        old = REPLAY_TRACKER.popleft()
        REPLAY_SEEN.discard(old)


async def _set_pending_delete_state(db, chat_key, tenant_id, entry_id):
    await db.prepare(
        f"DELETE FROM {PARTYMATH_PENDING_DELETES_TABLE} "
        f"WHERE chat_id = ?1 AND tenant_id = ?2"
    ).bind(chat_key, tenant_id).run()
    await db.prepare(
        f"INSERT INTO {PARTYMATH_PENDING_DELETES_TABLE}(chat_id, tenant_id, entry_id, requested_at) "
        "VALUES (?1, ?2, ?3, ?4)"
    ).bind(chat_key, tenant_id, entry_id, int(datetime.now().timestamp())).run()


async def _get_pending_delete_state(db, chat_key, tenant_id):
    await db.prepare(
        f"DELETE FROM {PARTYMATH_PENDING_DELETES_TABLE} "
        f"WHERE requested_at < ?1"
    ).bind(int(datetime.now().timestamp()) - PENDING_DELETE_TTL_SECONDS).run()

    row = await db.prepare(
        f"SELECT entry_id FROM {PARTYMATH_PENDING_DELETES_TABLE} "
        f"WHERE chat_id = ?1 AND tenant_id = ?2"
    ).bind(chat_key, tenant_id).first()
    if not row:
        return None
    return _row_value(row, "entry_id")


def _set_pending_delete_state_memory(chat_key, tenant_id, entry_id):
    PENDING_DELETES[_tenant_membership_key(chat_key, tenant_id)] = entry_id


def _get_pending_delete_state_memory(chat_key, tenant_id):
    return PENDING_DELETES.get(_tenant_membership_key(chat_key, tenant_id))


async def _clear_pending_delete_state(db, chat_key, tenant_id):
    await db.prepare(
        f"DELETE FROM {PARTYMATH_PENDING_DELETES_TABLE} WHERE chat_id = ?1 AND tenant_id = ?2"
    ).bind(chat_key, tenant_id).run()


def _clear_pending_delete_state_memory(chat_key, tenant_id):
    PENDING_DELETES.pop(_tenant_membership_key(chat_key, tenant_id), None)


async def _set_pending_delete(env, chat_key, tenant_id, entry_id):
    db = _get_db(env)
    if not db:
        _set_pending_delete_state_memory(chat_key, tenant_id, entry_id)
        return
    await _ensure_storage_schema_once(db)
    await _set_pending_delete_state(db, chat_key, tenant_id, entry_id)


async def _get_pending_delete(env, chat_key, tenant_id):
    db = _get_db(env)
    if not db:
        return _get_pending_delete_state_memory(chat_key, tenant_id)
    await _ensure_storage_schema_once(db)
    return await _get_pending_delete_state(db, chat_key, tenant_id)


async def _clear_pending_delete(env, chat_key, tenant_id):
    db = _get_db(env)
    if not db:
        _clear_pending_delete_state_memory(chat_key, tenant_id)
        return
    await _ensure_storage_schema_once(db)
    await _clear_pending_delete_state(db, chat_key, tenant_id)


def _parse_query_param(url, key: str, default=None):
    query = parse_qs(url.query)
    values = query.get(key)
    if not values:
        return default
    return values[0]


def _parse_bool_param(raw_value, default=False):
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in ("1", "true", "yes", "on")


async def _list_tenant_state(env, tenant_filter=None):
    db = _get_db(env)
    if not db:
        return None

    await _ensure_storage_schema_once(db)

    if tenant_filter:
        tenant_rows = await db.prepare(
            f"SELECT tenant_id, tenant_name FROM {PARTYMATH_TENANTS_TABLE} WHERE tenant_id = ?1"
        ).bind(tenant_filter).all()
    else:
        tenant_rows = await db.prepare(
            f"SELECT tenant_id, tenant_name FROM {PARTYMATH_TENANTS_TABLE} ORDER BY tenant_id"
        ).all()
    replay_row = await db.prepare(
        f"SELECT COUNT(*) as count FROM {PARTYMATH_REPLAY_TABLE}"
    ).first()
    replay_count = _row_value(replay_row, "count") or 0
    settings_rows = await db.prepare(
        f"SELECT COUNT(*) as count, SUM(is_enabled) as enabled_count "
        f"FROM {PARTYMATH_CHAT_SETTINGS_TABLE}"
    ).first()
    chat_settings_count = _row_value(settings_rows, "count") or 0
    enabled_chat_settings_count = _row_value(settings_rows, "enabled_count") or 0

    tenants = []
    for row in getattr(tenant_rows, "results", []):
        tenant_id = _row_value(row, "tenant_id")
        tenant_name = _row_value(row, "tenant_name")
        if not tenant_id:
            continue

        entries = await db.prepare(
            f"SELECT COUNT(*) as count FROM {PARTYMATH_ENTRIES_TABLE} WHERE tenant_id = ?1"
        ).bind(tenant_id).first()
        pending = await db.prepare(
            f"SELECT COUNT(*) as count FROM {PARTYMATH_PENDING_DELETES_TABLE} WHERE tenant_id = ?1"
        ).bind(tenant_id).first()
        members = await db.prepare(
            f"SELECT COUNT(*) as count FROM {PARTYMATH_TENANT_MEMBERSHIPS_TABLE} WHERE tenant_id = ?1"
        ).bind(tenant_id).first()

        tenants.append({
            "tenant_id": tenant_id,
            "tenant_name": tenant_name,
            "entries": _row_value(entries, "count") or 0,
            "pending_deletes": _row_value(pending, "count") or 0,
            "chat_memberships": _row_value(members, "count") or 0,
            "replays_tracked": replay_count,
        })

    if tenant_filter:
        tenant = await _load_tenant_from_db(db, tenant_filter)
        tenants_payload = [tenant] if tenant else []
    else:
        tenants_payload = []

    return {
        "tenants": tenants,
        "tenant_detail": tenants_payload,
        "chat_settings": {
            "configured_chats": chat_settings_count,
            "enabled_chats": enabled_chat_settings_count,
        },
    }


async def _run_scheduled_deliveries(env, now=None):
    now = now or datetime.now(timezone.utc)
    db = _get_db(env)
    if not db:
        return {
            "ok": False,
            "message": "d1_not_configured",
            "scheduled": 0,
            "sent": 0,
            "skipped": 0,
            "failed": 0,
        }

    await _ensure_storage_schema_once(db)
    due_rows = await _list_due_chat_tenant_rows(db, now)
    if not due_rows:
        return {"ok": True, "scheduled": 0, "sent": 0, "skipped": 0, "failed": 0, "message": "No reminders due"}

    delivery_date = _delivery_date_for_now(now)
    chats = {}
    for row in due_rows:
        chat_id = row.get("chat_id")
        tenant_id = row.get("tenant_id")
        tenant_name = row.get("tenant_name")
        if not chat_id or not tenant_id:
            continue
        chats.setdefault(chat_id, []).append((tenant_id, tenant_name))

    if not chats:
        return {"ok": True, "scheduled": 0, "sent": 0, "skipped": 0, "failed": 0, "message": "No tenants due"}

    sent = 0
    skipped = 0
    failed = 0

    for chat_id, tenant_rows in chats.items():
        telegram_text_parts = []
        tenant_ids_for_send = []
        for tenant_id, tenant_name in tenant_rows:
            if await _has_delivered_today(db, chat_id, tenant_id, delivery_date):
                skipped += 1
                continue

            tenant = await _load_tenant_from_db(db, tenant_id)
            if not tenant:
                skipped += 1
                continue

            tenant_lines = _tenant_today_lines_for_date(tenant, now.date())
            if not tenant_lines:
                skipped += 1
                continue

            if tenant_name and tenant.get("name") != tenant_name:
                tenant_lines.insert(0, f"🏢 {tenant_name}")
            tenant_ids_for_send.append(tenant_id)
            telegram_text_parts.append("\n".join(tenant_lines))

        if not telegram_text_parts:
            continue

        telegram_text = "\n\n".join(telegram_text_parts)
        telegram_chat_id = _safe_int(chat_id) or chat_id
        try:
            telegram_send = await _send_telegram_text(telegram_chat_id, telegram_text, env.TELEGRAM_BOT_TOKEN)
        except Exception as exc:
            telegram_send = {"ok": False, "error": str(exc)}

        was_sent = bool(telegram_send.get("ok"))
        for tenant_id in tenant_ids_for_send:
            await _mark_delivery(db, chat_id, tenant_id, delivery_date, was_sent)

        if was_sent:
            sent += len(tenant_ids_for_send)
        else:
            failed += len(tenant_ids_for_send)

    return {
        "ok": True,
        "scheduled": len(due_rows),
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "delivery_date": delivery_date,
        "processed": len(chats),
    }


async def _message_for_delete(tenant: dict, args: str, chat_key: str, env):
    if not args:
        return {"text": "Use: /delete <id> or /delete <id> confirm"}

    parts = args.split()
    entry_id = parts[0]
    confirmed = len(parts) > 1 and parts[1].lower() == "confirm"

    lookup = find_entry_by_id(tenant, entry_id)
    if not lookup:
        return {"text": f"No entry found with id {entry_id}."}

    _, _, entry = lookup
    if not confirmed:
        await _set_pending_delete(env, chat_key, tenant["id"], entry_id)
        return {
            "text": (
                f"🗑️ Remove '{entry.get('name')}' ({entry_id})?\n"
                f"Reply '/delete {entry_id} confirm' to confirm."
            )
        }

    pending_entry_id = await _get_pending_delete(env, chat_key, tenant["id"])
    if pending_entry_id != entry_id:
        await _set_pending_delete(env, chat_key, tenant["id"], entry_id)
        return {
            "text": (
                f"⚠️ Deletion for {entry_id} requires confirmation.\n"
                f"Reply '/delete {entry_id} confirm' to confirm."
            )
        }

    await _clear_pending_delete(env, chat_key, tenant["id"])
    delete_entry_by_id(tenant, entry_id)
    db = _get_db(env)
    if db:
        await _ensure_storage_schema_once(db)
        await _delete_entry_from_db(db, tenant["id"], entry_id)
    return {"text": f"🗑️ Deleted '{entry.get('name')}' ({entry_id}) from {tenant['name']}."}


async def _message_for_tenant_command(env, chat_id, args: str):
    db = _get_db(env)
    if not db:
        return {"text": "⚠️ Tenant commands are available after D1 is configured."}

    await _ensure_storage_schema_once(db)
    chat_key = str(chat_id)
    action, raw_value = (args.split(maxsplit=1) + [""])[:2]
    action = action.strip().lower()
    if not action:
        return {
            "text": (
                "Usage:\n"
                "/tenant list\n"
                "/tenant create <name>\n"
                "/tenant use <tenant-id>\n"
                "/tenant default"
            )
        }

    if action == "list":
        memberships = await _list_chat_tenants(db, chat_key)
        if not memberships:
            tenant = await _tenant_for_chat(chat_id, env)
            memberships = [{
                "tenant_id": tenant["id"],
                "tenant_name": tenant["name"],
                "is_default": True,
                "entry_count": len(_all_entries(tenant)),
            }]
        lines = [f"🏢 Tenants for chat {chat_key}:"]
        for membership in memberships:
            default_marker = "✅" if membership.get("is_default") else "  "
            tenant_name = membership.get("tenant_name") or "(no name)"
            lines.append(
                f"{default_marker} {membership.get('tenant_id')} — "
                f"{tenant_name} ({membership.get('entry_count', 0)} items)"
            )
        return {"text": "\n".join(lines)}

    if action == "default":
        tenant = await _tenant_for_chat(chat_id, env)
        return {"text": f"🏠 Active tenant: {tenant['id']} ({tenant['name']})."}

    if action == "create":
        tenant_name = (raw_value or "").strip() or f"Tenant for {chat_key}"
        tenant = await _create_tenant_record(db, tenant_name, include_default_entries=False)
        await _attach_tenant_to_chat(db, chat_key, tenant["id"], make_default=False)
        return {
            "text": (
                f"✅ Created tenant '{tenant['name']}' with id {tenant['id']}.\n"
                "Use /tenant use <tenant-id> to switch."
            )
        }

    if action == "use":
        tenant_id = (raw_value or "").strip()
        if not tenant_id:
            return {"text": "Usage: /tenant use <tenant-id>"}

        tenant = await _load_tenant_from_db(db, tenant_id)
        if not tenant:
            return {
                "text": (
                    f"⚠️ Tenant '{tenant_id}' not found. "
                    "Create it with /tenant create, then use its id."
                )
            }

        membership_row = await db.prepare(
            f"SELECT tenant_id FROM {PARTYMATH_TENANT_MEMBERSHIPS_TABLE} "
            f"WHERE chat_id = ?1 AND tenant_id = ?2"
        ).bind(chat_key, tenant_id).first()
        if not membership_row:
            return {
                "text": (
                    f"⚠️ Tenant '{tenant_id}' is not linked to this chat. "
                    "Use /tenant list to see available tenants."
                )
            }

        await _set_default_tenant_for_chat(db, chat_key, tenant_id)
        return {"text": f"✅ Active tenant switched to '{tenant['name']}' ({tenant_id})."}

    return {"text": "Unknown tenant command. Try /tenant list, create, use, or default."}


async def _message_for_command(command: str, args: str, tenant: dict, chat_id: int, env):
    if command == "start":
        return _handle_start()
    if command == "help":
        return _handle_start()
    if command == "today":
        return _message_for_tenant_today(tenant)
    if command == "upcoming":
        return _message_for_upcoming(tenant, args)
    if command == "list":
        return _message_for_list(tenant)
    if command == "find":
        return _message_for_find(tenant, args)
    if command == "tenant":
        return await _message_for_tenant_command(env, chat_id, args)
    if command == "add":
        return await _message_for_add(env, tenant, args)
    if command == "delete":
        return await _message_for_delete(tenant, args, str(chat_id), env)
    return {
        "text": (
            f"Unknown command '{command}'. Try /start to see available commands."
        )
    }


async def _send_telegram_text(chat_id: int, text: str, bot_token: str) -> dict:
    if not bot_token:
        return {"ok": False, "error": "bot token not configured"}

    telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        telegram_response = await fetch(
            telegram_url,
            _to_js_object(
                {
                    "method": "POST",
                    "headers": {"content-type": "application/json"},
                    "body": json.dumps({"chat_id": chat_id, "text": text}),
                }
            ),
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    raw_result = await telegram_response.text()
    try:
        payload = json.loads(raw_result)
    except JSONDecodeError:
        payload = {"ok": False, "raw": raw_result}
    return payload


def _bearer_token(value: str) -> str:
    prefix = "bearer "
    if value.lower().startswith(prefix):
        return value[len(prefix) :].strip()
    return ""


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlparse(request.url)

        if request.method == "GET" and url.path in ("", "/"):
            return _json_response(
                {
                    "ok": True,
                    "service": "partymath",
                    "mode": "cloudflare-worker",
                    "paths": [
                        "/health",
                        "/telegram/webhook",
                        "/admin/set-webhook",
                        "/admin/tenant-state",
                        "/admin/clear-replays",
                    ],
                }
            )

        if request.method == "GET" and url.path == "/health":
            return _json_response(
                {
                    "ok": True,
                    "service": "partymath",
                    "bot_token_configured": bool(self.env.TELEGRAM_BOT_TOKEN),
                    "webhook_secret_configured": bool(self.env.TELEGRAM_WEBHOOK_SECRET),
                    "d1_bound": bool(_get_db(self.env)),
                }
            )

        if request.method == "GET" and url.path == "/admin/tenant-state":
            supplied_token = _bearer_token(request.headers.get(ADMIN_AUTH_HEADER, ""))
            if not hmac.compare_digest(supplied_token, self.env.PARTYMATH_ADMIN_TOKEN):
                return _json_response({"ok": False, "error": "forbidden"}, status=403)

            tenant_id = _parse_query_param(url, "tenant_id")
            state = await _list_tenant_state(self.env, tenant_filter=tenant_id)
            if state is None:
                return _json_response({"ok": False, "error": "d1_not_configured"}, status=503)

            return _json_response({
                "ok": True,
                **state,
                "tenant_id": tenant_id,
            })

        if request.method == "GET" and url.path == "/admin/clear-replays":
            supplied_token = _bearer_token(request.headers.get(ADMIN_AUTH_HEADER, ""))
            if not hmac.compare_digest(supplied_token, self.env.PARTYMATH_ADMIN_TOKEN):
                return _json_response({"ok": False, "error": "forbidden"}, status=403)

            update_id = _safe_int(_parse_query_param(url, "update_id"))
            clear_all = _parse_bool_param(_parse_query_param(url, "all"), default=False)
            older_than_seconds = _safe_int(_parse_query_param(url, "older_than_seconds"))

            if update_id is None and not clear_all and older_than_seconds is None:
                return _json_response(
                    {
                        "ok": False,
                        "error": "missing target",
                        "usage": "/admin/clear-replays?all=1 or ?update_id=<id> or ?older_than_seconds=<sec>",
                    },
                    status=400,
                )

            result = await _clear_replays(
                self.env,
                update_id=update_id,
                older_than_seconds=older_than_seconds,
                clear_all=clear_all,
            )

            return _json_response({
                "ok": True,
                **result,
            })

        if request.method == "POST" and url.path == "/telegram/webhook":
            try:
                supplied_secret = request.headers.get(WEBHOOK_SECRET_HEADER, "")
                expected_secret = self.env.TELEGRAM_WEBHOOK_SECRET

                if not hmac.compare_digest(supplied_secret, expected_secret):
                    print(
                        "[partymath] webhook secret mismatch: "
                        f"got_len={len(supplied_secret)} "
                        f"expect_len={len(expected_secret)}"
                    )
                    return _json_response({"ok": False, "error": "unauthorized"}, status=401)

                raw_body = await request.text()
                if not raw_body:
                    return _json_response({"ok": False, "error": "empty body"}, status=400)

                try:
                    update = json.loads(raw_body)
                except JSONDecodeError:
                    return _json_response({"ok": False, "error": "invalid json"}, status=400)

                update_id = update.get("update_id")
                update_type = _extract_update_type(update)
                print(
                    f"[partymath] webhook update_id={update_id} "
                    f"type={update_type}"
                )
                if await _is_duplicate_update(self.env, update_id):
                    print(f"[partymath] duplicate update_id={update_id}")
                    return _json_response(
                        {
                            "ok": True,
                            "duplicate": True,
                            "update_id": update_id,
                        }
                    )

                chat_id, text, message_date = _extract_chat_and_text(update)
                if chat_id is None:
                    return _json_response(
                        {
                            "ok": False,
                            "error": "unable to extract chat id",
                            "update_id": update_id,
                            "update_type": update_type,
                        },
                        status=400,
                    )

                command, args = _parse_command_and_args(text or "")
                if not command:
                    print(
                        f"[partymath] received non-command update "
                        f"update_id={update_id} update_type={update_type} chat_id={chat_id}"
                    )
                    await _mark_update_seen(self.env, update_id)
                    return _json_response(
                        {
                            "ok": True,
                            "received": True,
                            "update_id": update_id,
                            "update_type": update_type,
                            "chat_id": chat_id,
                            "note": "no command found in update",
                        }
                    )

                print(
                    f"[partymath] handling chat_id={chat_id} command={command} "
                    f"args='{args}'"
                )

                scheduled_payload = None
                if command == "start":
                    scheduled_payload = await _ensure_chat_schedule(
                        self.env,
                        str(chat_id),
                        message_timestamp=message_date,
                    )

                tenant = await _tenant_for_chat(chat_id, self.env)
                command_result = await _message_for_command(
                    command,
                    args,
                    tenant,
                    chat_id,
                    self.env,
                )
                command_text = command_result.get("text", "")
                if not command_text:
                    raise RuntimeError("command handler returned empty response text")

                try:
                    await _mark_update_seen(self.env, update_id)
                except Exception as exc:
                    print(
                        f"[partymath] failed to mark update as seen chat_id={chat_id} "
                        f"update_id={update_id} error={type(exc).__name__}: {exc}"
                    )

                if command == "start" and scheduled_payload:
                    notify_hour = _row_value(scheduled_payload, "notify_hour")
                    notify_minute = _row_value(scheduled_payload, "notify_minute")
                    if notify_hour is not None and notify_minute is not None:
                        command_text = (
                            f"{command_text}\n"
                            "🎯 Daily reminders will now run once per day at "
                            f"{notify_hour:02d}:{notify_minute:02d} UTC"
                            " for your workspace."
                        )

                telegram_send = await _send_telegram_text(
                    chat_id,
                    command_text,
                    self.env.TELEGRAM_BOT_TOKEN,
                )
                if not telegram_send.get("ok"):
                    print(
                        f"[partymath] failed to send telegram response "
                        f"chat_id={chat_id} ok={telegram_send.get('ok')} error={telegram_send.get('error')}"
                    )
                    return _json_response(
                        {
                            "ok": True,
                            "received": True,
                            "update_id": update_id,
                            "update_type": update_type,
                            "chat_id": chat_id,
                            "text": command_text,
                            "telegram": telegram_send,
                            "warning": TELEGRAM_SEND_FAIL_MESSAGE,
                        }
                    )

                print(
                    f"[partymath] sent telegram response successfully "
                    f"chat_id={chat_id} command={command} update_id={update_id}"
                )
                return _json_response(
                    {
                        "ok": True,
                        "received": True,
                        "update_id": update_id,
                        "update_type": update_type,
                        "chat_id": chat_id,
                        "telegram": telegram_send,
                        "text": command_text,
                    }
                )
            except Exception as exc:
                message = str(exc)
                print(f"[partymath] webhook traceback: {traceback.format_exc()}")
                print(f"[partymath] webhook processing error: {message}")
                return _json_response(
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": message,
                        "source": "telegram_webhook",
                    },
                    status=200,
                )

        if request.method == "POST" and url.path == "/admin/set-webhook":
            supplied_token = _bearer_token(request.headers.get(ADMIN_AUTH_HEADER, ""))
            if not hmac.compare_digest(supplied_token, self.env.PARTYMATH_ADMIN_TOKEN):
                return _json_response({"ok": False, "error": "forbidden"}, status=403)

            webhook_url = f"{url.scheme}://{url.netloc}/telegram/webhook"
            telegram_url = (
                f"https://api.telegram.org/bot{self.env.TELEGRAM_BOT_TOKEN}/setWebhook"
            )
            payload = {
                "url": webhook_url,
                "secret_token": self.env.TELEGRAM_WEBHOOK_SECRET,
            }
            telegram_response = await fetch(
                telegram_url,
                _to_js_object(
                    {
                        "method": "POST",
                        "headers": {"content-type": "application/json"},
                        "body": json.dumps(payload),
                    }
                ),
            )

            raw_result = await telegram_response.text()
            try:
                telegram_result = json.loads(raw_result)
            except JSONDecodeError:
                telegram_result = {"ok": False, "raw": raw_result}

            return _json_response(
                {
                    "ok": bool(telegram_result.get("ok")),
                    "webhook_url": webhook_url,
                    "telegram_result": telegram_result,
                },
                status=200 if telegram_result.get("ok") else 502,
            )

        return _json_response({"ok": False, "error": "not found"}, status=404)

    async def scheduled(self, controller, env, ctx):
        schedule_result = await _run_scheduled_deliveries(env)
        return _json_response(
            {
                "ok": schedule_result.get("ok", False),
                "service": "partymath",
                "scheduled": schedule_result.get("scheduled", 0),
                "sent": schedule_result.get("sent", 0),
                "skipped": schedule_result.get("skipped", 0),
                "failed": schedule_result.get("failed", 0),
                "delivery_date": schedule_result.get("delivery_date"),
                "message": schedule_result.get("message"),
                **({} if schedule_result.get("ok") else {"reason": schedule_result.get("message")}),
            }
        )
