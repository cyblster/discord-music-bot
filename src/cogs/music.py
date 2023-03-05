import asyncio
import discord
import validators

from discord import Guild, Member, VoiceState, Interaction, WebhookMessage, Embed, FFmpegPCMAudio
from discord.ext import commands
from discord.ui import View, Select, Button
from yt_dlp import YoutubeDL
from time import strftime, gmtime
from typing import Optional


from src.config import BaseConfig


class MusicCog(commands.Cog):
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
    YOUTUBE_LOGO_URL = 'https://cdn1.iconfinder.com/data/icons/logotypes/32/youtube-512.png'

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.queue = {}
        for guild in self.bot.guilds:
            self.queue[guild.id] = []

        super().__init__()

    def is_first_track(self, guild_id: int) -> bool:
        return True if len(self.queue[guild_id]) == 1 else False

    def is_queue_empty(self, guild_id: int) -> bool:
        return False if self.queue[guild_id] else True

    def update_queue(self, message: Optional[WebhookMessage], interaction: Interaction, source: dict) -> None:
        self.queue[interaction.guild_id].append({
            'message': message,
            'interaction': interaction,
            'source': source
        })

    async def play_track(self, guild_id: int, first_track: bool = False) -> None:
        if first_track:
            await self.safe_connect(self.bot, self.queue[guild_id][0]['interaction'])
        else:
            await self.queue[guild_id][0]['message'].edit(view=MusicControlView(enabled=False))
            self.queue[guild_id].pop(0)
            if self.is_queue_empty(guild_id):
                await self.safe_disconnect(self.bot, guild_id)
        if not self.is_queue_empty(guild_id):
            source = FFmpegPCMAudio(
                self.queue[guild_id][0]['source']['url'],
                **self.FFMPEG_OPTIONS,
                executable=self.FFMPEG_PATH
            )
            self.bot.get_guild(guild_id).voice_client.play(
                source,
                after=lambda _: asyncio.run_coroutine_threadsafe(
                    self.play_track(guild_id, first_track=False),
                    self.bot.loop
                )
            )
            self.queue[guild_id][0]['message'] = await self.queue[guild_id][0]['interaction'].followup.send(
                embed=PlayNowEmbed(
                    self.queue[guild_id][0]['interaction'].user,
                    self.queue[guild_id][0]['source']
                ),
                view=MusicControlView(self, self.queue[guild_id][0]['interaction'])
            )

    @staticmethod
    def is_user_connected(interaction: Interaction) -> bool:
        return True if interaction.user.voice else False

    @staticmethod
    def is_user_with_bot(bot: commands.Bot, interaction: Interaction) -> bool:
        if not MusicCog.is_user_connected(interaction):
            return False
        if interaction.user.voice.channel != bot.get_channel(
            interaction.user.voice.channel.id
        ).guild.voice_client.channel:
            return False
        return True

    @staticmethod
    async def safe_connect(bot: commands.Bot, interaction: Interaction) -> None:
        if not bot.get_guild(interaction.guild_id).voice_client:
            await interaction.user.voice.channel.connect()

    @staticmethod
    async def safe_disconnect(bot: commands.Bot, guild_id: int) -> None:
        if bot.get_guild(guild_id).voice_client:
            await bot.get_guild(guild_id).voice_client.disconnect(force=True)

    @staticmethod
    def get_formatted_duration(duration: Optional[str]) -> str:
        if duration is None:
            return 'Неизвестно'
        if int(duration) >= 3600:
            return strftime('%H:%M:%S', gmtime(int(duration)))
        return strftime('%M:%S', gmtime(int(duration)))

    @staticmethod
    def get_formatted_option(label: str) -> str:
        if len(label) > 90:
            return label[:90]
        else:
            return label

    @commands.Cog.listener()
    async def on_guild_join(self, guild: Guild) -> None:
        self.queue[guild.id] = []

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: Guild) -> None:
        self.queue.pop(guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, user: Member, before: VoiceState, after: VoiceState) -> None:
        if user == self.bot.user:
            if not after.channel:
                if self.bot.get_guild(before.channel.guild.id).voice_client:
                    self.bot.get_guild(before.channel.guild.id).voice_client.cleanup()
                if self.queue[before.channel.guild.id]:
                    await self.queue[before.channel.guild.id][0]['message'].edit(view=MusicControlView(enabled=False))
                self.queue[before.channel.guild.id] = []
        elif before.channel and self.bot.get_guild(before.channel.guild.id).voice_client:
            if before.channel == self.bot.get_guild(before.channel.guild.id).voice_client.channel:
                if len(before.channel.members) == 1 and before.channel.members[0] == self.bot.user:
                    await self.safe_disconnect(self.bot, before.channel.guild.id)

    @discord.app_commands.command(name='play', description='Запустить музыку с YouTube')
    @discord.app_commands.describe(search='Введите строку для поиска или URL')
    async def command_play(self, interaction: Interaction, search: str) -> None:
        if not self.is_user_connected(interaction):
            return
        if not self.is_queue_empty(interaction.guild_id) and not self.is_user_with_bot(self.bot, interaction):
            return

        await interaction.response.defer()

        with YoutubeDL(self.YDL_OPTIONS) as ydl:
            if validators.url(search):
                entry = ydl.extract_info(search, download=False)
                self.update_queue(None, interaction, entry)
                if self.is_first_track(interaction.guild_id):
                    await self.play_track(interaction.guild_id, first_track=True)
                else:
                    await interaction.followup.send(embed=PlayQueueEmbed(interaction.user, entry))
            else:
                entries = ydl.extract_info(f'ytsearch5:{search}', download=False)['entries']
                await interaction.followup.send(
                    embed=SearchEmbed(entries),
                    view=MusicSelectView(self, interaction=interaction, entries=entries)
                )


class MusicSelectView(View):
    def __init__(self, cog: MusicCog = None, interaction: Interaction = None, entries: dict = None,
                 timeout: Optional[float] = 30.0, enabled: bool = True):
        self.__interaction = interaction

        super().__init__(timeout=timeout)

        if enabled:
            self.add_item(MusicSelect(cog, entries))
        else:
            self.add_item(MusicSelectDisabled())

    async def on_timeout(self) -> None:
        if self.__interaction:
            await self.__interaction.edit_original_response(view=MusicSelectView(timeout=None, enabled=False))


class MusicSelect(Select):
    def __init__(self, cog: MusicCog, entries: dict):
        self.__cog = cog
        self.__entries = entries

        super().__init__(placeholder='Выберите нужное', options=[
            discord.SelectOption(label='{}. {}'.format(
                i + 1,
                MusicCog.get_formatted_option(entry['title'])), value=str(i)
            )
            for i, entry in enumerate(self.__entries)
        ])

    async def callback(self, interaction: Interaction) -> None:
        await interaction.response.defer()
        await interaction.edit_original_response(view=MusicSelectView(timeout=None, enabled=False))

        if MusicCog.is_user_connected(interaction):
            self.__cog.update_queue(None, interaction, self.__entries[int(self.values[0])])
            if self.__cog.is_first_track(interaction.guild_id):
                await self.__cog.play_track(interaction.guild_id, first_track=True)
            else:
                if MusicCog.is_user_with_bot(self.__cog.bot, interaction):
                    await interaction.followup.send(embed=PlayQueueEmbed(
                        interaction.user, self.__entries[int(self.values[0])]))


class MusicSelectDisabled(Select):
    def __init__(self):
        super().__init__(options=[discord.SelectOption(label='')], disabled=True)


class MusicControlView(View):
    def __init__(self, cog: MusicCog = None, interaction: Interaction = None, enabled: bool = True):
        super().__init__(timeout=None)

        if enabled:
            self.add_item(MusicControlButtonNext(cog, interaction))
            self.add_item(MusicControlButtonQueue(cog, interaction))
            self.add_item(MusicControlButtonStub())
            self.add_item(MusicControlButtonDisconnect(cog, interaction))
        else:
            self.add_item(MusicControlButtonNext(disabled=True))
            self.add_item(MusicControlButtonQueue(disabled=True))
            self.add_item(MusicControlButtonStub())
            self.add_item(MusicControlButtonDisconnect(disabled=True))


class MusicControlButtonNext(Button):
    def __init__(self, cog: MusicCog = None, interaction: Interaction = None, disabled: bool = False):
        self.__cog = cog
        self.__interaction = interaction

        super().__init__(emoji='⏭', label='Пропустить', style=discord.ButtonStyle.gray, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        if MusicCog.is_user_with_bot(self.__cog.bot, self.__interaction):
            self.__cog.bot.get_guild(interaction.guild_id).voice_client.stop()


class MusicControlButtonQueue(Button):
    def __init__(self, cog: MusicCog = None, interaction: Interaction = None, disabled: bool = False):
        self.__cog = cog
        self.__interaction = interaction

        super().__init__(emoji='💬', label='Очередь', style=discord.ButtonStyle.gray, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        if MusicCog.is_user_with_bot(self.__cog.bot, self.__interaction):
            await interaction.followup.send(embed=QueueEmbed(self.__cog.queue, self.__interaction.guild_id))


class MusicControlButtonDisconnect(Button):
    def __init__(self, cog: MusicCog = None, interaction: Interaction = None, disabled: bool = False):
        self.__cog = cog
        self.__interaction = interaction

        super().__init__(label='Отключить', style=discord.ButtonStyle.danger, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        if MusicCog.is_user_with_bot(self.__cog.bot, self.__interaction):
            await MusicCog.safe_disconnect(self.__cog.bot, self.__interaction.guild_id)


class MusicControlButtonStub(Button):
    def __init__(self):
        super().__init__(label='\u200b', style=discord.ButtonStyle.gray, disabled=True)


class SearchEmbed(Embed):
    def __init__(self, yt_entries: dict):
        super().__init__(title='Результаты поиска :')

        for i, entry in enumerate(yt_entries, 1):
            self.add_field(
                name='\u200b',
                value='**{}.** [{}]({}) ({})'.format(
                    i,
                    entry['title'],
                    entry['original_url'],
                    MusicCog.get_formatted_duration(entry.get('duration'))
                ),
                inline=False
            )
        self.set_footer(
            text='YouTube',
            icon_url=MusicCog.YOUTUBE_LOGO_URL
        )


class QueueEmbed(Embed):
    def __init__(self, queue: dict, guild_id: int):
        super().__init__(title='Очередь')

        if queue[guild_id][1:]:
            for i, data in enumerate(queue[guild_id][1:], 1):
                self.add_field(
                    name='**{}.** {}'.format(i, data['source']['channel']),
                    value='[{}]({}) ({})'.format(
                        data['source']['title'],
                        data['source']['original_url'],
                        MusicCog.get_formatted_duration(data['source'].get('duration'))
                    ),
                    inline=False
                )
        else:
            self.add_field(
                name='В очереди ничего нет.',
                value='Добавьте треки, используя команду **/play**'
            )
        self.set_footer(
            text='YouTube',
            icon_url='https://cdn1.iconfinder.com/data/icons/logotypes/32/youtube-512.png'
        )


class TrackEmbed(Embed):
    def __init__(self, user: Member, yt_entry: dict):
        super().__init__(title=yt_entry['title'], url=yt_entry['original_url'])

        self.add_field(name='Запрошено пользователем :', value=f'`{user}`', inline=True)
        self.add_field(
            name='Длительность :',
            value='`{}`'.format(MusicCog.get_formatted_duration(yt_entry.get('duration'))),
            inline=True
        )
        self.set_footer(
            text='YouTube',
            icon_url=MusicCog.YOUTUBE_LOGO_URL
        )


class PlayNowEmbed(TrackEmbed):
    def __init__(self, user: Member, yt_entry: dict):
        super().__init__(user, yt_entry)

        self.colour = 15548997
        self.set_author(name=yt_entry['channel'], url=yt_entry['channel_url'])
        self.set_image(url=yt_entry['thumbnail'])


class PlayQueueEmbed(TrackEmbed):
    def __init__(self, user: Member, yt_entry: dict):
        super().__init__(user, yt_entry)

        self.set_author(name='Трек добавлен в очередь')
        self.set_thumbnail(url=yt_entry['thumbnail'])
