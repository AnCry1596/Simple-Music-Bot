import sys

import discord
import yt_dlp

from config import FFMPEG_OPTS, YDL_OPTS


def resolve(query):
    """yt-dlp -> (stream_url, title, video_id). Runs blocking; call via asyncio.to_thread."""
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return info["url"], info.get("title", query), info.get("id")


def resolve_list(query, limit=25):
    """Expand a playlist into [(title, video_id), ...] (flat, no stream URLs).
    Falls back to a single [(title, id)] for a normal video/search. Blocking."""
    opts = {**YDL_OPTS, "noplaylist": False, "extract_flat": True, "playlist_items": f"1-{limit}"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
    entries = info.get("entries") or [info]
    return [(e.get("title", "?"), e.get("id")) for e in entries if e.get("id")]


def related(video_id, seen):
    """Next track from YouTube's radio mix for video_id, skipping ids in `seen`.
    Returns (title, vid) or None. Blocking; call via asyncio.to_thread."""
    if not video_id:
        return None
    # RD<id> is YouTube's auto-generated radio playlist for that video.
    opts = {**YDL_OPTS, "noplaylist": False, "playlist_items": "1-15", "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        mix = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}", download=False)
        for entry in mix.get("entries", []):
            vid = entry.get("id")
            if vid and vid not in seen:
                return (entry.get("title", "?"), vid)
    return None


def make_source(url):
    """FFmpeg PCM source from a stream URL. stderr -> console so ffmpeg errors are visible."""
    return discord.FFmpegPCMAudio(url, stderr=sys.stderr, **FFMPEG_OPTS)
