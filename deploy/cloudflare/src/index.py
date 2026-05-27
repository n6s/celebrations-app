from __future__ import annotations

import hmac
import json
from json import JSONDecodeError
from urllib.parse import urlparse

from js import Object, fetch
from pyodide.ffi import to_js as _to_js
from workers import Response, WorkerEntrypoint


WEBHOOK_SECRET_HEADER = "x-telegram-bot-api-secret-token"
ADMIN_AUTH_HEADER = "authorization"


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
                    "paths": ["/health", "/telegram/webhook"],
                }
            )

        if request.method == "GET" and url.path == "/health":
            return _json_response(
                {
                    "ok": True,
                    "service": "partymath",
                    "bot_token_configured": bool(self.env.TELEGRAM_BOT_TOKEN),
                    "webhook_secret_configured": bool(self.env.TELEGRAM_WEBHOOK_SECRET),
                }
            )

        if request.method == "POST" and url.path == "/telegram/webhook":
            supplied_secret = request.headers.get(WEBHOOK_SECRET_HEADER, "")
            expected_secret = self.env.TELEGRAM_WEBHOOK_SECRET

            if not hmac.compare_digest(supplied_secret, expected_secret):
                return _json_response({"ok": False, "error": "unauthorized"}, status=401)

            raw_body = await request.text()
            if not raw_body:
                update = {}
            else:
                try:
                    update = json.loads(raw_body)
                except JSONDecodeError:
                    return _json_response({"ok": False, "error": "invalid json"}, status=400)

            return _json_response(
                {
                    "ok": True,
                    "received": True,
                    "update_id": update.get("update_id"),
                    "update_type": _extract_update_type(update),
                }
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
        return _json_response(
            {
                "ok": True,
                "service": "partymath",
                "scheduled": True,
            }
        )
