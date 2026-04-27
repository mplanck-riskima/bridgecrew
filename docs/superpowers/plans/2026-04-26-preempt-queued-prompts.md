# Pre-empt Queued Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Pre-empt button to queue notifications and `/list-queue` that cancels the running task, moves the selected prompt to run immediately, and prepends a "continue the work relayed to prompt: ..." entry for the interrupted task.

**Architecture:** All changes are in `discord_cogs/claude_prompt.py`. A new `_current_items` dict tracks the actively-running `QueuedPrompt` per thread so the pre-empt handler knows what to prepend. A new `PreemptView` replaces `CancelQueuedView` on queue notifications. `QueueListView` gets Pre-empt buttons alongside existing Remove buttons.

**Tech Stack:** discord.py 2.x (Views, Buttons), asyncio, `collections.deque` (underlying type of `asyncio.Queue._queue`)

---

### Task 1: Add `_current_items` tracking to the cog and worker

**Files:**
- Modify: `discord_cogs/claude_prompt.py:276-283` (`__init__`)
- Modify: `discord_cogs/claude_prompt.py:495-528` (`_worker`)

- [ ] **Step 1: Add `_current_items` dict to `__init__`**

In `ClaudePromptCog.__init__` (around line 283, after `self._system_run_labels`), add:

```python
# thread_id -> QueuedPrompt currently being processed by the worker
self._current_items: dict[int, QueuedPrompt] = {}
```

- [ ] **Step 2: Set `_current_items[thread_id]` in `_worker` before processing each item**

In `_worker`, the current structure around line 514 is:
```python
                try:
                    await self._process_prompt(item)
                except Exception as e:
                    log.exception("Error processing queued prompt")
                    try:
                        await item.message.channel.send(f"**Error:** {e}")
                    except discord.HTTPException:
                        pass
```

Replace it with:
```python
                self._current_items[thread_id] = item
                try:
                    await self._process_prompt(item)
                except Exception as e:
                    log.exception("Error processing queued prompt")
                    try:
                        await item.message.channel.send(f"**Error:** {e}")
                    except discord.HTTPException:
                        pass
                finally:
                    self._current_items.pop(thread_id, None)
```

- [ ] **Step 3: Update `_worker` queue message editing to clear buttons when processing starts**

The current code around line 504-513 creates a `CancelQueuedView` just to show "Processing...". Simplify to use `view=None` which removes all buttons (works for both `CancelQueuedView` and the new `PreemptView`):

Replace:
```python
                # Deactivate the Remove button on the queued notification
                if item.queue_message:
                    try:
                        view = CancelQueuedView(item)
                        view.remove.disabled = True
                        view.remove.label = "Processing..."
                        view.remove.style = discord.ButtonStyle.secondary
                        await item.queue_message.edit(view=view)
                    except discord.HTTPException:
                        pass
```

With:
```python
                # Remove buttons from the queue notification once processing starts
                if item.queue_message:
                    try:
                        await item.queue_message.edit(view=None)
                    except discord.HTTPException:
                        pass
```

- [ ] **Step 4: Commit**

```bash
git add discord_cogs/claude_prompt.py
git commit -m "feat: track current queue item per thread for pre-empt support"
```

---

### Task 2: Create `PreemptView` and `_handle_preempt`

**Files:**
- Modify: `discord_cogs/claude_prompt.py:220-273` (add `PreemptView` after `CancelQueuedView`)
- Modify: `discord_cogs/claude_prompt.py:275` (add `_handle_preempt` method to `ClaudePromptCog`)

- [ ] **Step 1: Add `PreemptView` class after `CancelQueuedView` (around line 234)**

Insert this class between `CancelQueuedView` and `QueueListView`:

```python
class PreemptView(discord.ui.View):
    """Queue notification view with Pre-empt and Remove buttons."""

    def __init__(self, item: QueuedPrompt, cog: "ClaudePromptCog") -> None:
        super().__init__(timeout=None)
        self.item = item
        self.cog = cog

    @discord.ui.button(label="Pre-empt", style=discord.ButtonStyle.primary)
    async def preempt(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await self.cog._handle_preempt(interaction.channel_id, self.item)

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.item.cancelled = True
        button.disabled = True
        button.label = "Removed"
        original = interaction.message.content if interaction.message else ""
        await interaction.response.edit_message(content=f"~~{original}~~", view=self)
```

- [ ] **Step 2: Add `_handle_preempt` method to `ClaudePromptCog`**

Add this method to `ClaudePromptCog`, before `_worker` (around line 495):

```python
    async def _handle_preempt(self, channel_id: int, item: QueuedPrompt) -> None:
        """Pre-empt the currently running task with `item`.

        Moves `item` to the front of the queue and inserts a
        'continue the work...' entry for the interrupted task at position 1.
        Then cancels the running subprocess so the worker picks up `item` next.
        """
        queue = self._queues.get(channel_id)
        if not queue:
            return

        current = self._current_items.get(channel_id)
        dq = queue._queue  # collections.deque — same access pattern as /list-queue

        # Move the pre-empting item to front (no-op if already there)
        try:
            dq.remove(item)
        except ValueError:
            pass  # item may have already been dequeued if worker was very fast
        dq.appendleft(item)

        # Insert the "continue..." entry right after item (index 1)
        if current is not None:
            continue_item = QueuedPrompt(
                message=current.message,
                prompt=f"continue the work relayed to prompt: {current.prompt}",
                project=current.project,
                was_queued=True,
            )
            dq.insert(1, continue_item)
        else:
            log.warning("_handle_preempt: no current item tracked for channel %s — skip continue entry", channel_id)

        # Cancel the running subprocess; worker loop will pick up the reordered queue naturally
        self.bot.claude_runner.cancel(channel_id)
```

- [ ] **Step 3: Commit**

```bash
git add discord_cogs/claude_prompt.py
git commit -m "feat: add PreemptView and _handle_preempt to ClaudePromptCog"
```

---

### Task 3: Use `PreemptView` in `on_message` queue notifications

**Files:**
- Modify: `discord_cogs/claude_prompt.py:387-398` (main channel queuing branch)
- Modify: `discord_cogs/claude_prompt.py:420-431` (thread queuing branch)

There are two places in `on_message` where a queue notification is sent with `CancelQueuedView`. Both need to switch to `PreemptView`.

- [ ] **Step 1: Update the main channel queuing branch (around line 393)**

Replace:
```python
                view = CancelQueuedView(queued)
                label = self._system_run_labels.get(channel_id)
                label_str = f" — {label}" if label else ""
                queue_msg = await message.channel.send(f"*Queued (position {position}{label_str}):* `{preview}`", view=view)
```

With:
```python
                view = PreemptView(queued, self)
                label = self._system_run_labels.get(channel_id)
                label_str = f" — {label}" if label else ""
                queue_msg = await message.channel.send(f"*Queued (position {position}{label_str}):* `{preview}`", view=view)
```

- [ ] **Step 2: Update the thread queuing branch (around line 426)**

Replace:
```python
                view = CancelQueuedView(queued)
                label = self._system_run_labels.get(thread_id)
                label_str = f" — {label}" if label else ""
                queue_msg = await message.channel.send(f"*Queued (position {position}{label_str}):* `{preview}`", view=view)
```

With:
```python
                view = PreemptView(queued, self)
                label = self._system_run_labels.get(thread_id)
                label_str = f" — {label}" if label else ""
                queue_msg = await message.channel.send(f"*Queued (position {position}{label_str}):* `{preview}`", view=view)
```

- [ ] **Step 3: Commit**

```bash
git add discord_cogs/claude_prompt.py
git commit -m "feat: show Pre-empt button on queue notifications"
```

---

### Task 4: Add Pre-empt buttons to `QueueListView` and `/list-queue`

**Files:**
- Modify: `discord_cogs/claude_prompt.py:236-272` (`QueueListView`)
- Modify: `discord_cogs/claude_prompt.py:1172-1186` (`list_queue` command)

Discord allows max 25 interactive components per message. With 2 buttons per item (Remove + Pre-empt), cap at 12 items to stay within the limit.

- [ ] **Step 1: Update `QueueListView.__init__` to accept optional `cog` and `channel_id`**

Replace the entire `QueueListView` class:

```python
class QueueListView(discord.ui.View):
    """Shows all queued items with per-item Remove and Pre-empt buttons."""

    def __init__(self, items: list[QueuedPrompt], cog: "ClaudePromptCog | None" = None, channel_id: int = 0):
        super().__init__(timeout=120)
        self.items = items
        self.cog = cog
        self.channel_id = channel_id
        # With 2 buttons per item, Discord's 25-component cap means max 12 items
        limit = 12 if cog is not None else 25
        for i, item in enumerate(items[:limit]):
            self.add_item(self._make_remove_button(i, item))
            if cog is not None:
                self.add_item(self._make_preempt_button(i, item))

    def _make_remove_button(self, index: int, item: QueuedPrompt):
        button = discord.ui.Button(
            label=f"Remove #{index + 1}",
            style=discord.ButtonStyle.danger,
            custom_id=f"remove_{id(item)}",
        )

        async def callback(interaction: discord.Interaction, _item=item, _btn=button):
            _item.cancelled = True
            _btn.disabled = True
            _btn.label = f"#{list(self.items).index(_item) + 1} Removed"
            await interaction.response.edit_message(content=self._render(), view=self)

        button.callback = callback
        return button

    def _make_preempt_button(self, index: int, item: QueuedPrompt):
        button = discord.ui.Button(
            label=f"Pre-empt #{index + 1}",
            style=discord.ButtonStyle.primary,
            custom_id=f"preempt_{id(item)}",
        )

        async def callback(interaction: discord.Interaction, _item=item, _btn=button):
            _btn.disabled = True
            # Also disable the matching remove button
            for child in self.children:
                if getattr(child, "custom_id", "") == f"remove_{id(_item)}":
                    child.disabled = True
            await interaction.response.edit_message(view=self)
            await self.cog._handle_preempt(self.channel_id, _item)

        button.callback = callback
        return button

    def _render(self) -> str:
        lines = ["**Queued prompts:**"]
        for i, item in enumerate(self.items):
            preview = item.prompt[:80] + ("..." if len(item.prompt) > 80 else "")
            if item.cancelled:
                lines.append(f"~~{i + 1}. `{preview}`~~")
            else:
                lines.append(f"{i + 1}. `{preview}`")
        active = sum(1 for it in self.items if not it.cancelled)
        if active == 0:
            lines.append("\n*All items removed.*")
        return "\n".join(lines)
```

Note: `_make_button` is replaced by `_make_remove_button` (same logic, renamed). Update the old `_make_button` references — there are none outside the class itself.

- [ ] **Step 2: Update `list_queue` command to pass `cog` and `channel_id`**

In the `list_queue` command (around line 1185), replace:
```python
        view = QueueListView(items)
        await interaction.response.send_message(view._render(), view=view)
```

With:
```python
        view = QueueListView(items, cog=self, channel_id=thread_id)
        await interaction.response.send_message(view._render(), view=view)
```

- [ ] **Step 3: Commit**

```bash
git add discord_cogs/claude_prompt.py
git commit -m "feat: add Pre-empt buttons to /list-queue view"
```

---

### Task 5: Manual Testing

No automated test suite exists — test manually by running the bot.

- [ ] **Test 1 — Basic pre-empt via notification:**
  1. Start a long Claude task in a project thread.
  2. Send a second @mention prompt while the first is running.
  3. Verify: "Queued (position 1)" notification appears with **Pre-empt** and **Remove** buttons.
  4. Click **Pre-empt**.
  5. Verify: both buttons are disabled, the current task cancels, the second prompt starts immediately.
  6. Verify: once the second prompt finishes, a "continue the work relayed to prompt: ..." task runs next.

- [ ] **Test 2 — Pre-empt with multiple items in queue:**
  1. Queue 2 prompts while a task runs (queue: [B, C]).
  2. Click **Pre-empt** on B's notification (B is position 1).
  3. Verify execution order: B → "continue A" → C.

- [ ] **Test 3 — Nothing running when Pre-empt clicked:**
  1. Queue a prompt (it starts running immediately).
  2. Wait for the task to finish.
  3. Click **Pre-empt** on the now-stale notification.
  4. Verify: no error, no "continue..." item, nothing explodes.

- [ ] **Test 4 — Pre-empt from `/list-queue`:**
  1. Queue 3 prompts while a task runs.
  2. Run `/list-queue` — verify Pre-empt buttons appear alongside Remove buttons.
  3. Click **Pre-empt #2**.
  4. Verify: item 2 runs next, "continue A" after it, items 1 and 3 follow in order.

- [ ] **Test 5 — Remove button still works on PreemptView:**
  1. Queue a prompt.
  2. Click **Remove** on the notification.
  3. Verify: notification text is struck through, the item is skipped when its turn comes.
