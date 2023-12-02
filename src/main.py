import logging

import discord
from discord.ext import commands

from src.cogs import (
    MusicCog
)
from src.models import (
    BaseModal,
    async_engine
)


class Bot(discord.ext.commands.Bot):
    def __init__(self, token: str):
        super().__init__(
            command_prefix=discord.ext.commands.when_mentioned_or(),
            intents=discord.Intents.all()
        )

        self.logger = logging.getLogger(discord.__title__)
        self.logger_handler = logging.StreamHandler()
        self.logger_formatter = logging.Formatter(
            '[%(asctime)s] %(name)s |%(levelname)s| - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger_handler.setFormatter(self.logger_formatter)
        self.logger.addHandler(self.logger_handler)

        self.run(token, log_handler=self.logger_handler, log_formatter=self.logger_handler.formatter)

    @staticmethod
    async def init_db():
        async with async_engine.begin() as connection:
            await connection.run_sync(BaseModal.metadata.create_all)

    async def on_connect(self) -> None:
        await self.init_db()

    async def on_ready(self) -> None:
        await self.wait_until_ready()

        await self.add_cog(MusicCog(self))

        await self.tree.sync()
