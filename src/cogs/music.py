from typing import List, Dict, Optional

import asyncio
import discord
import dataclasses

from datetime import datetime, timedelta
from yt_dlp import YoutubeDL

from src.models import MusicModel


@dataclasses.dataclass
class TrackAbstract:
    user: discord.Member
    url: str
    title: str
    original_url: str
    channel: str
    channel_url: str
    thumbnail: str
    duration: int

    @classmethod
    def from_dict(cls, dict_) -> "TrackAbstract":
        field_names = set([field.name for field in dataclasses.fields(cls)])

        return cls(**{k: v for k, v in dict_.items() if k in field_names})


class EmojiMapping:
    SpeechBalloon = '💬'
    SkipTrack = '⏭'
    NoEntry = '⛔'


class MusicCog(discord.ext.commands.Cog):
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

    bot: discord.ext.commands.Bot
    queue: Dict[int, List[TrackAbstract]]

    def __init__(self, bot: discord.ext.commands.Bot):
        self.bot = bot

        self.queue = {guild.id: [] for guild in self.bot.guilds}

        super().__init__()

        bot.loop.create_task(self.restore_views())

    @staticmethod
    def user_is_administrator(user: discord.Member) -> bool:
        return user.guild_permissions.administrator

    @staticmethod
    def is_user_connected(user: discord.Member) -> bool:
        return user.voice is not None

    @staticmethod
    def get_formatted_duration(duration: Optional[int]) -> str:
        if duration is None:
            return 'Неизвестно'

        dt = datetime.utcfromtimestamp(duration)
        if dt.day == 1:
            if dt.hour == 0:
                return dt.strftime('%M:%S')
            return dt.strftime('%H:%M:%S')

        dt -= timedelta(days=1)
        return dt.strftime('%d:%H:%M:%S')

    async def connect_to_user(self, user: discord.Member) -> None:
        if not self.bot.get_guild(user.guild.id).voice_client:
            await self.bot.get_channel(user.voice.channel.id).connect()

    async def disconnect_from_guild(self, guild: discord.Guild) -> None:
        voice_client = self.bot.get_guild(guild.id).voice_client
        if voice_client:
            await voice_client.disconnect(force=True)

    def is_user_with_bot(self, user: discord.Member) -> bool:
        voice_client = self.bot.get_guild(user.guild.id).voice_client
        if not voice_client:
            return False

        if not self.is_user_connected(user):
            return False

        return user.voice.channel == voice_client.channel

    def is_first_track(self, guild_id: int) -> bool:
        return len(self.queue[guild_id]) == 1

    def is_queue_empty(self, guild_id: int) -> bool:
        return len(self.queue[guild_id]) == 0

    def add_track_to_queue(self, guild_id, track: TrackAbstract):
        self.queue[guild_id].append(track)

    async def play_track(self, guild: discord.Guild, first_track: bool = False) -> None:
        if not first_track:
            self.queue[guild.id].pop(0)

        music_model = await MusicModel.get_by_guild_id(guild.id)
        channel = self.bot.get_channel(music_model.channel_id)

        track_message = await channel.fetch_message(music_model.track_message_id)
        queue_message = await channel.fetch_message(music_model.queue_message_id)

        await queue_message.edit(embed=QueueEmbed(self.queue[channel.guild.id]))
        if not self.is_queue_empty(channel.guild.id):
            await track_message.edit(
                embed=PlayNowEmbed(self.queue[channel.guild.id][0]),
                view=PlayNowView(self, guild)
            )

            if first_track:
                await self.connect_to_user(self.queue[guild.id][0].user)

            source = discord.FFmpegPCMAudio(
                self.queue[channel.guild.id][0].url,
                **self.FFMPEG_OPTIONS,
                executable='ffmpeg'
            )
            self.bot.get_guild(channel.guild.id).voice_client.play(
                source,
                after=lambda _: asyncio.run_coroutine_threadsafe(
                    self.play_track(guild),
                    self.bot.loop
                )
            )
        else:
            await track_message.edit(embed=NothingPlayEmbed(), view=NothingPlayView(self, guild))
            await self.disconnect_from_guild(guild)

    def skip_track(self, guild: discord.Guild):
        self.bot.get_guild(guild.id).voice_client.stop()

    def clear_queue(self, guild_id):
        self.queue[guild_id] = []

    async def restore_views(self):
        await self.bot.wait_until_ready()

        music_models = await MusicModel.get_all()
        for music_model in music_models:
            channel = self.bot.get_channel(music_model.channel_id)

            track_message = await channel.fetch_message(music_model.track_message_id)
            await track_message.edit(
                embed=NothingPlayEmbed(),
                view=NothingPlayView(self, channel.guild)
            )

            queue_message = await channel.fetch_message(music_model.queue_message_id)
            await queue_message.edit(embed=QueueEmbed(self.queue[channel.guild.id]))

    @discord.ext.commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        self.clear_queue(guild.id)

    @discord.ext.commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        self.queue.pop(guild.id)

    @discord.ext.commands.Cog.listener()
    async def on_voice_state_update(
        self,
        user: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ) -> None:
        if user == self.bot.user:
            if not after.channel:
                music_model = await MusicModel.get_by_guild_id(before.channel.guild.id)
                channel = self.bot.get_channel(music_model.channel_id)

                voice_client = self.bot.get_guild(music_model.guild_id).voice_client
                if voice_client:
                    voice_client.cleanup()
                    track_message = await channel.fetch_message(music_model.track_message_id)
                    await track_message.edit(
                        embed=NothingPlayEmbed(),
                        view=NothingPlayView(self, before.channel.guild)
                    )

                if self.queue[before.channel.guild.id]:
                    self.clear_queue(before.channel.guild.id)
                    queue_message = await channel.fetch_message(music_model.queue_message_id)
                    await queue_message.edit(embed=QueueEmbed(self.queue[before.channel.guild.id]))

        elif before.channel:
            voice_client = before.channel.guild.voice_client
            if voice_client and before.channel == voice_client.channel:
                if len(before.channel.members) == 1 and before.channel.members[0] == self.bot.user:
                    await self.disconnect_from_guild(before.channel.guild)

    @discord.app_commands.command(name='setup', description='Выбрать текущий канал в качестве музыкального')
    async def command_setup(self, interaction: discord.Interaction) -> None:
        if not self.user_is_administrator(interaction.user):
            return await interaction.response.send_message(
                f'{EmojiMapping.NoEntry} Данная команда доступна только администратору сервера.',
                ephemeral=True,
                delete_after=10
            )

        await interaction.channel.edit(
            topic=f'Канал музыкального бота {self.bot.user.name.split("#")[0]}',
            overwrites={interaction.guild.default_role: discord.PermissionOverwrite(send_messages=False)}
        )

        await interaction.response.send_message('Производится установка...', ephemeral=True)
        track_message = await interaction.channel.send(
            embed=NothingPlayEmbed(),
            view=NothingPlayView(self, interaction.guild)
        )
        queue_message = await interaction.channel.send(embed=QueueEmbed(self.queue[interaction.guild_id]))
        await MusicModel.setup(
            interaction.guild_id,
            interaction.channel_id,
            track_message_id=track_message.id,
            queue_message_id=queue_message.id
        )
        await interaction.delete_original_response()


class OrderTrackModal(discord.ui.Modal):
    def __init__(self, cog: MusicCog):
        self.cog = cog

        super().__init__(title='Добавить трек в очередь', timeout=None)

        self.add_item(discord.ui.TextInput(label='Введите строку для поиска или URL'))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        with YoutubeDL(self.cog.YDL_OPTIONS) as ydl:
            self.cog.add_track_to_queue(
                interaction.guild_id,
                TrackAbstract.from_dict({
                    **{'user': interaction.user},
                    **ydl.extract_info(self.children[0].value, download=False)
                })
            )

            if self.cog.is_first_track(interaction.guild_id):
                await self.cog.play_track(interaction.guild, first_track=True)
            else:
                music_model = await MusicModel.get_by_guild_id(interaction.guild_id)
                queue_message = await interaction.channel.fetch_message(music_model.queue_message_id)
                await queue_message.edit(embed=QueueEmbed(self.cog.queue[interaction.guild_id]))


class PlayView(discord.ui.View):
    def __init__(self, cog: MusicCog, guild: discord.Guild):
        self.cog = cog
        self.guild = guild

        super().__init__(timeout=600)

    @discord.ui.button(emoji=EmojiMapping.SpeechBalloon, label='Добавить', style=discord.ButtonStyle.green)
    async def btn_add(self, interaction: discord.Interaction, button: discord.Button):
        if not self.cog.is_user_connected(interaction.user):
            return await interaction.response.send_message(
                f'{EmojiMapping.NoEntry} Вы не подключены к голосовому каналу сервера.',
                ephemeral=True,
                delete_after=10
            )

        if not self.cog.is_queue_empty(interaction.guild_id) and not self.cog.is_user_with_bot(interaction.user):
            return await interaction.response.send_message(
                f'{EmojiMapping.NoEntry} Бот уже подключен к голосовому каналу сервера.',
                ephemeral=True,
                delete_after=10
            )

        await interaction.response.send_modal(OrderTrackModal(self.cog))


class NothingPlayView(PlayView):
    def __init__(self, cog: MusicCog, guild: discord.Guild):
        super().__init__(cog, guild)

    @discord.ui.button(emoji=EmojiMapping.SkipTrack, label='Пропустить', style=discord.ButtonStyle.gray, disabled=True)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.Button):
        pass

    @discord.ui.button(label='\u200b', style=discord.ButtonStyle.gray, disabled=True)
    async def btn_stub(self, interaction: discord.Interaction, button: discord.Button):
        pass

    @discord.ui.button(label='Отключить', style=discord.ButtonStyle.danger, disabled=True)
    async def btn_disconnect(self, interaction: discord.Interaction, button: discord.Button):
        pass

    async def on_timeout(self) -> None:
        music_model = await MusicModel.get_by_guild_id(self.guild.id)
        channel = self.cog.bot.get_channel(music_model.channel_id)
        track_message = await channel.fetch_message(music_model.track_message_id)

        await track_message.edit(view=NothingPlayView(self.cog, self.guild))


class PlayNowView(PlayView):
    def __init__(self, cog: MusicCog, guild: discord.Guild):
        super().__init__(cog, guild)

    @discord.ui.button(emoji=EmojiMapping.SkipTrack, label='Пропустить', style=discord.ButtonStyle.gray)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.Button):
        await interaction.response.defer()

        if self.cog.is_user_with_bot(interaction.user):
            self.cog.skip_track(interaction.guild)

    @discord.ui.button(label='\u200b', style=discord.ButtonStyle.gray, disabled=True)
    async def btn_stub(self, interaction: discord.Interaction, button: discord.Button):
        pass

    @discord.ui.button(label='Отключить', style=discord.ButtonStyle.danger)
    async def btn_disconnect(self, interaction: discord.Interaction, button: discord.Button):
        await interaction.response.defer()

        if self.cog.is_user_with_bot(interaction.user):
            await self.cog.disconnect_from_guild(interaction.guild)

    async def on_timeout(self) -> None:
        music_model = await MusicModel.get_by_guild_id(self.guild.id)
        channel = self.cog.bot.get_channel(music_model.channel_id)
        track_message = await channel.fetch_message(music_model.track_message_id)

        await track_message.edit(view=PlayNowView(self.cog, self.guild))


class NothingPlayEmbed(discord.Embed):
    def __init__(self):
        super().__init__(title=f'Сейчас ничего не играет')

        self.add_field(
            name='Подсказка:',
            value='Чтобы воспроизвести трек, воспользуйтесь кнопкой **"Добавить"**.'
        )

        self.colour = 15548997


class PlayNowEmbed(discord.Embed):
    def __init__(self, track: TrackAbstract):
        super().__init__(title=track.title, url=track.original_url)

        self.set_author(name=track.channel, url=track.channel_url)
        self.set_image(url=track.thumbnail)

        self.add_field(name='Запрошено пользователем :', value=f'`{track.user}`', inline=True)
        self.add_field(name='Длительность :', value='`{}`'.format(MusicCog.get_formatted_duration(track.duration)), inline=True)

        self.colour = 15548997
        self.set_footer(text='YouTube', icon_url=MusicCog.YOUTUBE_LOGO_URL)
        
        
class QueueEmbed(discord.Embed):
    def __init__(self, queue: List[TrackAbstract]):
        super().__init__(title='Очередь')

        if len(queue) > 1:
            for i, track in enumerate(queue[1:], 1):
                self.add_field(
                    name='**{}.** {}'.format(i, track.channel),
                    value='[{}]({}) ({})'.format(
                        track.title,
                        track.original_url,
                        MusicCog.get_formatted_duration(track.duration)
                    ),
                    inline=False
                )
            self.add_field(
                name='\u200b',
                value='Чтобы добавить трек в очередь, нажмите на кнопку **"Добавить"**.'
            )
        else:
            self.add_field(
                name='В очереди ничего нет.',
                value='Чтобы добавить трек в очередь, нажмите на кнопку **"Добавить"**.'
            )

        self.colour = 15548997
