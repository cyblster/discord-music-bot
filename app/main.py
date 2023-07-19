import discord
from discord import Intents
from discord.ext import commands

from app.cogs.music import MusicCog


class Bot(commands.Bot):
    def __init__(self, token: str):
        super().__init__(
            command_prefix='/',
            activity=discord.Activity(type=discord.ActivityType.listening, name='/play'),
            intents=Intents.all()
        )

        self.run(token)

    async def on_ready(self) -> None:
        await self.wait_until_ready()

        await self.add_cog(MusicCog(self))

        await self.tree.sync()


if __name__ == '__main__':
    from configs.environment import get_environment_variables

    env = get_environment_variables()

    Bot(env.TOKEN)
