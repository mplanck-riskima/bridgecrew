# cron-orders

Adds MCP tools for managing scheduled orders and renames the "schedules" concept to "orders" throughout the codebase.

## What Orders Are

Orders are recurring tasks dispatched automatically by the bot on a cron schedule. They send a prompt to a Discord channel (optionally mentioning the bot with a persona), where Claude executes the task autonomously. This feature was previously called "scheduled tasks" or "schedules."

## MCP Tools

Registered in `~/.claude/.mcp.json` as `orders-mcp` (stdio transport, runs `orders_mcp_server.py`):

**`list_orders()`** — Returns all scheduled orders.

**`create_order(name, prompt, cron_expr, project_id="", discord_channel_id="", prompt_template_id="", feature_name="", enabled=True)`**
- `cron_expr`: 5-field cron (minute hour day month weekday)
- `project_id`: from `list_projects()` — routes the order to the correct project thread
- `prompt_template_id`: from `list_personas()` — sets the bot persona for this order
- `feature_name`: targets a specific feature session (see below)
- If `discord_channel_id` is omitted, falls back to `DISCORD_CHANNEL_ID` env var

**`delete_order(order_id)`** — Permanently deletes an order. Returns `{"deleted": True, "order_id": ...}`. Returns HTTP 404 if the ID is invalid.

**`list_projects()`** — Returns `[{project_id, name, discord_channel_id}]` for all projects.

**`list_personas()`** — Returns `[{id, name}]` for all prompt templates.

## feature_name Targeting

An order can specify a `feature_name` field. When the order fires, the bot looks up that feature's active session and routes the prompt into that session's Claude context — so the order sees the feature's full conversation history, tools, and workspace context.

If the named feature has no active session, the order runs without a session (no prior context).

## Self-Cancellation

When an order fires, the bot appends `Order ID (for self-cancellation): <id>` to Claude's prompt. Claude can call `delete_order(order_id='<id>')` to permanently cancel the recurring order after completing the task. This enables one-shot orders: create an order that cancels itself when its goal is met.

The `SCHEDULED_ORDER_INSTRUCTIONS` system prompt tells Claude about this mechanism.

## Prompt Markers

The dispatcher (`_run_task()` in `dashboard/backend/app/routers/orders.py`) builds the full Discord prompt using these markers:
- `[order]` — signals to the bot that this is a scheduled dispatch (replaces `[scheduled-order]`)
- `[persona:{id}|{name}]` — sets the persona
- `[persona-label:{name}]` — human-readable persona name
- `[scheduled-project:{project_id}]` — routes to the correct project
- `[order-id:{id}]` — stripped by bot, appended as visible "Order ID" text to Claude's prompt
- `[order-feature:{name}]` — overrides feature session lookup with the named feature

## Rename from Schedules

- Backend: `schedules.py` → `orders.py`, routes `/api/schedules` → `/api/orders`, models `ScheduleCreate/Update` → `OrderCreate/Update`
- Database: collection name `scheduled_tasks` unchanged (no migration)
- Frontend: `Schedules.tsx` → `Orders.tsx`, `ScheduledTask` type → `Order`, nav route `/schedules` → `/orders`
- Bot: `[scheduled-order]` marker → `[order]`
