import asyncio
import logging

import discord
from discord.ext import commands

from core.discord_streamer import DiscordStreamer

log = logging.getLogger(__name__)


class ClaudePromptCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore own messages
        if message.author == self.bot.user:
            return

        # Ignore messages that aren't in a thread
        if not isinstance(message.channel, discord.Thread):
            return

        # Must mention the bot
        if self.bot.user not in message.mentions:
            return

        # Resolve project from thread
        project = self.bot.project_manager.get_project_by_thread(message.channel.id)
        if not project:
            return

        # Strip the bot mention from the prompt
        prompt = message.content
        for mention_str in [f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>"]:
            prompt = prompt.replace(mention_str, "")
        prompt = prompt.strip()

        if not prompt:
            await message.channel.send("Send a prompt after mentioning me.")
            return

        # Check if Claude is already running for this project
        runner = self.bot.claude_runner
        if runner.is_busy(message.channel.id):
            await message.channel.send("Claude is already working on something in this project. Please wait or use `/cancel`.")
            return

        project_dir = self.bot.project_manager.get_project_dir(project)

        # Get session_id: prefer active feature's session, fall back to project default
        feature = self.bot.feature_manager.get_current_feature(project_dir)
        session_id = feature.session_id if feature else None
        if not session_id:
            from core.state import load_project_state
            state = load_project_state(project_dir)
            session_id = state.get("default_session_id")
        resume = bool(session_id)

        # Start streaming with a cancel button
        cancel_fn = lambda: runner.cancel(message.channel.id)
        streamer = DiscordStreamer(message.channel, on_cancel=cancel_fn)
        await streamer.start()

        # Create a background task to periodically flush the buffer
        async def tick_loop():
            while not streamer._finalized:
                await asyncio.sleep(0.3)
                await streamer.tick()

        tick_task = asyncio.create_task(tick_loop())

        print(f"\n{'='*60}\n[{message.author}] {prompt}\n{'='*60}", flush=True)

        try:
            async for event in runner.run(
                prompt=prompt,
                project_dir=project_dir,
                thread_id=message.channel.id,
                session_id=session_id,
                resume=resume,
            ):
                if event.type == "text":
                    print(event.content, end="", flush=True)
                    await streamer.feed(event.content)
                elif event.type == "cancelled":
                    print("\n[Cancelled]", flush=True)
                    await streamer.send_cancelled()
                    return
                elif event.type == "error":
                    print(f"\n[Error] {event.content}", flush=True)
                    await streamer.send_error(event.content)
                    return
                elif event.type == "result":
                    print(flush=True)  # final newline after streaming
                    # Persist the session_id Claude returned
                    if event.session_id:
                        from core.state import load_project_state, save_project_state

                        state = load_project_state(project_dir)
                        # Save to feature if active
                        if feature and feature.name in state.get("features", {}):
                            state["features"][feature.name]["session_id"] = event.session_id
                        # Always save as project default
                        state["default_session_id"] = event.session_id
                        save_project_state(project_dir, state)

                    # Show context window usage
                    if event.input_tokens is not None and event.context_window:
                        total_tokens = event.input_tokens + (event.output_tokens or 0)
                        pct = total_tokens / event.context_window * 100
                        cost_str = f" | ${event.cost_usd:.4f}" if event.cost_usd else ""
                        await streamer.feed(
                            f"\n\n---\n*{total_tokens:,} / {event.context_window:,} tokens ({pct:.1f}%){cost_str}*"
                        )

            await streamer.finalize()

            # Log to history
            self.bot.feature_manager.add_history(
                project_dir,
                user=str(message.author),
                prompt_summary=prompt,
                feature_name=feature.name if feature else None,
            )

        except Exception as e:
            log.exception("Error during Claude prompt relay")
            await streamer.send_error(str(e))
        finally:
            # Always clean up the stop button
            if not streamer._finalized:
                await streamer.finalize()
            tick_task.cancel()
            try:
                await tick_task
            except asyncio.CancelledError:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ClaudePromptCog(bot))
