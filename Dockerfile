FROM python:3.9
WORKDIR /discord-music-bot
COPY . .
RUN apt-get -y update && apt-get -y upgrade && apt-get install -y --fix-missing ffmpeg
RUN pip install --upgrade pip
RUN pip install -e .
CMD ["/bin/bash", "-c", "python3.9 runner.py"]