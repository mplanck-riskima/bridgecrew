# repriortize-queued-work

**Started:** 2026-04-27  
**Completed:** 2026-05-03  
**Cost:** $10.1478

## Summary

Added a Pre-empt capability to the Discord bot's prompt queue, allowing users to immediately prioritize any queued prompt over the currently running task.

**What it does:** When a prompt is queued while another is running, the user sees a "Pre-empt" button on the queue notification message and on each row in the /list-queue view. Clicking Pre-empt: (1) cancels the currently running task, (2) inserts a "continue the work relayed to prompt: <original prompt>" item at queue position 1 so the interrupted work can resume afterward, and (3) moves the selected prompt to the front so it runs immediately next.

**Key files changed:**
- `discord_cogs/claude_prompt.py` — All implementation: `PreemptView` Discord UI component with Pre-empt + Remove buttons, `_handle_preempt` method, `_current_items: dict[int, QueuedPrompt]` for per-thread active-item tracking, Pre-empt buttons wired into queue notifications and `QueueListView`, plus fixes for race conditions, timeout handling, and cross-surface double-fire prevention.
- `docs/superpowers/specs/2026-04-26-preempt-queued-prompts-design.md` — Design spec.
- `docs/superpowers/plans/2026-04-26-preempt-queued-prompts.md` — Implementation plan.

**Design decisions:**
- The "continue..." resume item is inserted at index 1 of the deque (not 0), so the pre-empting prompt runs first and the interrupted work resumes second.
- Buttons are disabled and the notification message is updated immediately on click to prevent double-fire across both surfaces (notification message and /list-queue).
- Pre-empt reuses the existing `cancel()` code path for clean task cancellation and worker restart.
