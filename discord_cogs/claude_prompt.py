import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import discord
from discord.ext import commands

from core.discord_streamer import DiscordStreamer
from core.usage_tracker import fmt_time_until
from discord import app_commands
from discord_cogs import has_captain_role, captains_only, REQUIRED_ROLE
from models.feature import Feature

SEND_FILE_PATTERN = re.compile(r"\[send-file:\s*(.+?)\]")
ASK_USER_PATTERN = re.compile(r"\[ask-user:\s*(.+?)\]")
PLAY_AUDIO_PATTERN = re.compile(r"\[play-audio:\s*(.+?)\]", re.DOTALL)

log = logging.getLogger(__name__)


class AskUserButton(discord.ui.Button["AskUserView"]):
    def __init__(self, label: str, index: int, view_id: str) -> None:
        display = label[:77] + "..." if len(label) > 80 else label
        super().__init__(style=discord.ButtonStyle.primary, label=display, custom_id=f"ask_{view_id}_{index}")
        self._answer = label  # preserve full text for the response

    async def callback(self, interaction: discord.Interaction) -> None:
        view: AskUserView = self.view
        view.answer = self._answer
        view.event.set()
        for item in view.children:
            item.disabled = True
            if isinstance(item, AskUserButton):
                if item._answer == self._answer:
                    item.style = discord.ButtonStyle.success  # green
                else:
                    item.style = discord.ButtonStyle.secondary  # grey
        await interaction.response.edit_message(
            content=f"**Claude asked:** {view.question_text}",
            view=view,
        )
        view.stop()


class StopQuestionButton(discord.ui.Button):
    """A secondary 'Stop — I'll clarify' button added to every ask-user interaction."""
    def __init__(self) -> None:
        super().__init__(style=discord.ButtonStyle.secondary, label="Stop — I'll clarify", row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: AskUserView = self.view
        view.answer = None  # None signals "stop the loop"
        view.event.set()
        for item in view.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"**Claude asked:** {view.question_text}\n*Continuing manually...*",
            view=view,
        )
        view.stop()


class AskUserView(discord.ui.View):
    def __init__(self, question_text: str, options: list[str]) -> None:
        import uuid
        super().__init__(timeout=300)
        self.question_text = question_text
        self.answer: str | None = None
        self.event = asyncio.Event()
        self.message: discord.Message | None = None  # set after send
        view_id = uuid.uuid4().hex[:8]
        for i, opt in enumerate(options[:5]):
            self.add_item(AskUserButton(opt.strip(), i, view_id))
        self.add_item(StopQuestionButton())

    async def on_timeout(self) -> None:
        self.answer = "__timeout__"  # distinct from None (stop button)
        self.event.set()
        # Disable all buttons so stale interactions don't show "interaction failed"
        if self.message:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


BUGS_AND_FIXES = "Bugs & Fixes"

from dataclasses import dataclass as _dataclass

@_dataclass
class _PendingFeature:
    name: str
    subdir: str | None = None
    session_id: str | None = None
    total_cost_usd: float = 0.0
    prompt_count: int = 0
    bridgecrew_feature_id: str | None = None


class FeatureGateSelect(discord.ui.Select):
    """Dropdown shown when a prompt arrives with no active feature."""

    def __init__(self, features: list, project_dir, bot):
        options = []
        # Always offer Bugs & Fixes first
        bugs_exists = any(f.name == BUGS_AND_FIXES for f in features)
        bugs_desc = "Resume" if bugs_exists else "Create"
        options.append(discord.SelectOption(
            label=BUGS_AND_FIXES, value=BUGS_AND_FIXES,
            description=f"{bugs_desc} — catch-all for misc work",
        ))
        # Existing features (skip Bugs & Fixes since it's already listed)
        for f in features[:23]:
            if f.name == BUGS_AND_FIXES:
                continue
            desc = f"{f.status}"
            if f.subdir:
                desc += f" · {f.subdir}/"
            options.append(discord.SelectOption(label=f.name, value=f.name, description=desc))
        # Option to create a new feature
        options.append(discord.SelectOption(
            label="Create new feature...", value="__new__",
            description="Type a name for a new feature",
        ))
        super().__init__(placeholder="Select a feature before continuing...", options=options)
        self.project_dir = project_dir
        self.bot = bot
        self.selected_feature = None
        self.event = asyncio.Event()

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]

        if choice == "__new__":
            # Send a modal to collect the feature name
            modal = NewFeatureModal(self)
            await interaction.response.send_modal(modal)
            return

        # Resume or create Bugs & Fixes / existing feature
        from core.state import load_project_state, save_project_state as _save_ps
        _existing_names = set()
        _features_dir = self.project_dir / ".claude" / "features"
        if _features_dir.exists():
            import json as _json_fc
            for _fp in _features_dir.glob("*.json"):
                try:
                    _fd = _json_fc.loads(_fp.read_text())
                    _existing_names.add(_fd.get("name", ""))
                except Exception:
                    pass
        exists = choice in _existing_names

        _state = load_project_state(self.project_dir)
        _state["pending_feature_op"] = {"action": "resume" if exists else "start", "name": choice}
        _state["active_feature_name"] = choice
        _save_ps(self.project_dir, _state)
        self.selected_feature = _PendingFeature(name=choice)

        scope = ""
        action = "Will resume" if exists else "Will start"
        await interaction.response.edit_message(
            content=f"{action} feature **`{self.selected_feature.name}`**{scope}. Processing prompt...",
            view=None,
        )
        self.event.set()


class NewFeatureModal(discord.ui.Modal, title="New Feature"):
    name_input = discord.ui.TextInput(label="Feature name", placeholder="e.g. add-auth-system", max_length=80)

    def __init__(self, gate_select: FeatureGateSelect):
        super().__init__()
        self.gate_select = gate_select

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name_input.value.strip()
        if not name:
            await interaction.response.send_message("Feature name cannot be empty.", ephemeral=True)
            return
        from core.state import load_project_state, save_project_state as _save_ps_modal
        _state = load_project_state(self.gate_select.project_dir)
        _state["pending_feature_op"] = {"action": "start", "name": name}
        _state["active_feature_name"] = name
        _save_ps_modal(self.gate_select.project_dir, _state)
        self.gate_select.selected_feature = _PendingFeature(name=name)
        await interaction.response.edit_message(
            content=f"Started feature **`{name}`**. Processing prompt...",
            view=None,
        )
        self.gate_select.event.set()


class FeatureGateView(discord.ui.View):
    def __init__(self, features: list, project_dir, bot):
        super().__init__(timeout=120)
        self.select = FeatureGateSelect(features, project_dir, bot)
        self.add_item(self.select)

    async def on_timeout(self):
        self.select.event.set()


@dataclass
class QueuedPrompt:
    message: discord.Message
    prompt: str
    project: object  # Project dataclass
    was_queued: bool = False  # True if this prompt waited behind another
    attachments: list = field(default_factory=list)  # discord.Attachment objects
    cancelled: bool = False
    queue_message: object = None  # discord.Message showing the queued notification


class CancelQueuedView(discord.ui.View):
    """Red 'Remove' button shown on queued prompt notifications."""

    def __init__(self, item: QueuedPrompt):
        super().__init__(timeout=None)
        self.item = item

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.item.cancelled = True
        button.disabled = True
        button.label = "Removed"
        original = interaction.message.content if interaction.message else ""
        await interaction.response.edit_message(content=f"~~{original}~~", view=self)


class QueueListView(discord.ui.View):
    """Shows all queued items with per-item Remove buttons."""

    def __init__(self, items: list[QueuedPrompt]):
        super().__init__(timeout=120)
        self.items = items
        for i, item in enumerate(items[:25]):
            self.add_item(self._make_button(i, item))

    def _make_button(self, index: int, item: QueuedPrompt):
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


class ClaudePromptCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # thread_id -> asyncio.Queue of QueuedPrompt
        self._queues: dict[int, asyncio.Queue[QueuedPrompt]] = {}
        # thread_id -> worker task
        self._workers: dict[int, asyncio.Task] = {}
        # thread_id -> human-readable label explaining why the thread is busy (e.g. "completing feature `foo`")
        self._system_run_labels: dict[int, str] = {}

    def has_active_work(self, thread_id: int) -> bool:
        """Check if a thread has an active worker or queued items."""
        if thread_id in self._workers and not self._workers[thread_id].done():
            return True
        queue = self._queues.get(thread_id)
        return queue is not None and not queue.empty()

    def _strip_mention(self, content: str) -> str:
        """Remove bot mention from message content."""
        prompt = content
        for mention_str in [f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>"]:
            prompt = prompt.replace(mention_str, "")
        return prompt.strip()

    def _build_project_context(self, include_paths: bool = False) -> str:
        """Build a context string listing all known projects and their thread IDs.

        If include_paths is True, also includes full filesystem paths for cross-project access.
        """
        from core.state import load_project_state
        pm = self.bot.project_manager
        projects = pm.projects
        if not projects:
            return ""

        lines = ["\n\nThe following projects are available, each with a dedicated Discord thread:"]
        for name, project in sorted(projects.items()):
            project_dir = pm.get_project_dir(project)
            project_state = load_project_state(project_dir)
            session_id = project_state.get("default_session_id")
            import json as _json_tmp
            _features_dir = project_dir / ".claude" / "features"
            _active_feat_name = None
            if _features_dir.exists():
                for _fp in _features_dir.glob("*.json"):
                    try:
                        _fd = _json_tmp.loads(_fp.read_text())
                        if _fd.get("status") == "active":
                            _active_feat_name = _fd.get("name")
                            break
                    except Exception:
                        pass
            feat_str = f" (active feature: {_active_feat_name})" if _active_feat_name else ""
            path_str = f" — path: `{project_dir}`" if include_paths else ""
            lines.append(f"- {name}: thread <#{project.thread_id}>{feat_str}{path_str}")

        if include_paths:
            lines.append(f"\nWorkspace root: `{self.bot.workspace_dir}`")
            global_claude = Path.home() / ".claude"
            lines.append(f"Global Claude config directory: `{global_claude}`")
            lines.append(
                "You have permission to access any of these project directories and the global Claude config. "
                "You must NEVER access or modify any files outside of these listed project directories and "
                "the global Claude config directory — no exceptions."
            )

        return "\n".join(lines)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore own messages unless it's a scheduled order dispatched by the dashboard
        is_self = message.author == self.bot.user
        is_scheduled_dispatch = is_self and "[scheduled-order]" in message.content
        if is_self and not is_scheduled_dispatch:
            return

        # Must mention the bot
        if self.bot.user not in message.mentions:
            return

        # Role gate: only captains can prompt the bot (scheduled orders bypass this)
        if not is_scheduled_dispatch and not has_captain_role(message.author):
            await message.add_reaction("\U0001f512")  # lock emoji
            return

        # Warn if a restart is pending, but still accept the prompt (it will delay the restart)
        if self.bot._restart_requested:
            await message.channel.send(
                "⚠️ A restart is scheduled — your prompt will delay it until this run completes."
            )

        # Strip the bot mention from the prompt
        prompt = self._strip_mention(message.content)

        if not prompt:
            await message.channel.send("Send a prompt after mentioning me.")
            return

        # --- Main channel @mention (not in a thread) ---
        if not isinstance(message.channel, discord.Thread):
            # Only respond in the configured channel
            if message.channel.id != self.bot.project_manager.channel_id:
                return

            channel_id = message.channel.id
            queued = QueuedPrompt(message=message, prompt=prompt, project=None, attachments=list(message.attachments))

            if channel_id not in self._queues:
                self._queues[channel_id] = asyncio.Queue()

            queue = self._queues[channel_id]

            if channel_id in self._workers and not self._workers[channel_id].done():
                queued.was_queued = True
                await queue.put(queued)
                position = queue.qsize()
                await message.add_reaction("\U0001f4cb")
                preview = prompt[:200] + ("…" if len(prompt) > 200 else "")
                view = CancelQueuedView(queued)
                label = self._system_run_labels.get(channel_id)
                label_str = f" — {label}" if label else ""
                queue_msg = await message.channel.send(f"*Queued (position {position}{label_str}):* `{preview}`", view=view)
                queued.queue_message = queue_msg
                return

            await queue.put(queued)
            self._workers[channel_id] = asyncio.create_task(self._worker(channel_id))
            return

        # --- Thread @mention ---
        # Resolve project from thread
        project = self.bot.project_manager.get_project_by_thread(message.channel.id)
        if not project:
            return

        thread_id = message.channel.id
        queued = QueuedPrompt(message=message, prompt=prompt, project=project, attachments=list(message.attachments))

        # Get or create queue for this thread
        if thread_id not in self._queues:
            self._queues[thread_id] = asyncio.Queue()

        queue = self._queues[thread_id]

        # If a worker is already running, queue the prompt
        if thread_id in self._workers and not self._workers[thread_id].done():
            queued.was_queued = True
            await queue.put(queued)
            position = queue.qsize()
            await message.add_reaction("\U0001f4cb")  # clipboard emoji = queued
            preview = prompt[:200] + ("…" if len(prompt) > 200 else "")
            view = CancelQueuedView(queued)
            label = self._system_run_labels.get(thread_id)
            label_str = f" — {label}" if label else ""
            queue_msg = await message.channel.send(f"*Queued (position {position}{label_str}):* `{preview}`", view=view)
            queued.queue_message = queue_msg
            return

        # No worker running — put it in the queue and start the worker
        await queue.put(queued)
        self._workers[thread_id] = asyncio.create_task(self._worker(thread_id))

    async def _collect_answer(self, channel, raw_question: str) -> str:
        """Parse a question string and show a Discord widget to collect the answer."""
        parts = [p.strip() for p in raw_question.split("|")]
        question_text = parts[0]
        options = parts[1:] if len(parts) > 1 else []

        if options:
            view = AskUserView(question_text, options)
            view.message = await channel.send(f"**Claude is asking:** {question_text}", view=view)
            try:
                await asyncio.wait_for(view.event.wait(), timeout=300)
            except asyncio.TimeoutError:
                return "__timeout__"  # on_timeout hasn't run yet; signal directly
            return view.answer  # None = stop button; str = option label
        else:
            stop_view = discord.ui.View(timeout=300)
            stop_event = asyncio.Event()

            stop_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, label="Stop — I'll clarify")

            async def _stop_cb(interaction: discord.Interaction) -> None:
                stop_event.set()
                stop_btn.disabled = True
                await interaction.response.edit_message(
                    content=f"**Claude asked:** {question_text}\n*Continuing manually...*",
                    view=stop_view,
                )
                stop_view.stop()

            stop_btn.callback = _stop_cb
            stop_view.add_item(stop_btn)

            ask_msg = await channel.send(
                f"**Claude is asking:** {question_text}\n*Reply in this channel to answer, or click the button to continue on your own.*",
                view=stop_view,
            )
            try:
                reply_task = asyncio.ensure_future(
                    self.bot.wait_for(
                        "message",
                        check=lambda m: m.channel == channel and not m.author.bot,
                    )
                )
                stop_task = asyncio.ensure_future(stop_event.wait())
                done, pending = await asyncio.wait(
                    [reply_task, stop_task],
                    timeout=300,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                if reply_task in done:
                    return reply_task.result().content
                # Timed out or stop button pressed
                return None
            except Exception:
                return None

    async def _worker(self, thread_id: int) -> None:
        """Process queued prompts for a thread, one at a time."""
        queue = self._queues[thread_id]
        try:
            while not queue.empty():
                item = await queue.get()
                # Skip cancelled items
                if item.cancelled:
                    continue
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
                try:
                    await self._process_prompt(item)
                except Exception as e:
                    log.exception("Error processing queued prompt")
                    try:
                        await item.message.channel.send(f"**Error:** {e}")
                    except discord.HTTPException:
                        pass
        finally:
            # Clean up if the queue is empty
            if queue.empty():
                self._queues.pop(thread_id, None)
                self._workers.pop(thread_id, None)
            # Notify the bot that a worker finished
            await self.bot.notify_worker_done()

    async def _run_stream(self, *, channel, runner, prompt, project_dir, run_dir, thread_id,
                          session_id, resume, feature, persona_content="", persona_name="",
                          workspace_context="", bridgecrew_project_id="", model=None,
                          guild=None, project_name=None,
                          show_prompt_preview: bool = False,
                          is_scheduled: bool = False) -> tuple[str | None, str | None, str]:
        """Run Claude and stream to Discord. Returns (last_session_id, pending_question, response_text).

        project_dir: project root — used for state, token tracking, file security
        run_dir: Claude's working directory — may be a subdirectory when a feature targets one
        model: optional model override (e.g. 'claude-opus-4-6')
        guild/project_name: used for autonomous voice notifications
        show_prompt_preview: include a truncated prompt preview in the Thinking... message
        """
        # Start streaming with a cancel button
        cancel_fn = lambda: runner.cancel(thread_id)
        streamer = DiscordStreamer(channel, on_cancel=cancel_fn)
        await streamer.start(prompt_preview=prompt if show_prompt_preview else "", persona_name=persona_name, session_id=session_id or "", feature_name=feature.name if feature else "")

        # Create a background task to periodically flush the buffer
        async def tick_loop(s=streamer):
            while not s._finalized:
                await asyncio.sleep(0.3)
                await s.tick()

        tick_task = asyncio.create_task(tick_loop())
        full_response = []
        last_session_id = session_id

        import datetime as _dt
        _started_at = _dt.datetime.now(_dt.timezone.utc)

        try:
            async for event in runner.run(
                prompt=prompt,
                project_dir=run_dir,
                thread_id=thread_id,
                session_id=session_id,
                resume=resume,
                persona_content=persona_content,
                workspace_context=workspace_context,
                model=model,
                is_scheduled=is_scheduled,
            ):
                if event.type == "text":
                    print(event.content, end="", flush=True)
                    full_response.append(event.content)
                    await streamer.feed(event.content)
                elif event.type == "cancelled":
                    print("\n[Cancelled]", flush=True)
                    await streamer.send_cancelled()
                    return last_session_id, None, ""
                elif event.type == "error":
                    print(f"\n[Error] {event.content}", flush=True)
                    await streamer.send_error(event.content)
                    if guild:
                        asyncio.create_task(self.bot.voice_notifier.voice_event(
                            guild, "error",
                            f"Claude hit an error in {project_name}." if project_name else "Claude hit an error."
                        ))
                    return last_session_id, None, ""
                elif event.type == "result":
                    if event.session_id:
                        last_session_id = event.session_id
                    print(flush=True)  # final newline after streaming
                    # Persist session_id and model
                    if event.session_id or event.model:
                        from core.state import load_project_state, save_project_state
                        if event.session_id:
                            _state = load_project_state(project_dir)
                            _state["default_session_id"] = event.session_id
                            save_project_state(project_dir, _state)

                        # Save project-level defaults (bot state)
                        state = load_project_state(project_dir)
                        if event.session_id:
                            state["default_session_id"] = event.session_id
                        if event.model:
                            state["model"] = event.model
                        save_project_state(project_dir, state)

                    # Show context health and cost footer
                    if event.input_tokens is not None:
                        context_fill = event.input_tokens
                        context_window = event.context_window or 200_000
                        # CLI may report 200k but newer models support 1M
                        if event.model and ("opus" in event.model or "sonnet" in event.model):
                            context_window = max(context_window, 1_000_000)
                        context_pct = context_fill / context_window * 100

                        if context_pct >= 85:
                            indicator = "\U0001f534"  # red
                            warning = "\n**\u26a0\ufe0f Context window critically full — wrap up this feature now!**"
                            if guild:
                                asyncio.create_task(self.bot.voice_notifier.voice_event(
                                    guild, "context_critical",
                                    f"Context window critically full for {project_name}. Wrap up soon." if project_name
                                    else "Context window critically full. Wrap up soon."
                                ))
                        elif context_pct >= 70:
                            indicator = "\U0001f7e0"  # orange
                            warning = "\n**\u26a0\ufe0f Context window getting large — consider finishing soon.**"
                        elif context_pct >= 50:
                            indicator = "\U0001f7e1"  # yellow
                            warning = "\n*Context window over 50% — keep an eye on it.*"
                        else:
                            indicator = "\U0001f7e2"  # green
                            warning = ""

                        # Accumulate cost for the session/feature (still tracked, just not shown)
                        _out_tokens = event.output_tokens or 0
                        _cost = event.cost_usd or 0.0
                        if feature and session_id:
                            from core.mcp_client import post_cost as _post_cost
                            asyncio.create_task(_post_cost(
                                project_dir,
                                session_id=session_id,
                                cost_usd=_cost,
                                input_tokens=context_fill,
                                output_tokens=_out_tokens,
                            ))
                        totals = {
                            "total_cost_usd": (getattr(feature, "total_cost_usd", 0.0) or 0.0) + _cost,
                            "total_input_tokens": context_fill,
                            "total_output_tokens": _out_tokens,
                            "prompt_count": (getattr(feature, "prompt_count", 0) or 0) + 1,
                        }

                        # Report cost to BridgeCrew dashboard (fire-and-forget, non-blocking)
                        if event.cost_usd:
                            import asyncio as _asyncio
                            from core.bridgecrew_client import report_cost as _report_cost
                            _feature_bc_id = f"{project_name}:{feature.name}" if (project_name and feature) else ""
                            _asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda: _report_cost(
                                    project_id=bridgecrew_project_id,
                                    session_id=last_session_id or "",
                                    model=event.model or "",
                                    cost_usd=event.cost_usd,
                                    input_tokens=context_fill,
                                    output_tokens=event.output_tokens or 0,
                                    feature_id=_feature_bc_id,
                                    started_at=_started_at,
                                    completed_at=_dt.datetime.now(_dt.timezone.utc),
                                ),
                            )

                        # Build compact footer: context % + daily/weekly usage + reset time
                        from core.usage_tracker import get_usage_summary, fmt_tokens
                        reset_str = ""
                        usage_str = ""
                        try:
                            usage = get_usage_summary()
                            cur_out = event.output_tokens or 0
                            five_h_out = usage.five_hour.output_tokens + cur_out
                            week_out = usage.this_week.output_tokens + cur_out
                            usage_str = f" · 5h {fmt_tokens(five_h_out)} · week {fmt_tokens(week_out)}"
                        except Exception:
                            pass
                        from datetime import datetime, timezone as _tz

                        def _rate_label(rtype: str) -> str:
                            if "five_hour" in rtype:
                                return "5h"
                            if "seven_day" in rtype:
                                return "7d"
                            if "daily" in rtype:
                                return "daily"
                            return rtype

                        reset_str = ""
                        if event.rate_limits:
                            reset_parts = []
                            for rtype, resets_at in event.rate_limits.items():
                                resets_dt = datetime.fromtimestamp(resets_at, tz=_tz.utc)
                                reset_parts.append(f"{_rate_label(rtype)} ↺ {fmt_time_until(resets_dt)}")
                            if reset_parts:
                                reset_str = " · " + " · ".join(reset_parts)

                        footer_line = f"*{indicator} ctx {context_pct:.1f}%{usage_str}{reset_str}*"

                        # Session/feature line: model, feature, cumulative cost, prompt count
                        model_str = f"`{event.model}` · " if event.model else ""
                        session_label = f"`{feature.name}`" if feature else "session"
                        cost_str = f"${totals['total_cost_usd']:.4f} · " if totals["total_cost_usd"] else ""
                        session_id_str = f" · `{last_session_id[:8]}`" if last_session_id else ""
                        session_line = f"*{model_str}{session_label} · {cost_str}{totals['prompt_count']} prompts{session_id_str}*"

                        await streamer.feed(
                            f"\n\n---\n"
                            f"{footer_line}\n"
                            f"{session_line}"
                            f"{warning}"
                        )

            # Extract markers from the full response text BEFORE finalize() so we can
            # strip them from streamer.current_text first.  finalize() calls
            # current_message.edit(content=current_text), and discord.py does NOT update
            # the Python .content attribute on edit — so if finalize runs first, the
            # subsequent strip loop reads stale .content values and misses the marker,
            # leaving [ask-user: ...] visible in the Discord message.
            response_text = "".join(full_response)
            pending_files = SEND_FILE_PATTERN.findall(response_text)
            pending_audio = PLAY_AUDIO_PATTERN.findall(response_text)
            pending_question = None
            ask_match = ASK_USER_PATTERN.search(response_text)
            if ask_match:
                pending_question = ask_match.group(1)

            # Strip markers from the streamer's internal text so finalize() writes clean
            # content to Discord (no visible [ask-user: ...] / [send-file: ...] etc.)
            if pending_files or pending_question or pending_audio:
                ct = streamer.current_text
                ct = SEND_FILE_PATTERN.sub("", ct)
                ct = ASK_USER_PATTERN.sub("", ct)
                ct = PLAY_AUDIO_PATTERN.sub("", ct)
                streamer.current_text = ct.strip() or "\u200b"

            await streamer.finalize()

            # Autonomous run-complete notification
            if guild:
                asyncio.create_task(self.bot.voice_notifier.voice_event(
                    guild, "run_complete",
                    f"Claude has finished in {project_name}." if project_name else "Claude has finished."
                ))

            # Also strip markers from any earlier Discord messages (multi-message responses
            # where the marker landed in a non-current message, or messages sent before the
            # final flush).
            if pending_files or pending_question or pending_audio:
                for msg in streamer.all_messages:
                    try:
                        if msg.content:
                            cleaned = SEND_FILE_PATTERN.sub("", msg.content)
                            cleaned = ASK_USER_PATTERN.sub("", cleaned)
                            cleaned = PLAY_AUDIO_PATTERN.sub("", cleaned)
                            if cleaned != msg.content:
                                await msg.edit(content=cleaned.strip() or "\u200b")
                    except discord.HTTPException:
                        pass

            # Fire [play-audio:] prompts as background tasks
            for audio_prompt in pending_audio:
                if guild:
                    asyncio.create_task(
                        self.bot.voice_notifier.play_prompt(guild, audio_prompt.strip())
                    )

            # Attach any files that were referenced
            for rel_path in pending_files:
                rel_path = rel_path.strip()
                file_path = (run_dir / rel_path).resolve()
                # Security: must be within project directory or workspace
                workspace = self.bot.workspace_dir.resolve()
                allowed = False
                try:
                    file_path.relative_to(project_dir.resolve())
                    allowed = True
                except ValueError:
                    pass
                if not allowed:
                    try:
                        file_path.relative_to(workspace)
                        allowed = True
                    except ValueError:
                        pass
                if not allowed:
                    await channel.send(f"Skipped `{rel_path}` — outside workspace directory.")
                    continue
                if not file_path.exists() or not file_path.is_file():
                    await channel.send(f"Skipped `{rel_path}` — file not found.")
                    continue
                size_mb = file_path.stat().st_size / (1024 * 1024)
                if size_mb > 25:
                    await channel.send(f"Skipped `{rel_path}` — too large ({size_mb:.1f}MB).")
                    continue
                try:
                    await channel.send(f"📎 `{rel_path}`", file=discord.File(str(file_path)))
                except discord.HTTPException as e:
                    await channel.send(f"Failed to send `{rel_path}`: {e}")

            return last_session_id, pending_question, response_text

        except Exception as e:
            log.exception("Error during Claude stream")
            await streamer.send_error(str(e))
            return last_session_id, None, ""
        finally:
            # Always clean up the stop button
            if not streamer._finalized:
                await streamer.finalize()
            tick_task.cancel()
            try:
                await tick_task
            except asyncio.CancelledError:
                pass

    async def run_feature_summary_prompt(self, channel, project, feature) -> None:
        """Send a prompt to Claude to create a feature doc and update CLAUDE.md.
        Called after a feature is marked complete. Registers itself as a worker so
        that messages arriving during the summary are queued (not errored) and
        processed automatically once the summary finishes.
        """
        project_dir = self.bot.project_manager.get_project_dir(project)

        # Feature doc lives under the subdir's own features/ folder, or the project root's
        if feature.subdir:
            feature_doc_path = f"{feature.subdir}/features/{feature.name}.md"
        else:
            feature_doc_path = f"features/{feature.name}.md"

        prompt = (
            f"The feature **`{feature.name}`** has just been marked as completed. "
            f"Please do the following two tasks:\n\n"
            f"1. Create `{feature_doc_path}` (relative to the project root) summarising this feature. Include:\n"
            f"   - What the feature does / what problem it solves\n"
            f"   - Key files changed or created\n"
            f"   - Any important design decisions or tradeoffs\n"
            f"   - Known limitations or follow-up items (if any)\n\n"
            f"2. Open `CLAUDE.md` at the project root and add or update a `## Features` section "
            f"that lists every feature with a one-sentence description and a reference to its doc file. "
            f"Format each entry as a bullet:\n"
            f"   - **{feature.name}**: One sentence description. See `{feature_doc_path}`.\n\n"
            f"Do NOT use the @ symbol when referencing files in CLAUDE.md — write plain paths only. "
            f"Preserve all existing content in CLAUDE.md outside the Features section. "
            f"Keep both files concise."
        )

        thread_id = channel.id

        # Register as a worker so messages arriving during the summary queue correctly
        # instead of hitting the "already running" error from the runner.
        if thread_id not in self._queues:
            self._queues[thread_id] = asyncio.Queue()
        self._system_run_labels[thread_id] = f"completing feature **`{feature.name}`**"

        async def _run():
            try:
                await self._run_stream(
                    channel=channel,
                    runner=self.bot.claude_runner,
                    prompt=prompt,
                    project_dir=project_dir,
                    run_dir=project_dir,
                    thread_id=thread_id,
                    session_id=feature.session_id,
                    resume=True,
                    feature=feature,
                    # No activity reporting for internal summary prompts
                )
            finally:
                self._system_run_labels.pop(thread_id, None)
            # Drain any messages that arrived during the summary
            await self._worker(thread_id)

        self._workers[thread_id] = asyncio.create_task(_run())

    async def run_feature_init_session(
        self,
        channel,
        project_dir,
        feature_name: str,
        action: str,
        subdir: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Start (or resume) a Claude session so it registers with the MCP server.

        Sends a minimal prompt instructing Claude to call feature_start or feature_resume
        via the MCP tool. _run_stream automatically persists the resulting session_id
        to default_session_id in project state.

        action: "start" or "resume"
        subdir: optional subdirectory scope (start only)
        session_id: existing CLI session ID to resume (leave None for a fresh session)
        """
        thread_id = channel.id

        if action == "start":
            prompt = f"Reply: 'Ready to work on **`{feature_name}`**.' Nothing else."
        else:
            prompt = f"Reply: 'Resumed **`{feature_name}`**.' Nothing else."

        if thread_id not in self._queues:
            self._queues[thread_id] = asyncio.Queue()
        label = (
            f"starting feature **`{feature_name}`**"
            if action == "start"
            else f"resuming feature **`{feature_name}`**"
        )
        self._system_run_labels[thread_id] = label

        async def _run():
            try:
                last_sid, _, _ = await self._run_stream(
                    channel=channel,
                    runner=self.bot.claude_runner,
                    prompt=prompt,
                    project_dir=project_dir,
                    run_dir=project_dir,
                    thread_id=thread_id,
                    session_id=session_id,
                    resume=session_id is not None,
                    feature=None,
                )
            finally:
                self._system_run_labels.pop(thread_id, None)
            # Register the real CLI session UUID with the MCP server.
            # Claude doesn't know its own UUID, so the bot does this via REST.
            if last_sid:
                from core.mcp_client import (
                    start_feature_session as _start_fs,
                    resume_feature_session as _resume_fs,
                )
                if action == "start":
                    await _start_fs(project_dir, last_sid, feature_name)
                else:
                    await _resume_fs(project_dir, last_sid, feature_name)
                # Register new features in the dashboard (start only — resume reuses existing record)
                if action == "start":
                    _project = self.bot.project_manager.get_project_by_thread(channel.id)
                    if _project:
                        from core.state import load_project_state as _lps_init
                        from core.bridgecrew_client import report_feature_started as _rfs
                        _state_init = _lps_init(project_dir)
                        _bc_project_id = _state_init.get("bridgecrew_project_id", "")
                        _composite_id = f"{_project.name}:{feature_name}"
                        _loop = asyncio.get_event_loop()
                        await _loop.run_in_executor(
                            None,
                            lambda: _rfs(
                                project_id=_bc_project_id,
                                feature_name=feature_name,
                                session_id=last_sid,
                                feature_id=_composite_id,
                            ),
                        )
            await self._worker(thread_id)

        self._workers[thread_id] = asyncio.create_task(_run())

    async def run_feature_context_reset_session(
        self,
        channel,
        project_dir,
        feature_name: str,
        old_session_id: str,
    ) -> None:
        """Capture a milestone snapshot of current work, then start a fresh feature session.

        Called by /reset-context when a feature is active. Uses the old session so Claude
        has full context for the summary, then starts a brand-new session that resumes the
        feature — giving a clean context window with the milestone recorded.
        """
        thread_id = channel.id

        milestone_prompt = (
            f"The user is resetting the context window for feature **`{feature_name}`**. "
            f"Before the session is cleared, please capture a milestone snapshot:\n\n"
            f"1. Review recent git history (`git log --oneline -20`) and any relevant changed "
            f"files to understand what has been accomplished so far in this session.\n"
            f"2. Call `feature_add_milestone(project_dir='{project_dir}', "
            f"session_id='{old_session_id}', text='<your milestone summary>')` with a concise "
            f"but thorough summary covering: what was built or changed, key files touched, "
            f"and any important design decisions or pending follow-ups.\n\n"
            f"Reply with 'Milestone recorded for **`{feature_name}`**.' when done."
        )

        resume_prompt = f"Reply: 'Fresh context ready — resumed **`{feature_name}`**.' Nothing else."

        if thread_id not in self._queues:
            self._queues[thread_id] = asyncio.Queue()
        self._system_run_labels[thread_id] = f"capturing milestone for **`{feature_name}`**"

        async def _run():
            try:
                # Step 1: snapshot on old session
                await self._run_stream(
                    channel=channel,
                    runner=self.bot.claude_runner,
                    prompt=milestone_prompt,
                    project_dir=project_dir,
                    run_dir=project_dir,
                    thread_id=thread_id,
                    session_id=old_session_id,
                    resume=True,
                    feature=None,
                )
            finally:
                self._system_run_labels.pop(thread_id, None)

            # Release ALL active session locks for this feature so the fresh session can
            # resume without conflict.  We use abandon_feature_sessions (by feature name)
            # rather than complete_feature (by session ID) because the MCP server's
            # registered session ID may differ from the project-state default_session_id
            # (e.g. if Claude used a context-derived string when calling feature_resume).
            # complete_feature would silently no-op in that case, leaving the lock in place.
            from core.mcp_client import abandon_feature_sessions as _abandon_sessions
            await _abandon_sessions(project_dir, feature_name)

            # Step 2: start fresh session and re-register the feature
            self._system_run_labels[thread_id] = f"resuming feature **`{feature_name}`**"
            try:
                last_sid_2, _, _ = await self._run_stream(
                    channel=channel,
                    runner=self.bot.claude_runner,
                    prompt=resume_prompt,
                    project_dir=project_dir,
                    run_dir=project_dir,
                    thread_id=thread_id,
                    session_id=None,   # fresh session
                    resume=False,
                    feature=None,
                )
            finally:
                self._system_run_labels.pop(thread_id, None)

            # Register the fresh session's real CLI UUID with the MCP server
            if last_sid_2:
                from core.mcp_client import resume_feature_session as _resume_fs
                await _resume_fs(project_dir, last_sid_2, feature_name)

            await self._worker(thread_id)

        self._workers[thread_id] = asyncio.create_task(_run())

    async def run_feature_complete_session(
        self,
        channel,
        project_dir,
        feature_name: str,
        session_id: str,
    ) -> None:
        """Resume the active Claude session, prompt it to summarise and call feature_complete.

        Claude generates the summary from context, calls the feature_complete MCP tool
        (which writes features/<name>.md and unregisters the session), then updates
        CLAUDE.md. After the session finishes the MCP store has no active feature, so
        the next user prompt will trigger the feature gate.
        """
        thread_id = channel.id
        feature_doc_path = f"features/{feature_name}.md"
        prompt = (
            f"The user has completed feature **`{feature_name}`**. Please do the following:\n\n"
            f"1. Review recent git history (`git log --oneline -20`) and any relevant changed "
            f"files to understand what was built.\n"
            f"2. Call `feature_complete(project_dir='{project_dir}', session_id='{session_id}', "
            f"summary='<your summary>')` with a concise but thorough summary covering: what the "
            f"feature does, key files changed, and any important design decisions.\n"
            f"3. Open `CLAUDE.md` at the project root and add or update the `## Features` section "
            f"with a bullet for this feature:\n"
            f"   `- **{feature_name}**: One sentence description. See `{feature_doc_path}`.\n\n"
            f"Preserve all existing CLAUDE.md content outside the Features section. "
            f"Reply with 'Feature **`{feature_name}`** completed.' when done."
        )
        if thread_id not in self._queues:
            self._queues[thread_id] = asyncio.Queue()
        self._system_run_labels[thread_id] = f"completing feature **`{feature_name}`**"

        async def _run():
            try:
                last_sid, _, _ = await self._run_stream(
                    channel=channel,
                    runner=self.bot.claude_runner,
                    prompt=prompt,
                    project_dir=project_dir,
                    run_dir=project_dir,
                    thread_id=thread_id,
                    session_id=session_id,
                    resume=True,
                    feature=None,
                )
                # Fallback: ensure the feature is marked completed in the MCP store even
                # if Claude failed to call feature_complete via the MCP tool.  If Claude
                # already called it the session is unregistered and this is a no-op.
                from core.mcp_client import complete_feature as _complete_feature
                _sid = last_sid or session_id
                if _sid:
                    await _complete_feature(project_dir, _sid)
                # Clear the active feature name from project state so the gate fires
                # correctly on the next prompt (asking the user to pick a new feature).
                from core.state import load_project_state as _lps_c, save_project_state as _sps_c
                _cstate = _lps_c(project_dir)
                _cstate.pop("active_feature_name", None)
                _cstate.pop("pending_feature_op", None)
                _sps_c(project_dir, _cstate)
                # Report completion + markdown to dashboard
                _project = self.bot.project_manager.get_project_by_thread(channel.id)
                if _project:
                    from pathlib import Path as _Path
                    from core.mcp_client import get_features as _gf
                    from core.bridgecrew_client import report_feature_completed as _rfc
                    _composite_id = f"{_project.name}:{feature_name}"
                    _md_path = _Path(project_dir) / "features" / f"{feature_name}.md"
                    _md_content = None
                    try:
                        _md_content = _md_path.read_text(encoding="utf-8")
                    except Exception:
                        pass
                    _feats = await _gf(project_dir)
                    _feat_data = next((f for f in _feats if f.get("name") == feature_name), {})
                    _loop = asyncio.get_event_loop()
                    await _loop.run_in_executor(
                        None,
                        lambda md=_md_content, fd=_feat_data, cid=_composite_id: _rfc(
                            feature_id=cid,
                            summary=fd.get("summary", ""),
                            total_cost_usd=fd.get("total_cost_usd", 0.0),
                            total_input_tokens=fd.get("total_input_tokens", 0),
                            total_output_tokens=fd.get("total_output_tokens", 0),
                            markdown_content=md,
                        ),
                    )
            finally:
                self._system_run_labels.pop(thread_id, None)
            await self._worker(thread_id)

        self._workers[thread_id] = asyncio.create_task(_run())

    @captains_only()
    @app_commands.command(name="clear-work", description="Remove all queued prompts for this thread")
    async def clear_work(self, interaction: discord.Interaction) -> None:
        thread_id = interaction.channel_id
        queue = self._queues.get(thread_id)
        if not queue or queue.empty():
            await interaction.response.send_message("Nothing queued.", ephemeral=True)
            return
        count = 0
        while not queue.empty():
            try:
                item = queue.get_nowait()
                item.cancelled = True
                count += 1
            except asyncio.QueueEmpty:
                break
        await interaction.response.send_message(f"Cleared **{count}** queued prompt(s).")

    @captains_only()
    @app_commands.command(name="list-queue", description="Show all queued prompts with remove buttons")
    async def list_queue(self, interaction: discord.Interaction) -> None:
        thread_id = interaction.channel_id
        queue = self._queues.get(thread_id)
        if not queue or queue.empty():
            await interaction.response.send_message("Nothing queued.", ephemeral=True)
            return
        # Peek at queue items without dequeueing
        items = [item for item in list(queue._queue) if not item.cancelled]
        if not items:
            await interaction.response.send_message("Nothing queued.", ephemeral=True)
            return
        view = QueueListView(items)
        await interaction.response.send_message(view._render(), view=view)

    @staticmethod
    async def _download_attachments(attachments: list, project_dir: Path, message_id: int) -> list[Path]:
        """Download Discord attachments to a staging directory. Returns list of file paths."""
        if not attachments:
            return []
        staging_dir = project_dir / ".discord_uploads" / str(message_id)
        staging_dir.mkdir(parents=True, exist_ok=True)
        downloaded = []
        for att in attachments:
            try:
                file_path = staging_dir / att.filename
                data = await att.read()
                file_path.write_bytes(data)
                downloaded.append(file_path)
            except Exception as e:
                log.warning("Failed to download attachment %s: %s", att.filename, e)
        return downloaded

    @staticmethod
    def _cleanup_attachments(project_dir: Path, message_id: int) -> None:
        """Remove the staging directory for downloaded attachments."""
        import shutil
        staging_dir = project_dir / ".discord_uploads" / str(message_id)
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)

    async def _process_prompt(self, item: QueuedPrompt) -> None:
        message = item.message
        prompt = item.prompt
        project = item.project
        runner = self.bot.claude_runner

        # Detect scheduled-order marker and strip it from the prompt
        import re as _re
        is_scheduled = bool(_re.search(r"\[scheduled-order\]", prompt, _re.IGNORECASE))
        scheduled_persona_id = ""
        if is_scheduled:
            persona_match = _re.search(r"\[persona:([^\]]+)\]", prompt, _re.IGNORECASE)
            if persona_match:
                scheduled_persona_id = persona_match.group(1).strip()
            prompt = _re.sub(r"\s*\[scheduled-order\]\s*", "", prompt, flags=_re.IGNORECASE)
            prompt = _re.sub(r"\s*\[persona:[^\]]*\]\s*", "", prompt, flags=_re.IGNORECASE)
            prompt = prompt.strip()

        # Main channel queries run against the bot's own project directory
        if project is None:
            project_dir = Path(__file__).resolve().parent.parent
        else:
            project_dir = self.bot.project_manager.get_project_dir(project)

        # Load project state early — needed to find the active feature by session_id
        from core.state import load_project_state
        state = load_project_state(project_dir)
        default_session_id = state.get("default_session_id")
        preferred_model = state.get("preferred_model")

        # Get active feature for this Discord session by matching the last known session_id
        _feature_needs_mcp_registration = False
        if project and default_session_id:
            from core.mcp_client import get_session_feature as _get_sf
            _feat_dict = await _get_sf(project_dir, default_session_id)
            feature = Feature.from_dict(_feat_dict["name"], _feat_dict) if _feat_dict else None
        else:
            feature = None

        # Fallback: if MCP has no active feature, use the state-stored active feature name.
        # This covers the case where the gate was used to pick a feature but feature_start/
        # feature_resume was never called (so MCP doesn't know about the session yet).
        if project and not feature:
            _active_feat_name = state.get("active_feature_name")
            if _active_feat_name:
                import json as _json_af, re as _re_af
                _snake = _active_feat_name.lower().replace("&", "and")
                _snake = _re_af.sub(r"[-\s]+", "_", _snake)
                _snake = _re_af.sub(r"[^a-z0-9_]", "", _snake)
                _snake = _re_af.sub(r"_+", "_", _snake).strip("_") or "unnamed"
                _feat_file = project_dir / ".claude" / "features" / f"{_snake}.json"
                if _feat_file.exists():
                    try:
                        _fd = _json_af.loads(_feat_file.read_text(encoding="utf-8"))
                        if _fd.get("status", "active") == "active":
                            feature = Feature.from_dict(_active_feat_name, _fd)
                        else:
                            # Feature was completed/discarded — clear the stale state entry
                            state.pop("active_feature_name", None)
                            from core.state import save_project_state as _sps_clear
                            _sps_clear(project_dir, state)
                    except Exception:
                        pass
                if not feature and _active_feat_name:
                    # Feature file doesn't exist yet (brand-new feature picked from gate)
                    feature = Feature(name=_active_feat_name)
                if feature:
                    _feature_needs_mcp_registration = True

        # Gate: require a feature selection for project threads
        if project and not feature:
            from core.mcp_client import get_features as _get_feats
            _raw_feats = await _get_feats(project_dir)
            features = [Feature.from_dict(f["name"], f) for f in _raw_feats if f.get("name")]
            view = FeatureGateView(features, project_dir, self.bot)
            from core.discord_streamer import discord_retry
            gate_msg = await discord_retry(message.channel.send(
                "No active feature — pick one before I start working:",
                view=view,
            ))
            self._system_run_labels[message.channel.id] = "selecting a feature"
            try:
                await view.select.event.wait()
            finally:
                self._system_run_labels.pop(message.channel.id, None)
            feature = view.select.selected_feature
            if not feature:
                await gate_msg.edit(content="*Timed out — prompt cancelled.*", view=None)
                return
            # Feature was just selected from the gate — MCP doesn't know about this session yet.
            # Reload state because the gate callback saved active_feature_name.
            state = load_project_state(project_dir)
            default_session_id = state.get("default_session_id")
            _feature_needs_mcp_registration = True

        # Prefer the most-recent persisted session (default_session_id) over the session_id
        # recorded in the MCP feature file — the latter can be stale when the runner returns
        # a new session_id after each --resume call.  Fall back to feature.session_id when
        # no default is available (e.g. very first prompt for this project).
        session_id = default_session_id or (feature.session_id if feature else None)
        resume = bool(session_id)

        # Fetch persona content and BridgeCrew dashboard project ID
        bridgecrew_project_id = state.get("bridgecrew_project_id", "")
        from core.bridgecrew_client import get_project_prompt as _get_prompt, get_prompt_by_id as _get_prompt_by_id, report_activity as _report_activity
        if scheduled_persona_id:
            persona_content, persona_name = _get_prompt_by_id(scheduled_persona_id)
        else:
            persona_content, persona_name = _get_prompt(bridgecrew_project_id) if bridgecrew_project_id else ("", "")

        # Report the user's message to the activity feed (fire-and-forget)
        if bridgecrew_project_id:
            loop = asyncio.get_event_loop()
            loop.run_in_executor(
                None,
                lambda: _report_activity(
                    project_id=bridgecrew_project_id,
                    role="user",
                    author=str(message.author),
                    content=prompt,
                    feature_name=feature.name if feature else None,
                ),
            )

        # If the active feature targets a subdirectory, use that as Claude's working dir
        run_dir = project_dir
        if feature and feature.subdir:
            candidate = project_dir / feature.subdir
            if candidate.is_dir():
                run_dir = candidate

        # Download any attachments and append file paths to the prompt
        downloaded_files = await self._download_attachments(item.attachments, project_dir, message.id)
        if downloaded_files:
            prompt += "\n\nThe following files were attached to this message:\n"
            for fp in downloaded_files:
                prompt += f"- {fp.resolve()}\n"

        # Snapshot full diff state so we can detect any changes (committed or not)
        is_self = self.bot.is_self_project(project_dir)
        diff_snapshot = None
        if is_self:
            try:
                diff_proc, head_proc = await asyncio.gather(
                    asyncio.create_subprocess_exec(
                        "git", "diff", "HEAD",
                        cwd=str(project_dir),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    ),
                    asyncio.create_subprocess_exec(
                        "git", "rev-parse", "HEAD",
                        cwd=str(project_dir),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    ),
                )
                diff_out, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=5)
                head_out, _ = await asyncio.wait_for(head_proc.communicate(), timeout=5)
                diff_snapshot = (head_out.decode().strip(), diff_out.decode())
            except Exception:
                pass

        workspace_context = self._build_project_context(include_paths=True)

        # Determine which MCP registration action to take after the run.
        # The bot registers the session via REST using the real CLI UUID, so Claude
        # no longer needs a prompt prefix instructing it to call feature_start/resume.
        _reg_action: str | None = None
        if _feature_needs_mcp_registration and feature:
            import re as _re_reg
            _snake_reg = feature.name.lower().replace("&", "and")
            _snake_reg = _re_reg.sub(r"[-\s]+", "_", _snake_reg)
            _snake_reg = _re_reg.sub(r"[^a-z0-9_]", "", _snake_reg)
            _snake_reg = _re_reg.sub(r"_+", "_", _snake_reg).strip("_") or "unnamed"
            _feat_file_reg = project_dir / ".claude" / "features" / f"{_snake_reg}.json"
            _reg_action = "resume" if _feat_file_reg.exists() else "start"

        print(f"\n{'='*60}\n[{message.author}] {prompt}\n{'='*60}", flush=True)

        guild = message.guild
        project_name = project.name if project else None

        # Run the initial prompt
        last_session_id, pending_question, response_text = await self._run_stream(
            channel=message.channel,
            runner=runner,
            prompt=prompt,
            project_dir=project_dir,
            run_dir=run_dir,
            thread_id=message.channel.id,
            session_id=session_id,
            resume=resume,
            feature=feature,
            persona_content=persona_content,
            persona_name=persona_name,
            workspace_context=workspace_context,
            bridgecrew_project_id=bridgecrew_project_id,
            model=preferred_model,
            guild=guild,
            project_name=project_name,
            show_prompt_preview=item.was_queued,
            is_scheduled=is_scheduled,
        )

        # Register the real CLI session UUID with the MCP server when needed.
        # Done after _run_stream so we have the actual UUID, not a Claude-guessed string.
        if _reg_action and feature and last_session_id:
            from core.mcp_client import (
                start_feature_session as _start_fs,
                resume_feature_session as _resume_fs,
            )
            if _reg_action == "start":
                await _start_fs(project_dir, last_session_id, feature.name)
            else:
                await _resume_fs(project_dir, last_session_id, feature.name)

        # Report Claude's response to the activity feed (fire-and-forget)
        if bridgecrew_project_id and response_text:
            loop = asyncio.get_event_loop()
            loop.run_in_executor(
                None,
                lambda: _report_activity(
                    project_id=bridgecrew_project_id,
                    role="assistant",
                    author="Claude",
                    content=response_text,
                    feature_name=feature.name if feature else None,
                ),
            )

        _STOP_PHRASES = (
            "i'll handle it", "i will handle it", "stop", "stop — i'll clarify", "i'll clarify",
            "let me handle", "i'll take care", "i will take care",
            "let me modify", "i'll modify", "i will modify",
            "i have notes", "i'll update", "i will update",
            "i'll continue", "i will continue",
        )

        # Question loop: collect answer, continue session, repeat if needed
        while pending_question and last_session_id:
            # Open-ended questions (no options) end the prompt sequence —
            # the user replies in the thread naturally, which starts a new prompt.
            if "|" not in pending_question:
                break

            answer = await self._collect_answer(message.channel, pending_question)
            print(f"[Answer] {answer!r}", flush=True)

            # Explicit opt-out phrases stop the loop so the user can continue manually
            if answer and answer.strip().lower().rstrip(".!") in _STOP_PHRASES:
                break

            # Stop button clicked — terminate immediately, user will clarify manually
            if answer is None:
                break

            # Timeout — proceed with best guess
            if answer == "__timeout__":
                answer = "No answer provided — use your best judgment and proceed."

            last_session_id, pending_question, _ = await self._run_stream(
                channel=message.channel,
                runner=runner,
                prompt=answer,
                project_dir=project_dir,
                run_dir=run_dir,
                thread_id=message.channel.id,
                session_id=last_session_id,
                resume=True,
                feature=feature,
                persona_content=persona_content,
                persona_name=persona_name,
                workspace_context=workspace_context,
                bridgecrew_project_id=bridgecrew_project_id,
                model=preferred_model,
                guild=guild,
                project_name=project_name,
            )

        # Clean up downloaded attachments
        if downloaded_files:
            self._cleanup_attachments(project_dir, message.id)

        # Auto-restart if the bot's own code was actually modified
        if is_self and diff_snapshot is not None:
            try:
                old_head, old_diff = diff_snapshot
                diff_proc, head_proc = await asyncio.gather(
                    asyncio.create_subprocess_exec(
                        "git", "diff", "HEAD",
                        cwd=str(project_dir),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    ),
                    asyncio.create_subprocess_exec(
                        "git", "rev-parse", "HEAD",
                        cwd=str(project_dir),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    ),
                )
                diff_out, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=5)
                head_out, _ = await asyncio.wait_for(head_proc.communicate(), timeout=5)
                head = head_out.decode().strip()
                uncommitted = diff_out.decode()
                if head != old_head or uncommitted != old_diff:
                    await self.bot.request_restart(channel=message.channel)
            except Exception:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ClaudePromptCog(bot))
