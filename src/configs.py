import os
from dotenv import load_dotenv


load_dotenv()


class BotConfig:
    TOKEN = os.getenv('BOT_TOKEN')

    DEBUG = bool(int(os.getenv('DEBUG')))


class DatabaseConfig:
    HOST = os.getenv('POSTGRES_HOST')
    PORT = int(os.getenv('POSTGRES_PORT'))
    USER = os.getenv('POSTGRES_USER')
    PASSWORD = os.getenv('POSTGRES_PASSWORD')
    DB = os.getenv('POSTGRES_DB')
