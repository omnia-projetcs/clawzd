"""
Clawzd — Discord bot integration.
Runs a Discord bot that forwards messages to Clawzd and returns LLM responses.
"""
import os, logging, asyncio
from config import DATA_DIR

logger = logging.getLogger("clawzd.discord")

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_IDS = os.getenv("DISCORD_CHANNEL_IDS", "").split(",")

_bot = None

async def start_discord_bot():
    """Start the Discord bot in the background."""
    global _bot
    if not DISCORD_TOKEN:
        logger.warning("Discord: No DISCORD_BOT_TOKEN set, skipping")
        return
    try:
        import discord
        from discord.ext import commands
    except ImportError:
        logger.warning("Discord: discord.py not installed. Run: pip install discord.py")
        return

    intents = discord.Intents.default()
    intents.message_content = True
    _bot = commands.Bot(command_prefix="!", intents=intents)

    @_bot.event
    async def on_ready():
        logger.info("Discord bot connected as %s", _bot.user)

    @_bot.event
    async def on_message(message):
        if message.author.bot:
            return
        # Only respond in configured channels, or when mentioned
        if DISCORD_CHANNEL_IDS[0] and str(message.channel.id) not in DISCORD_CHANNEL_IDS:
            if _bot.user not in message.mentions:
                return

        content = message.content.replace(f"<@{_bot.user.id}>", "").strip()
        if not content:
            return

        from app.llm_provider import get_llm_provider
        from app.preprompts import get_preprompt
        from app.database import create_session, add_message
        import uuid

        session_id = f"discord-{message.channel.id}-{uuid.uuid4().hex[:6]}"
        create_session(session_id, title=f"[Discord] {content[:40]}")
        add_message(session_id, "user", content)

        messages = [
            {"role": "system", "content": get_preprompt("enrichment") or ""},
            {"role": "user", "content": content},
        ]

        async with message.channel.typing():
            provider = get_llm_provider()
            full = ""
            async for token in provider.chat_stream(messages):
                full += token

        add_message(session_id, "assistant", full)

        # Discord max message length is 2000
        for i in range(0, len(full), 1900):
            await message.reply(full[i:i+1900], mention_author=False)

    try:
        await _bot.start(DISCORD_TOKEN)
    except Exception as e:
        logger.error("Discord bot error: %s", e)
