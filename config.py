import os

from dotenv import load_dotenv

load_dotenv()  # read .env into os.environ

TOKEN = os.environ["DISCORD_TOKEN"]
PREFIX = os.environ.get("PREFIX", "!")
GUILD_ID = int(os.environ["GUILD_ID"]) if os.environ.get("GUILD_ID") else None  # instant per-guild sync; None = global
MONGO_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGODB_DB_NAME", "musicbot")
DEFAULT_LANG = os.environ.get("LANGUAGE", "en")

YDL_OPTS = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "remote_components": ["ejs:github"],  # let yt-dlp use deno to solve YouTube's n-challenge
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}
