# Pre-empt Queued Prompts — Design Spec

**Date:** 2026-04-26
**Feature:** repriortize-queued-work
**Status:** Approved

## Overview

Add the ability to pre-empt the currently running task from two surfaces:

1. A **Pre-empt** button on the "Queued (position X)" notification message shown when a new prompt is added while a task is running.
2. A **Pre-empt** button per item in the `/list-queue` view.

When pre-empt fires: the running task is cancelled, a "continue the work relayed to prompt: `<original prompt>`" item is prepended to the front of the queue, and the selected prompt runs immediately next.

## Architecture

### State additions to `ClaudePrompt` cog (`discord_cogs/claude_prompt.py`)

- `_current_items: dict[int, QueuedPrompt]` — tracks which `QueuedPrompt` the worker is actively processing per channel ID. Set when the worker pops an item from the queue; cleared when the worker finishes or is cancelled.

No new fields on `QueuedPrompt`. The "continue..." entry is a freshly constructed `QueuedPrompt` with a modified prompt string.

### New view: `PreemptView`

A `discord.ui.View` attached to the existing "Queued (position X)" notification message. Contains:

- A **Pre-empt** button (triggers pre-empt logic).
- The existing **Remove** button (already present on queue notifications).

On pre-empt click, both buttons are disabled and the message is updated immediately to prevent double-fire.

### `QueueListView` update

Each item row in `/list-queue` gains a **Pre-empt** button alongside the existing **Remove** button. Clicking it runs the same pre-empt handler.

## Data Flow

Pre-empt sequence for thread with channel ID `cid`:

1. User @mentions bot while worker is running → `QueuedPrompt` created, enqueued, notification sent with `PreemptView`.
2. User clicks **Pre-empt**:
   a. Look up `current = _current_items.get(cid)`.
   b. Call `cancel(cid)` — cancels the `asyncio.Task` in `_workers[cid]` (same path as `/cancel` command).
   c. If `current` exists, construct a new `QueuedPrompt` with `prompt = f"continue the work relayed to prompt: {current.prompt}"` and `was_queued=True`.
   d. `appendleft` that item onto `_queues[cid]._queue` (the underlying `collections.deque`, consistent with how `/list-queue` already peeks at it).
   e. Disable Pre-empt and Remove buttons, update notification message.
3. Worker restart: cancellation triggers the existing worker-done path, which spawns a new worker. That worker processes: (incoming prompt) → ("continue..." item) → (remaining queue).

### Worker bookkeeping

In `_worker()`:
- Before processing each item: `self._current_items[cid] = item`
- After processing (success, cancel, or error): `self._current_items.pop(cid, None)`

## Error Handling & Edge Cases

| Scenario | Behaviour |
|---|---|
| Nothing running when Pre-empt clicked | `_current_items.get(cid)` returns `None`; skip "continue..." prepend; queued item runs normally next |
| Pre-empt clicked twice | Buttons disabled on first click; second Discord interaction gets a stale-interaction error — no double-cancel |
| `_current_items` missing (bot restarted mid-run) | Guard with `.get()`; cancel still fires, "continue..." prepend skipped, warning logged |
| Worker cancellation timing | Existing cancel path handles mid-response teardown; pre-empt rides it unchanged |
| Pre-empt on item 2+ from `/list-queue` | Selected item moves to front via `appendleft`; "continue..." for running task prepended before it; rest of queue unchanged |

## Files Changed

- `discord_cogs/claude_prompt.py` — primary file: `_current_items` dict, `PreemptView`, `QueueListView` update, `_worker` bookkeeping, pre-empt handler function

## Testing Plan

1. **Basic pre-empt:** Start long task → send second prompt → click Pre-empt. Verify cancel, new prompt starts, "continue..." in queue.
2. **Deep queue:** 2 items queued → add 3rd → Pre-empt 3rd. Verify order: 3rd runs, "continue..." at position 1, original items 1 & 2 follow.
3. **Nothing running:** Task finishes just before Pre-empt clicked. Verify no error, no "continue..." prepend, item runs normally.
4. **Pre-empt from `/list-queue`:** Verify button appears per item; mid-queue pre-empt produces correct order.
5. **Button disabled after click:** Verify Pre-empt and Remove are disabled after firing.
