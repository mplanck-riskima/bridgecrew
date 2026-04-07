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
        self.answer = None  # None signals "stop the loop"
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
        fm = self.bot.feature_manager

        if choice == "__new__":
            # Send a modal to collect the feature name
            modal = NewFeatureModal(self)
            await interaction.response.send_modal(modal)
            return

        # Resume or create Bugs & Fixes / existing feature
        existing = fm.list_features(self.project_dir)
        exists = any(f.name == choice for f in existing)

        if exists:
            self.selected_feature = fm.resume_feature(self.project_dir, choice)
        else:
            self.selected_feature = fm.start_feature(self.project_dir, choice)

        scope = f" in `{self.selected_feature.subdir}/`" if self.selected_feature.subdir else ""
        action = "Resumed" if exists else "Started"
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
        fm = self.gate_select.bot.feature_manager
        self.gate_select.selected_feature = fm.start_feature(self.gate_select.project_dir, name)
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
            feature = self.bot.feature_manager.get_current_feature(project_dir, session_id=session_id)
            feat_str = f" (active feature: {feature.name})" if feature else ""
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
                pass
            return view.answer or "No response (timed out)"
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
        await streamer.start(prompt_preview=prompt if show_prompt_preview else "", persona_name=persona_name)

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
                        from core.state import load_project_state, save_project_state, load_feature_index, save_feature_index, load_feature_file, save_feature_file

                        if event.session_id and feature:
                            feat_data = load_feature_file(project_dir, feature.name)
                            if feat_data:
                                old_session_id = feat_data.get("session_id")
                                feat_data["session_id"] = event.session_id
                                feat_data["name"] = feature.name
                                # Update the sessions array entry so session_id-based lookup works
                                if old_session_id and old_session_id != event.session_id:
                                    for sess in feat_data.get("sessions", []):
                                        if sess.get("session_id") == old_session_id:
                                            sess["session_id"] = event.session_id
                                            break
                                save_feature_file(project_dir, feature.name, feat_data)
                                # Update index sessions routing table
                                index = load_feature_index(project_dir)
                                sessions = index.setdefault("sessions", {})
                                if old_session_id and old_session_id in sessions:
                                    sessions[event.session_id] = sessions.pop(old_session_id)
                                elif event.session_id not in sessions:
                                    sessions[event.session_id] = {
                                        "feature": feature.name,
                                        "source": "discord",
                                        "started_at": feat_data.get("started_at", ""),
                                    }
                                save_feature_index(project_dir, index)

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
                        totals = self.bot.feature_manager.accumulate_tokens(
                            project_dir,
                            input_tokens=context_fill,
                            output_tokens=event.output_tokens or 0,
                            cost_usd=event.cost_usd or 0.0,
                            feature_name=feature.name if feature else None,
                        )

                        # Report cost to BridgeCrew dashboard (fire-and-forget, non-blocking)
                        if event.cost_usd:
                            import asyncio as _asyncio
                            from core.bridgecrew_client import report_cost as _report_cost
                            _feature_bc_id = getattr(feature, "bridgecrew_feature_id", "") if feature else ""
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
                        session_line = f"*{model_str}{session_label} · {cost_str}{totals['prompt_count']} prompts*"

                        await streamer.feed(
                            f"\n\n---\n"
                            f"{footer_line}\n"
                            f"{session_line}"
                            f"{warning}"
                        )

            await streamer.finalize()

            # Autonomous run-complete notification
            if guild:
                asyncio.create_task(self.bot.voice_notifier.voice_event(
                    guild, "run_complete",
                    f"Claude has finished in {project_name}." if project_name else "Claude has finished."
                ))

            # Extract markers from the full response text and clean them from Discord messages
            response_text = "".join(full_response)
            pending_files = SEND_FILE_PATTERN.findall(response_text)
            pending_audio = PLAY_AUDIO_PATTERN.findall(response_text)
            pending_question = None
            ask_match = ASK_USER_PATTERN.search(response_text)
            if ask_match:
                pending_question = ask_match.group(1)

            # Strip markers from the Discord messages if any were found
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
        feature = self.bot.feature_manager.get_current_feature(project_dir, session_id=default_session_id) if project else None

        # Gate: require a feature selection for project threads
        if project and not feature:
            features = self.bot.feature_manager.list_features(project_dir)
            view = FeatureGateView(features, project_dir, self.bot)
            gate_msg = await message.channel.send(
                "No active feature — pick one before I start working:",
                view=view,
            )
            self._system_run_labels[message.channel.id] = "selecting a feature"
            try:
                await view.select.event.wait()
            finally:
                self._system_run_labels.pop(message.channel.id, None)
            feature = view.select.selected_feature
            if not feature:
                await gate_msg.edit(content="*Timed out — prompt cancelled.*", view=None)
                return

        session_id = feature.session_id if feature else default_session_id
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

            # None means button click or timeout — proceed with best guess
            if answer is None:
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

        # Log to history
        self.bot.feature_manager.add_history(
            project_dir,
            user=str(message.author),
            prompt_summary=prompt,
            feature_name=feature.name if feature else None,
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
