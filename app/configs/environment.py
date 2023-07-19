from functools import lru_cache
import os
import pathlib

from pydantic_settings import BaseSettings


@lru_cache
def get_env_filename():
    runtime_env = os.getenv('ENV')
    return f'.env.{runtime_env}' if runtime_env else '.env'


class EnvironmentSettings(BaseSettings):
    TOKEN: str
    FFMPEG_PATH: str

    DEBUG: bool

    class Config:
        env_file = f'{pathlib.Path(__file__).parent.parent.parent}/{get_env_filename()}'
        env_file_encoding = "utf-8"


@lru_cache
def get_environment_variables():
    return EnvironmentSettings()
