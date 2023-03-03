import asyncio
import discord
import requests
from discord.ext import commands
from yt_dlp import YoutubeDL
from time import strftime, gmtime

from bot.config import BaseConfig


class Music(commands.Cog):
    FFMPEG_PATH = BaseConfig.FFMPEG_PATH
    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn'
    }

    YDL_OPTIONS = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True
    }

    def __init__(self, bot):
        self.__bot = bot

        self.queue = {}
        self.active_interaction = {}

    async def start_playing(self, guild_id: int, first=True):
        if not first:
            await self.queue[guild_id][0][0].edit(view=MusicControlView(disabled=True))
            self.queue[guild_id].pop(0)
            if not self.queue[guild_id]:
                if self.__bot.get_guild(guild_id).voice_client:
                    await self.__bot.get_guild(guild_id).voice_client.disconnect()

        if self.queue[guild_id]:
            source = discord.FFmpegPCMAudio(
                self.queue[guild_id][0][2]['url'],
                **self.FFMPEG_OPTIONS,
                executable=self.FFMPEG_PATH
            )
            self.__bot.get_guild(guild_id).voice_client.play(
                source,
                after=lambda __: asyncio.run_coroutine_threadsafe(
                    self.start_playing(self.queue[guild_id][0][1].guild_id, first=False),
                    self.__bot.loop
                )
            )

            embed = discord.Embed(
                title=self.queue[guild_id][0][2]['title'],
                url=self.queue[guild_id][0][2]['original_url'],
                color=15548997
            )
            embed.set_author(
                name=self.queue[guild_id][0][2]['channel'],
                url=self.queue[guild_id][0][2]['channel_url']
            )
            embed.add_field(name='Запрошено пользователем :', value=f'`{self.queue[guild_id][0][1].user}`', inline=True)
            embed.add_field(
                name='Длительность :',
                value=(
                    strftime('`%H:%M:%S`', gmtime(self.queue[guild_id][0][2]['duration']))
                    if int(self.queue[guild_id][0][2]['duration']) >= 3600
                    else strftime('`%M:%S`', gmtime(self.queue[guild_id][0][2]['duration']))
                ),
                inline=True
            )
            embed.set_image(url=self.queue[guild_id][0][2]['thumbnail'])
            embed.set_footer(
                text='YouTube',
                icon_url='https://cdn1.iconfinder.com/data/icons/logotypes/32/youtube-512.png'
            )
            self.queue[guild_id][0][0] = await self.queue[guild_id][0][1].followup.send(embed=embed)
            await self.queue[guild_id][0][1].followup.edit_message(
                message_id=self.queue[guild_id][0][0].id,
                view=MusicControlView(
                    self.__bot, self.queue[guild_id][0][0], self.queue[guild_id][0][1],
                    timeout=int(self.queue[guild_id][0][2]['duration']))
            )

    @discord.app_commands.command(name='play', description='Запустить музыку с YouTube')
    @discord.app_commands.describe(search='Введите строку для поиска или URL')
    async def play(self, interaction: discord.Interaction, search: str):
        await interaction.response.defer()

        with YoutubeDL(self.YDL_OPTIONS) as ydl:
            try:
                requests.get(search)
                entry = ydl.extract_info(search, download=False)
                if interaction.user.voice is not None:
                    self.__bot.cogs[Music.__name__].queue[interaction.guild_id].append([
                        None,
                        interaction,
                        entry
                    ])
                    if len(self.__bot.cogs[Music.__name__].queue[interaction.guild_id]) == 1:
                        if self.__bot.get_guild(interaction.guild_id).voice_client is None:
                            await interaction.user.voice.channel.connect()
                        await self.__bot.cogs[Music.__name__].start_playing(interaction.guild_id)
                    else:
                        embed = discord.Embed(
                            title=entry['title'],
                            url=entry['original_url'],
                            color=15548997
                        )
                        embed.set_author(name='Трек добавлен в очередь')
                        embed.add_field(name='Запрошено пользователем :', value=f'`{interaction.user}`', inline=True)
                        embed.add_field(
                            name='Длительность :',
                            value=(
                                strftime('`%H:%M:%S`', gmtime(entry['duration']))
                                if int(entry['duration']) >= 3600
                                else strftime('`%M:%S`', gmtime(entry['duration']))
                            ),
                            inline=True
                        )
                        embed.set_thumbnail(url=entry['thumbnail'])
                        embed.set_footer(
                            text='YouTube',
                            icon_url='https://cdn1.iconfinder.com/data/icons/logotypes/32/youtube-512.png'
                        )
                        await interaction.followup.send(embed=embed)
            except requests.exceptions.MissingSchema:
                entries = ydl.extract_info(f'ytsearch5:{search}', download=False)['entries']
                embed = discord.Embed(title='Результаты поиска :')
                for i, entry in enumerate(entries, 1):
                    embed.add_field(
                        name='\u200b',
                        value='**{}.** [{}]({}) ({})'.format(i, entry['title'], entry['original_url'], (
                            strftime('%H:%M:%S', gmtime(entry['duration']))
                            if int(entry['duration']) >= 3600
                            else strftime('%M:%S', gmtime(entry['duration']))
                        )),
                        inline=False
                    )
                embed.set_footer(
                    text='YouTube',
                    icon_url='https://cdn1.iconfinder.com/data/icons/logotypes/32/youtube-512.png'
                )

                await interaction.followup.send(embed=embed, view=MusicView(self.__bot, interaction, entries))


class MusicView(discord.ui.View):
    def __init__(self, bot=None, interaction=None, entries=None, timeout=30, enabled=True):
        self.__bot = bot
        self.__interaction = interaction

        super().__init__(timeout=timeout)

        if enabled:
            self.add_item(MusicSelect(self.__bot, entries))
        else:
            self.add_item(MusicSelectDisabled())

    async def on_timeout(self):
        await self.__interaction.edit_original_response(view=MusicView(timeout=None, enabled=False))


class MusicSelect(discord.ui.Select):
    def __init__(self, bot, entries):
        self.__bot = bot
        self.__entries = entries

        super().__init__(placeholder='Выберите нужное', options=[
            discord.SelectOption(label='{}. {}'.format(i + 1, entry['title']), value=str(i))
            for i, entry in enumerate(self.__entries)
        ])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await interaction.edit_original_response(view=MusicView(timeout=None, enabled=False))

        if interaction.user.voice is not None:
            self.__bot.cogs[Music.__name__].queue[interaction.guild_id].append([
                None,
                interaction,
                self.__entries[int(self.values[0])]
            ])

            if len(self.__bot.cogs[Music.__name__].queue[interaction.guild_id]) == 1:
                if self.__bot.get_guild(interaction.guild_id).voice_client is None:
                    await interaction.user.voice.channel.connect()
                await self.__bot.cogs[Music.__name__].start_playing(interaction.guild_id)
            else:
                embed = discord.Embed(
                    title=self.__entries[int(self.values[0])]['title'],
                    url=self.__entries[int(self.values[0])]['original_url']
                )
                embed.set_author(name='Трек добавлен в очередь')
                embed.add_field(name='Запрошено пользователем :', value=f'`{interaction.user}`', inline=True)
                embed.add_field(
                    name='Длительность :',
                    value=(
                        strftime('`%H:%M:%S`', gmtime(self.__entries[int(self.values[0])]['duration']))
                        if int(self.__entries[int(self.values[0])]['duration']) >= 3600
                        else strftime('`%M:%S`', gmtime(self.__entries[int(self.values[0])]['duration']))
                    ),
                    inline=True
                )
                embed.set_thumbnail(url=self.__entries[int(self.values[0])]['thumbnail'])
                embed.set_footer(
                    text='YouTube',
                    icon_url='https://cdn1.iconfinder.com/data/icons/logotypes/32/youtube-512.png'
                )
                await interaction.followup.send(embed=embed)


class MusicSelectDisabled(discord.ui.Select):
    def __init__(self):
        super().__init__(
            options=[discord.SelectOption(label='')],
            disabled=True
        )


class MusicControlView(discord.ui.View):
    def __init__(self, bot=None, message=None, interaction=None, timeout=None, disabled=False):
        super().__init__(timeout=timeout)

        self.add_item(MusicControlButtonNext(bot, message, interaction, disabled))
        self.add_item(MusicControlButtonQueue(bot, message, interaction, disabled))
        self.add_item(MusicControlButtonStub(bot, message, interaction))
        self.add_item(MusicControlButtonDisconnect(bot, message, interaction, disabled))


class MusicControlButtonNext(discord.ui.Button):
    def __init__(self, bot, message, interaction, disabled=False):
        self.__bot = bot
        self.__message = message
        self.__interaction = interaction

        super().__init__(emoji='⏭', label='Пропустить', style=discord.ButtonStyle.gray, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        self.__bot.get_guild(interaction.guild_id).voice_client.stop()


class MusicControlButtonQueue(discord.ui.Button):
    def __init__(self, bot, message, interaction, disabled=False):
        self.__bot = bot
        self.__message = message
        self.__interaction = interaction

        super().__init__(emoji='💬', label='Очередь', style=discord.ButtonStyle.gray, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        empty_queue = True
        embed = discord.Embed(title='Очередь')
        for i, (*_, entry) in enumerate(self.__bot.cogs[Music.__name__].queue[interaction.guild_id][1:], 1):
            empty_queue = False
            embed.add_field(
                name='\u200b',
                value='**{}.** [{}]({}) ({})'.format(i, entry['title'], entry['original_url'], (
                        strftime('%H:%M:%S', gmtime(entry['duration']))
                        if int(entry['duration']) >= 3600
                        else strftime('%M:%S', gmtime(entry['duration']))
                    )),
                inline=False
            )
        if empty_queue:
            embed.add_field(
                name='В очереди ничего нет.',
                value='Добавьте треки, используя команду **/play**'
            )

        embed.set_footer(
            text='YouTube',
            icon_url='https://cdn1.iconfinder.com/data/icons/logotypes/32/youtube-512.png'
        )

        await interaction.followup.send(embed=embed)


class MusicControlButtonDisconnect(discord.ui.Button):
    def __init__(self, bot, message, interaction, disabled=False):
        self.__bot = bot
        self.__message = message
        self.__interaction = interaction

        super().__init__(label='Отключить', style=discord.ButtonStyle.danger, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        if self.__bot.get_guild(interaction.guild_id).voice_client:
            await self.__bot.get_guild(interaction.guild_id).voice_client.disconnect()


class MusicControlButtonStub(discord.ui.Button):
    def __init__(self, bot, message, interaction):
        self.__bot = bot
        self.__message = message
        self.__interaction = interaction

        super().__init__(label='\u200b', style=discord.ButtonStyle.gray, disabled=True)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
