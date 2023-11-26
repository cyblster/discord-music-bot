from typing import List
from datetime import datetime

from sqlalchemy import (
    MetaData,
    Integer,
    BigInteger,
    DateTime,
    func,
    select
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import create_async_engine

from src.configs import (
    BotConfig,
    DatabaseConfig
)


DB_URI = f'postgresql+asyncpg://{DatabaseConfig.USER}:{DatabaseConfig.PASSWORD}' \
         f'@{DatabaseConfig.HOST}:{DatabaseConfig.PORT}/{DatabaseConfig.DB}'


async_engine = create_async_engine(DB_URI, echo=BotConfig.DEBUG, future=True)


class BaseModal(DeclarativeBase):
    __abstract__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    added: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_onupdate=func.now(), nullable=True)

    metadata = MetaData(naming_convention={
        "ix": 'ix_%(column_0_label)s',
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s"
    })


class MusicModel(BaseModal):
    __tablename__ = 'music'

    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    track_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    queue_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    @classmethod
    async def setup(cls, guild_id: int, channel_id: int, track_message_id: int, queue_message_id: int) -> None:
        async with async_engine.connect() as db:
            query = (
                insert(cls)
                .values(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    track_message_id=track_message_id,
                    queue_message_id=queue_message_id
                )
                .on_conflict_do_update(
                    index_elements=[cls.guild_id],
                    set_=dict(
                        guild_id=guild_id,
                        channel_id=channel_id,
                        track_message_id=track_message_id,
                        queue_message_id=queue_message_id
                    )
                )
            )

            await db.execute(query)
            await db.commit()

    @classmethod
    async def get_all(cls) -> List["MusicModel"]:
        async with async_engine.connect() as db:
            query = (
                select(cls)
            )

            music_models = (await db.execute(query)).all()

            return music_models

    @classmethod
    async def get_by_guild_id(cls, guild_id: int) -> "MusicModel":
        async with async_engine.connect() as db:
            query = (
                select(cls)
                .filter_by(guild_id=guild_id)
            )

            music_model = (await db.execute(query)).one_or_none()

            return music_model
