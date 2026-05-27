# Telegram And Cloudflare Roadmap

## Product Direction

Turn Celebrations into a multi-tenant Telegram service while preserving the
working CLI and shared milestone logic.

- For the hosted product, use one newly branded Telegram bot rather than one
  bot token per tenant.
- Preserve the existing Celebrations bot and local notifier path during
  Cloudflare development; do not repoint it to a Worker as part of staging.
- Treat each Telegram group or supergroup chat as a celebration workspace.
- Use Telegram `chat.id` as the durable workspace identity; accept negative
  group IDs and normalize commands such as `/add@bot_name`.
- Treat a private chat as its own workspace initially. Administrative access
  to group workspaces can be designed later.
- Keep birthdays and anniversaries in one user-facing workflow, distinguished
  internally by celebration type.
- Prefer a Python Worker for the hosted implementation if a short feasibility
  spike confirms that the existing calculation rules and `python-dateutil`
  dependency run cleanly in Cloudflare's Python environment.
- Keep the legacy Kivy application out of this path unless explicitly targeted.

## Naming And Bot Separation

The Cloudflare migration is also a clean opportunity to rename the app. Do not
force the hosted service to inherit the current Celebrations identity before
choosing a name that fits a shared family-memory and milestone bot.

Before Telegram webhook development:

1. Choose a new product name and a matching Telegram-facing bot identity.
2. Create a new bot through BotFather using that identity.
3. Store its token only as a Cloudflare development or staging secret.
4. Use the new bot for Python Worker webhook, D1, and scheduled-delivery work.
5. Keep the existing bot connected to the current local Python/systemd path
   throughout parallel development.

This establishes two deliberately separate tracks:

```text
Existing bot -> local Python CLI/notifier -> existing tenant JSON data
New named bot -> Cloudflare Python Worker -> staging/new D1 data
```

The new hosted bot is still one bot shared by many tenant chats. It is not a
return to per-tenant bot tokens. Decide on production cutover, import, and
whether the old bot is retired only after the new bot has proven the desired
interaction model and scheduled output.

Name-selection checkpoint:

- The name should make sense in a Telegram group and in daily notification
  text.
- A matching, readable bot username should be available before development is
  coupled to that branding.
- Do not rename the legacy local application or bot merely to enable staging.

## Intended Telegram Surface

Begin with a small, learnable command surface:

```text
/start
/add birthday Roger | 1980-08-14 | Dad
/add anniversary Alice & Bob | 2018-09-14 | wedding
/today
/upcoming 30
/list
/find Roger
/delete <id>
```

Deletion must require inline-button confirmation before removing an entry.
Successful additions and deletions should be visibly acknowledged in the chat
so a family workspace has a lightweight activity record.

After the interaction model has been exercised in real chats, add:

```text
/edit <id> name <value>
/edit <id> date <YYYY-MM-DD>
/edit <id> hint <value>
/settings timezone America/Denver
/settings daily 07:00
/export
```

For `/find` and `/list`, inline buttons are a good fit for `Edit`, `Delete`,
and `Upcoming` actions. Decide whether everyone in a group can mutate data or
only Telegram administrators can do so before making permissions complicated.

## Local Foundation

The current local implementation already supports tenant paths through
`--tenant` and sends daily Telegram output through
`scripts/celebration-notifier.sh`. The notifier is outbound-only and should
not become the two-way Telegram implementation.

After the feasibility spike confirms the hosted runtime direction, prepare the
application boundary for the full migration:

1. Add stable IDs for celebration entries.
2. Add shared mutation helpers in `celebrations_core.py` for create, find,
   update, soft delete, and restore behavior.
3. Keep `cli/celebrations.py` as one adapter over those shared helpers.
4. Add a Telegram webhook adapter that calls the same helpers and initially
   resolves a Telegram chat to local tenant storage.
5. Preserve current birthday, anniversary, milestone, budget, and iCal
   calculations through CLI validation fixtures.

During this local phase, it is acceptable to retain separate tenant
`birthdays.json` and `anniversaries.json` files. The goal is to settle the
Telegram vocabulary and permissions before changing storage.

## Python Worker Preference

The valuable and risky-to-rewrite part of this application is already Python:
`celebrations_core.py` contains birthday, anniversary, fractional monthday,
centusday, kiloday, budget, and milestone behavior. A Python Worker can reduce
semantic migration risk by preserving that logic rather than translating it
into TypeScript during the hosting move.

Cloudflare Python Workers currently provide `fetch()` and scheduled handlers,
D1 and secret bindings through the Workers runtime, and package support through
`pywrangler`. Python Workers remain a beta platform feature, so this choice is
conditional on a focused staging-only feasibility spike and a straightforward
rollback path.

The current Python code cannot move unchanged. Filesystem-dependent concerns
must be separated first:

- Replace `~/.config/celebrations/...` reads and JSON writes with storage
  adapters: local JSON for the CLI path and D1 for the Worker path.
- Return iCal text from hosted routes rather than writing
  `celebrations.ics` to a persistent local filesystem.
- Replace shell/systemd delivery with Worker webhook and scheduled handlers.

Platform references:

- <https://developers.cloudflare.com/workers/languages/python/>
- <https://developers.cloudflare.com/workers/languages/python/packages/>
- <https://developers.cloudflare.com/d1/examples/query-d1-from-python-workers/>
- <https://developers.cloudflare.com/workers/examples/cron-trigger/>

## Cloudflare Target

The hosted target is preferably a Python Worker backed by D1:

```text
Telegram webhook -> Python Worker fetch()     -> command handler -> D1 -> Telegram replies
Cron Trigger      -> Python Worker scheduled() -> due tenant query -> D1 -> Telegram sends
```

Use:

- A Python Worker `fetch()` handler for Telegram webhook updates.
- A D1 binding for tenant, member, celebration, settings, and delivery data.
- Worker secrets for the Telegram bot token and webhook verification secret.
- A distinct development/staging bot token belonging to the new hosted-product
  identity; do not reuse the current local notifier bot token.
- One periodic Cron Trigger for daily notifications across all workspaces.
- A stored next-delivery time or delivery ledger instead of one Cron Trigger
  per tenant.

Do not begin with R2, a dashboard, or a legacy GUI port. Those can be revisited
after the Telegram service is useful and trustworthy.

## Candidate D1 Schema

The JSON files should eventually import into a relational model similar to:

```text
tenants
- id
- telegram_chat_id
- name
- timezone
- daily_notification_time
- notifications_enabled

memberships
- tenant_id
- telegram_user_id
- role

celebrations
- id
- tenant_id
- type
- name
- date
- kind
- nickname
- hint
- gender
- nonhuman
- deceased
- created_by
- created_at
- updated_at
- deleted_at

telegram_updates
- update_id
- received_at

notification_deliveries
- tenant_id
- local_date
- sent_at
- result
```

`telegram_updates.update_id` prevents repeated webhook delivery from applying
the same mutation twice. `deleted_at` allows safe Telegram deletion and a
future restore flow.

## Rollout Slices

Status update:

- The `partymath` Cloudflare Worker has been scaffolded and deployed to `workers.dev`.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, and a one-time bootstrap token are stored as Cloudflare secrets.
- Telegram webhook registration is live against `https://partymath.rogerpbrown.workers.dev/telegram/webhook`.
- The next implementation slice is Telegram command handling on synthetic data before any D1 migration.

### Slice 1: Python Worker Feasibility Spike

- Scaffold a Python Worker in a new `deploy/cloudflare/` area.
- Package and import `python-dateutil`, which is required by the existing
  `relativedelta` calculation logic.
- Exercise a small shared calculation subset against synthetic birthday and
  anniversary data.
- Bind a local or staging D1 database and read synthetic celebration rows.
- Expose a test `fetch()` route that returns calculated celebration output.
- Run a local scheduled-handler smoke test.
- Do not connect a real Telegram webhook or import real tenant data.
- Naming and creation of the new Cloudflare-development Telegram bot may happen
  alongside this spike, but its token is not required for calculation or D1
  feasibility validation.

Acceptance:

- A Python Worker can execute representative existing calculation rules.
- `python-dateutil` packages and imports successfully in the Worker toolchain.
- Both D1 reads and a scheduled invocation work with synthetic records.
- The outcome is documented clearly enough to confirm Python or choose
  TypeScript before broader migration work starts.

### Slice 2: Shared Local CRUD

- Add stable IDs and shared create/list/find/delete operations.
- Separate calculation behavior from local JSON persistence so the same
  operations can later be implemented by a D1-backed adapter.
- Add CLI paths or fixtures that exercise birthday and anniversary CRUD.
- Keep persistence in tenant JSON files.

Acceptance:

- Existing `--test` behavior remains correct.
- A birthday and anniversary can be added, found, and deleted in isolated test
  config files without touching real user data.

### Slice 3: Telegram Two-Way MVP

- Receive Telegram webhook commands locally.
- Map `chat.id` to a tenant/workspace.
- Implement `/start`, `/add`, `/list`, `/find`, `/delete`, `/today`, and
  `/upcoming`.
- Require confirmation for delete.

Acceptance:

- A group chat can add a birthday and anniversary and see daily/upcoming output.
- Replayed Telegram updates do not duplicate writes.
- Group bot-mention syntax and negative chat IDs work.

### Slice 4: Settings And Operational Safety

- Add timezone and daily-message settings.
- Define group mutation permissions.
- Add export and soft-delete restoration.
- Log outbound send outcomes distinctly from generated message content.

Acceptance:

- A tenant receives date-sensitive output in its configured timezone.
- Accidental deletion is recoverable.

### Slice 5: Cloudflare Staging

- Complete the Python Worker and D1 migrations, unless Slice 1 identified a
  concrete reason to use TypeScript instead.
- Connect only the newly named Cloudflare-development bot to the staging
  webhook; leave the existing local bot untouched.
- Port the tested Telegram command surface first.
- Configure webhook-secret verification and dry-run scheduled delivery.
- Import synthetic or copied test tenant data only.

Acceptance:

- Webhook and scheduled paths work against staging D1.
- Scheduled dry-run proves which tenants/messages would be sent.
- No production Telegram webhook or local notifier is changed.
- The existing local Python bot continues operating independently during the
  comparison period.

### Slice 6: Data Migration And Cutover

- Import real tenant JSON data into D1 with backups retained locally.
- Decide explicitly whether the new named bot becomes the production bot, and
  communicate any user/group onboarding required by that change.
- Run scheduled Cloudflare delivery in a controlled comparison period.
- Enable real sends only after message and timezone parity is confirmed.
- Disable local systemd notification timers only after Cloudflare delivery is
  verified.

Acceptance:

- Telegram mutations persist in D1.
- Daily delivery is confirmed for each active tenant.
- There is a documented rollback path to local JSON/notifier operation.

## Guardrails

- Do not commit real tenant data, bot tokens, exports, or webhook secrets.
- Do not reuse or repoint the existing local notifier bot during Cloudflare
  development; use the newly named bot as an isolated hosted-service track.
- Do not duplicate milestone/date logic across CLI, webhook, and scheduler
  surfaces.
- Do not silently redirect group changes into a private user workspace.
- Do not migrate hosting and invent the full Telegram interaction model in the
  same first slice.
- Do not assume Python Worker parity from documentation alone; validate this
  application's date calculations and dependency packaging in Slice 1.
- Validate current repo state before choosing a slice; this roadmap is a
  direction document, not proof that a feature has shipped.

## Recommended Next Slice

Implement Slice 1 only: a Python Worker feasibility spike using synthetic data,
`python-dateutil`, D1, a small `fetch()` result, and a scheduled-handler smoke
test. This should answer whether Cloudflare can host the existing Python rules
before the project spends effort translating logic or building a Telegram
surface around an unproven runtime.
