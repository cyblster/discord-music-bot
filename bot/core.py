import discord
from discord.ext import commands

from bot.music import Music, MusicControlView
from bot.config import BaseConfig


class DiscordBot(commands.Bot):
    def __init__(self, token):
        super().__init__(
            command_prefix=commands.when_mentioned_or(),
            activity=discord.Game(name="/play"),
            intents=discord.Intents.all()
        )

        self.run(token)

    async def on_ready(self):
        await self.wait_until_ready()
        await self.add_cog(Music(self))
        await self.tree.sync()

        for guild in self.guilds:
            self.cogs[Music.__name__].queue.update({guild.id: []})

    async def on_guild_join(self, guild):
        self.cogs[Music.__name__].queue.update({guild.id: []})

    async def on_guild_remove(self, guild):
        self.cogs[Music.__name__].queue.pop(guild.id)

    async def on_voice_state_update(self, user, before, after):
        if user == self.user and after.channel is None:
            if self.cogs[Music.__name__].queue[before.channel.guild.id]:
                await self.cogs[Music.__name__].queue[before.channel.guild.id][0][0].edit(
                    view=MusicControlView(disabled=True)
                )
            self.cogs[Music.__name__].queue[before.channel.guild.id] = []
            if self.get_guild(before.channel.guild.id).voice_client:
                await self.get_guild(before.channel.guild.id).voice_client.disconnect(force=False)


if __name__ == '__main__':
    DiscordBot(token=BaseConfig.TOKEN)
