"""
bot.py — Discord bot entry point for the MLB Parlay Agent.

Registers five slash commands and connects them to the pipeline:
  /run         — Full pipeline: IL/transactions, props, scoring, LLM analysis
  /resolve     — Outcome resolver: fetches box scores for pending recommendations
  /status      — Show all pending (unresolved) recommendations
  /calibration — Model calibration report: Brier scores, hit rates, EV accuracy
  /dashboard   — Performance dashboard: hit rates, P&L, prop category breakdown

Also runs two scheduled tasks daily (America/New_York timezone, DST-aware):
  9:00am ET  — auto-resolve pending recommendations, then immediately run the pipeline
  12:00pm ET — auto-run the full pipeline (second daily run, catches afternoon lineups)
  5:30pm ET  — auto-run the full pipeline (third daily run, final before evening games)

Each command immediately defers the interaction so Discord doesn't show
"interaction failed" during long-running jobs. Results are posted back to
the same channel when the work completes.

To run:
    python bot.py

Environment variables required in .env:
    DISCORD_BOT_TOKEN    — Bot token from the Discord developer portal
    DISCORD_GUILD_ID     — Server (guild) ID where commands are registered
    SCHEDULE_CHANNEL_ID  — Channel ID for scheduled pipeline output
"""
from __future__ import annotations

import os
from datetime import time as dtime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from src.bot.runner import pipeline_run, pipeline_resolve, pipeline_status, pipeline_calibration
from src.bot.formatter import (
    format_run_header,
    format_parlay_embed,
    format_analysis_chunks,
    format_resolve_chunks,
    format_status_embed,
    format_calibration_embed,
)

load_dotenv()

TOKEN    = (os.getenv("DISCORD_BOT_TOKEN") or "").removeprefix("DISCORD_BOT_TOKEN=") or None
GUILD_ID = (os.getenv("DISCORD_GUILD_ID") or "").removeprefix("DISCORD_GUILD_ID=") or None
SCHEDULE_CHANNEL_ID = int(
    (os.getenv("SCHEDULE_CHANNEL_ID") or "1488629941443498014").removeprefix("SCHEDULE_CHANNEL_ID=")
)

if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN not set in .env")
if not GUILD_ID:
    raise RuntimeError("DISCORD_GUILD_ID not set in .env")

GUILD = discord.Object(id=int(GUILD_ID))
ET = ZoneInfo("America/New_York")


class MLBBot(discord.Client):
    """
    Discord client subclass that holds the slash command tree.

    Using a subclass (rather than commands.Bot) keeps the setup minimal and
    makes it straightforward to swap in a different framework later when
    hosting remotely.
    """

    def __init__(self):
        """Initialise the client with the minimum required intents."""
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        """
        Sync slash commands to the guild on startup.

        Guild-scoped syncs take effect immediately (vs global syncs which
        can take up to an hour), so this is preferred for local development.
        """
        self.tree.copy_global_to(guild=GUILD)
        await self.tree.sync(guild=GUILD)
        print(f"Slash commands synced to guild {GUILD_ID}")

    async def on_ready(self):
        """Log a confirmation message and start scheduled tasks when bot connects."""
        print(f"Logged in as {self.user} (id: {self.user.id})")
        if not scheduled_run.is_running():
            scheduled_run.start()
            print("Scheduled run started (12:00pm, 5:30pm ET daily)")
        if not scheduled_resolve.is_running():
            scheduled_resolve.start()
            print("Scheduled resolve+run started (9:00am ET daily: resolve then pipeline)")


client = MLBBot()


# ── /run ──────────────────────────────────────────────────────────────────────

@client.tree.command(name="run", description="Run the full MLB parlay pipeline")
async def run_command(interaction: discord.Interaction):
    """
    Slash command handler for /run.

    Defers the interaction immediately (prevents Discord timeout), runs the
    full pipeline in a background thread, then posts results as embeds.
    The LLM analysis is split into chunks to stay within message limits.
    """
    await interaction.response.defer(thinking=True)
    channel = interaction.channel

    try:
        await interaction.followup.send("Pipeline starting — this may take a moment...")
        parlays, analysis = await pipeline_run()

        if not parlays:
            await channel.send("Pipeline complete — no qualifying parlays found today.")
            return

        await channel.send(embed=format_run_header(len(parlays)))

        for i, parlay in enumerate(parlays, 1):
            await channel.send(embed=format_parlay_embed(parlay, i))

        for chunk in format_analysis_chunks(analysis):
            await channel.send(chunk)

    except Exception as e:
        try:
            await channel.send(f"Pipeline error: {e}")
        except Exception:
            try:
                await interaction.followup.send(f"Pipeline error: {e}")
            except Exception:
                print(f"[run] pipeline error (failed to post to Discord): {e}")
        raise


# ── /resolve ──────────────────────────────────────────────────────────────────

@client.tree.command(name="resolve", description="Resolve outcomes for pending recommendations")
async def resolve_command(interaction: discord.Interaction):
    """
    Slash command handler for /resolve.

    Defers the interaction, runs the outcome resolver in a background thread,
    then posts the resolver's output as one or more chunked messages.
    """
    await interaction.response.defer(thinking=True)
    channel = interaction.channel

    try:
        await interaction.followup.send("Running outcome resolver...")
        output = await pipeline_resolve()

        for chunk in format_resolve_chunks(output):
            await channel.send(chunk)

    except Exception as e:
        try:
            await channel.send(f"Resolver error: {e}")
        except Exception:
            try:
                await interaction.followup.send(f"Resolver error: {e}")
            except Exception:
                print(f"[resolve] resolver error (failed to post to Discord): {e}")
        raise


# ── /status ───────────────────────────────────────────────────────────────────

@client.tree.command(name="status", description="Show all pending recommendations")
async def status_command(interaction: discord.Interaction):
    """
    Slash command handler for /status.

    Queries the database for pending parlays and posts a single embed
    listing each one with its legs and their current resolution state.
    Fast enough that deferred thinking is not needed.
    """
    await interaction.response.defer(thinking=True)

    try:
        pending = await pipeline_status()
        await interaction.followup.send(embed=format_status_embed(pending))

    except Exception as e:
        await interaction.followup.send(f"Status error: {e}")
        raise


# ── /calibration ──────────────────────────────────────────────────────────────

@client.tree.command(name="calibration", description="Show model calibration report")
async def calibration_command(interaction: discord.Interaction):
    """
    Slash command handler for /calibration.

    Computes calibration metrics from all resolved recommendation legs and
    posts them as a single embed with hit rates, Brier scores, and EV accuracy.
    """
    await interaction.response.defer(thinking=True)

    try:
        data = await pipeline_calibration()
        await interaction.followup.send(embed=format_calibration_embed(data))

    except Exception as e:
        await interaction.followup.send(f"Calibration error: {e}")
        raise


# ── /dashboard ────────────────────────────────────────────────────────────────

@client.tree.command(name="dashboard", description="Show performance dashboard — hit rates, P&L, prop category breakdown")
async def dashboard_command(interaction: discord.Interaction):
    """
    Slash command handler for /dashboard.

    TODO: implement pipeline_dashboard() in src/bot/runner.py and
          format_dashboard_embed() in src/bot/formatter.py.
    """
    await interaction.response.defer(thinking=True)
    await interaction.followup.send("Dashboard not yet implemented — coming in a later phase.")


# ── Scheduled tasks ───────────────────────────────────────────────────────────

async def _get_channel() -> discord.TextChannel | None:
    """
    Return the scheduled output channel.

    Tries the in-memory cache first (instant). Falls back to an API fetch if
    the cache misses — this can happen after a reconnect because discord.py
    repopulates its cache asynchronously after on_ready.
    """
    channel = client.get_channel(SCHEDULE_CHANNEL_ID)
    if channel is not None:
        return channel
    try:
        return await client.fetch_channel(SCHEDULE_CHANNEL_ID)
    except Exception as e:
        print(f"[scheduler] Cannot access channel {SCHEDULE_CHANNEL_ID}: {e}")
        return None


@tasks.loop(time=[
    dtime(hour=12, minute=0,  tzinfo=ET),
    dtime(hour=17, minute=30, tzinfo=ET),
])
async def scheduled_run():
    """
    Automatically run the full pipeline at 12:00pm and 5:30pm ET every day.

    Posts results to SCHEDULE_CHANNEL_ID the same way /run does.
    DST-aware: ZoneInfo("America/New_York") handles the EST/EDT switch.

    The channel is re-fetched after the pipeline completes so a reconnect
    that occurs during the run doesn't leave a stale channel reference.
    """
    print("[scheduler] scheduled_run fired")

    # Verify channel access before starting the pipeline
    if await _get_channel() is None:
        return

    try:
        parlays, analysis = await pipeline_run()

        # Re-fetch channel after the pipeline — bot may have reconnected during run
        channel = await _get_channel()
        if channel is None:
            print("[scheduler] Channel unavailable after pipeline — results lost")
            return

        if not parlays:
            await channel.send("Scheduled run complete — no qualifying parlays found today.")
            return

        await channel.send(embed=format_run_header(len(parlays)))

        for i, parlay in enumerate(parlays, 1):
            await channel.send(embed=format_parlay_embed(parlay, i))

        for chunk in format_analysis_chunks(analysis):
            await channel.send(chunk)

    except Exception as e:
        print(f"[scheduler] scheduled_run exception: {e}")
        channel = await _get_channel()
        if channel:
            try:
                await channel.send(f"Scheduled run error: {e}")
            except Exception:
                print(f"[scheduler] also failed to post error to Discord: {e}")
        raise


@scheduled_run.error
async def scheduled_run_error(exception: Exception):
    """Log unhandled exceptions from scheduled_run to stdout (visible in Railway logs)."""
    print(f"[scheduler] scheduled_run unhandled error: {exception}")


@tasks.loop(time=dtime(hour=9, minute=0, tzinfo=ET))
async def scheduled_resolve():
    """
    At 9:00am ET: resolve pending recommendations, then immediately run the pipeline.

    Resolve runs first so yesterday's outcomes are logged before today's
    recommendations are generated. Both results are posted to SCHEDULE_CHANNEL_ID.
    DST-aware: ZoneInfo("America/New_York") handles the EST/EDT switch.
    """
    print("[scheduler] scheduled_resolve fired")

    # ── Step 1: resolve yesterday's pending legs ──────────────────────────────
    try:
        output = await pipeline_resolve()

        channel = await _get_channel()
        if channel is None:
            return

        for chunk in format_resolve_chunks(output):
            await channel.send(chunk)

    except Exception as e:
        print(f"[scheduler] scheduled_resolve exception: {e}")
        channel = await _get_channel()
        if channel:
            try:
                await channel.send(f"Scheduled resolve error: {e}")
            except Exception:
                print(f"[scheduler] also failed to post resolve error to Discord: {e}")
        # error logged and posted — fall through to pipeline_run()

    # ── Step 2: run today's pipeline immediately after ────────────────────────
    print("[scheduler] scheduled_resolve → kicking off morning pipeline run")
    try:
        parlays, analysis = await pipeline_run()

        channel = await _get_channel()
        if channel is None:
            print("[scheduler] Channel unavailable after morning pipeline — results lost")
            return

        if not parlays:
            await channel.send("Morning pipeline complete — no qualifying parlays found today.")
            return

        await channel.send(embed=format_run_header(len(parlays)))

        for i, parlay in enumerate(parlays, 1):
            await channel.send(embed=format_parlay_embed(parlay, i))

        for chunk in format_analysis_chunks(analysis):
            await channel.send(chunk)

    except Exception as e:
        print(f"[scheduler] morning pipeline exception: {e}")
        channel = await _get_channel()
        if channel:
            try:
                await channel.send(f"Morning pipeline error: {e}")
            except Exception:
                print(f"[scheduler] also failed to post morning pipeline error to Discord: {e}")


@scheduled_resolve.error
async def scheduled_resolve_error(exception: Exception):
    """Log unhandled exceptions from scheduled_resolve to stdout."""
    print(f"[scheduler] scheduled_resolve unhandled error: {exception}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    client.run(TOKEN)
