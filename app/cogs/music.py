import asyncio
import discord
import validators

from discord import Guild, Member, TextChannel, Interaction, Embed, VoiceState, FFmpegPCMAudio
from discord.ext import commands
from discord.ui import View, Select, Button
from yt_dlp import YoutubeDL
from datetime import datetime


from app.configs.environment import get_environment_variables


env = get_environment_variables()


class MusicCog(commands.Cog):
    FFMPEG_PATH = env.FFMPEG_PATH
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

    async def connect(self, interaction: Interaction) -> None:
        if not self.bot.get_guild(interaction.guild_id).voice_client:
            await interaction.user.voice.channel.connect()

    async def disconnect(self, guild_id: int) -> None:
        voice_client = self.bot.get_guild(guild_id).voice_client
        if voice_client:
            await voice_client.disconnect(force=True)

    def is_user_with_bot(self, interaction: Interaction) -> bool:
        if not self.is_user_connected(interaction):
            return False

        user_channel = interaction.user.voice.channel
        bot_channel = self.bot.get_channel(interaction.user.voice.channel.id)
        return user_channel == bot_channel

    def is_first_track(self, guild_id: int) -> bool:
        return len(self.queue[guild_id]) == 1

    def is_queue_empty(self, guild_id: int) -> bool:
        return not len(self.queue[guild_id]) > 0

    def update_queue(self, guild_id: int, yt_source: dict) -> None:
        self.queue[guild_id].append({
            'message': None,
            'source': {
                'url': yt_source['url'],
                'title': yt_source['title'],
                'original_url': yt_source['original_url'],
                'channel': yt_source['channel'],
                'channel_url': yt_source['channel_url'],
                'thumbnail': yt_source['thumbnail'],
                'duration': self.get_formatted_duration(yt_source['duration'])
            }
        })

    async def play_track(
        self,
        interaction: Interaction = None,
        user: Member = None,
        text_channel: TextChannel = None
    ) -> None:
        if interaction:
            guild_id = interaction.guild.id
            message = await self.bot.get_channel(interaction.channel.id).fetch_message(
                (await interaction.followup.send(
                    embed=PlayNowEmbed(
                        source=self.queue[interaction.channel.guild.id][0]['source'],
                        user=user,
                        icon_url=self.YOUTUBE_LOGO_URL
                    ),
                    view=MusicControlView(self, guild_id)
                )).id
            )
            self.queue[guild_id][0]['message'] = message
            await self.connect(interaction)
        else:
            guild_id = user.guild.id
            await self.queue[guild_id][0]['message'].edit(view=MusicSelectViewDisabled())
            self.queue[guild_id].pop(0)
            if self.is_queue_empty(user.guild.id):
                await self.disconnect(user.guild.id)
            else:
                message = self.bot.get_guild(text_channel.id).send(
                    embed=PlayNowEmbed(
                        source=self.queue[text_channel.guild.id][0]['source'],
                        user=user,
                        icon_url=self.YOUTUBE_LOGO_URL
                    ),
                    view=MusicControlView(self, user.guild.id)
                )
                self.queue[guild_id][0]['message'] = message

        if not self.is_queue_empty(guild_id):
            source = FFmpegPCMAudio(
                self.queue[guild_id][0]['source']['url'],
                **self.FFMPEG_OPTIONS,
                executable=self.FFMPEG_PATH
            )
            self.bot.get_guild(guild_id).voice_client.play(
                source,
                after=lambda _: asyncio.run_coroutine_threadsafe(
                    self.play_track(None, user, text_channel),
                    self.bot.loop
                )
            )

    async def skip_track(self, interaction: Interaction) -> None:
        if self.is_user_with_bot(interaction):
            self.bot.get_guild(interaction.guild_id).voice_client.stop()

    @staticmethod
    def is_user_connected(interaction: Interaction) -> bool:
        return interaction.user.voice is not None

    @staticmethod
    def get_formatted_duration(duration: int) -> str:
        return datetime.fromtimestamp(duration).strftime('%d:%I:%M:%S').lstrip('00:')

    @staticmethod
    def get_formatted_option(option: str) -> str:
        return option[:90]

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
                    await self.queue[before.channel.guild.id][0]['message'].edit(view=MusicControlViewDisabled())
                self.queue[before.channel.guild.id] = []
        elif before.channel and self.bot.get_guild(before.channel.guild.id).voice_client:
            if before.channel == self.bot.get_guild(before.channel.guild.id).voice_client.channel:
                if len(before.channel.members) == 1 and before.channel.members[0] == self.bot.user:
                    await self.disconnect(before.channel.guild.id)

    @discord.app_commands.command(name='play', description='Включить трек с YouTube')
    @discord.app_commands.describe(search='Введите строку для поиска или URL')
    async def command_play(self, interaction: Interaction, search: str) -> None:
        if not self.is_user_connected(interaction):
            return
        if not self.is_queue_empty(interaction.guild_id) and not self.is_user_with_bot(interaction):
            return
        await interaction.response.defer()

        with YoutubeDL(self.YDL_OPTIONS) as ydl:
            if validators.url(search):
                entry = ydl.extract_info(search, download=False)
                self.update_queue(interaction.guild_id, entry)
                if self.is_first_track(interaction.guild_id):
                    await self.play_track(interaction)
                else:
                    await interaction.followup.send(embed=PlayQueueEmbed(
                        self.queue[interaction.guild_id][-1]['source'],
                        interaction.user,
                        self.YOUTUBE_LOGO_URL
                    ))
            else:
                entries = ydl.extract_info(f'ytsearch5:{search}', download=False)['entries']
                await interaction.followup.send(
                    embed=SearchEmbed(self, entries),
                    view=MusicSelectView(self, interaction, entries)
                )

    @discord.app_commands.command(name='skip', description='Пропустить текущий трек')
    async def command_skip(self, interaction: Interaction) -> None:
        if not self.is_user_connected(interaction):
            return
        if not self.is_user_with_bot(interaction):
            return
        await interaction.response.defer()

        await self.skip_track(interaction)

    @discord.app_commands.command(name='stop', description='Отключить бота')
    async def command_stop(self, interaction: Interaction) -> None:
        if not self.is_user_connected(interaction):
            return
        if not self.is_user_with_bot(interaction):
            return
        await interaction.response.defer()

        await self.disconnect(interaction.guild.id)


class MusicSelectView(View):
    def __init__(self, cog: MusicCog, interaction: Interaction, entries: dict = None):
        self.__interaction = interaction

        super().__init__(timeout=60)

        self.add_item(MusicSelect(cog, entries))

    async def on_timeout(self) -> None:
        if self.__interaction:
            await self.__interaction.edit_original_response(view=MusicSelectViewDisabled())


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
        await interaction.response.edit_message(view=MusicSelectViewDisabled())

        if self.__cog.is_user_connected(interaction):
            self.__cog.update_queue(interaction.guild_id, self.__entries[int(self.values[0])])
            if self.__cog.is_first_track(interaction.guild_id):
                await self.__cog.play_track(interaction)
            else:
                if self.__cog.is_user_with_bot(interaction):
                    await interaction.followup.send(embed=PlayQueueEmbed(
                        self.__cog.queue[interaction.guild_id][-1]['source'],
                        interaction.user,
                        self.__cog.YOUTUBE_LOGO_URL
                    ))


class MusicSelectViewDisabled(View):
    def __init__(self):
        super().__init__()

        self.add_item(Select(options=[discord.SelectOption(label='')], disabled=True))


class MusicControlView(View):
    def __init__(self, cog: MusicCog, guild_id: int):
        self.__cog = cog
        self.__guild_id = guild_id

        super().__init__(timeout=600)

    @discord.ui.button(emoji='⏭', label='Пропустить', style=discord.ButtonStyle.gray)
    async def btn_skip(self, interaction: Interaction, button: Button):
        await interaction.response.defer()

        if self.__cog.is_user_with_bot(interaction):
            await self.__cog.skip_track(interaction)

    @discord.ui.button(emoji='💬', label='Очередь', style=discord.ButtonStyle.gray)
    async def btn_queue(self, interaction: Interaction, button: Button):
        await interaction.response.defer()

        if self.__cog.is_user_with_bot(interaction):
            await interaction.followup.send(embed=QueueEmbed(
                self.__cog.queue,
                interaction.guild_id,
                self.__cog.YOUTUBE_LOGO_URL
            ))

    @discord.ui.button(label='\u200b', style=discord.ButtonStyle.gray, disabled=True)
    async def btn_stub(self, interaction: Interaction, button: Button):
        await interaction.response.defer()

    @discord.ui.button(label='Отключить', style=discord.ButtonStyle.danger)
    async def btn_disconnect(self, interaction: Interaction, button: Button):
        await interaction.response.defer()

        if self.__cog.is_user_with_bot(interaction):
            await self.__cog.disconnect(interaction.guild_id)

    async def on_timeout(self) -> None:
        if self.__cog.is_queue_empty(self.__guild_id):
            return

        self.__cog.queue[self.__guild_id][0]['message'] = await self.__cog.queue[self.__guild_id][0]['message'].edit(
            view=MusicControlView(self.__cog, self.__guild_id)
        )


class MusicControlViewDisabled(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(emoji='⏭', label='Пропустить', style=discord.ButtonStyle.gray, disabled=True)
    async def btn_skip(self, interaction: Interaction, button: Button):
        pass

    @discord.ui.button(emoji='💬', label='Очередь', style=discord.ButtonStyle.gray, disabled=True)
    async def btn_queue(self, interaction: Interaction, button: Button):
        pass

    @discord.ui.button(label='\u200b', style=discord.ButtonStyle.gray, disabled=True)
    async def btn_stub(self, interaction: Interaction, button: Button):
        pass

    @discord.ui.button(label='Отключить', style=discord.ButtonStyle.danger, disabled=True)
    async def btn_disconnect(self, interaction: Interaction, button: Button):
        pass


class SearchEmbed(Embed):
    def __init__(self, cog: MusicCog, yt_sources: dict):
        self.__cog = cog

        super().__init__(title='Результаты поиска :')

        for i, source in enumerate(yt_sources, 1):
            self.add_field(
                name='\u200b',
                value='**{}.** [{}]({}) ({})'.format(
                    i,
                    source['title'],
                    source['original_url'],
                    self.__cog.get_formatted_duration(source['duration'])
                ),
                inline=False
            )
        self.set_footer(
            text='YouTube',
            icon_url=self.__cog.YOUTUBE_LOGO_URL
        )


class QueueEmbed(Embed):
    def __init__(self, queue: dict, guild_id: int, icon_url: str):
        super().__init__(title='Очередь')

        if queue[guild_id][1:]:
            for i, data in enumerate(queue[guild_id][1:], 1):
                self.add_field(
                    name='**{}.** {}'.format(i, data['source']['channel']),
                    value='[{}]({}) ({})'.format(
                        data['source']['title'],
                        data['source']['original_url'],
                        data['source']['duration']
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
            icon_url=icon_url
        )


class TrackEmbed(Embed):
    def __init__(self, source: dict, user: Member, icon_url: str):
        super().__init__(title=source['title'], url=source['original_url'])

        self.add_field(name='Запрошено пользователем :', value=f'`{user.split("#")[0]}`', inline=True)
        self.add_field(name='Длительность :', value='`{}`'.format(source['duration']), inline=True)
        self.set_footer(text='YouTube', icon_url=icon_url)


class PlayNowEmbed(TrackEmbed):
    def __init__(self, source: dict, user: Member, icon_url: str):
        super().__init__(source, user, icon_url)

        self.color = 15548997
        self.set_author(name=source['channel'], url=source['channel_url'])
        self.set_image(url=source['thumbnail'])


class PlayQueueEmbed(TrackEmbed):
    def __init__(self, source: dict, user: Member, icon_url: str):
        super().__init__(source, user, icon_url)

        self.set_author(name='Трек добавлен в очередь')
        self.set_thumbnail(url=source['thumbnail'])
