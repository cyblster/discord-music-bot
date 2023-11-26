import discord
from discord import Intents
from discord.ext import commands

from src.cogs import (
    MusicCog
)
from src.models import (
    BaseModal,
    async_engine
)


class Bot(commands.Bot):
    def __init__(self, token: str):
        super().__init__(
            command_prefix=commands.when_mentioned_or(),
            intents=Intents.all()
        )

        self.run(token)

    @staticmethod
    async def init_db():
        async with async_engine.begin() as connection:
            await connection.run_sync(BaseModal.metadata.create_all)

    async def on_ready(self) -> None:
        await self.init_db()
        await self.wait_until_ready()
        await self.add_cog(MusicCog(self))
        await self.tree.sync()
