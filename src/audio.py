import sys

import discord
import yt_dlp

from config import FFMPEG_OPTS, YDL_OPTS


def track_ref(entry):
    """What we store per track: bare id for YouTube (thumbnails/radio work),
    full webpage URL for any other yt-dlp-supported service."""
    ie = (entry.get("ie_key") or entry.get("extractor") or "").lower()
    if ie.startswith("youtube"):
        return entry.get("id")
    return entry.get("url") or entry.get("webpage_url") or entry.get("id")


def watch_url(ref):
    """Turn a stored track ref back into something yt-dlp can extract."""
    return ref if ref.startswith("http") else f"https://www.youtube.com/watch?v={ref}"


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
    return [(e.get("title", "?"), track_ref(e)) for e in entries if track_ref(e)]


def search(query, n=5):
    """YouTube search -> [(title, ref, duration_secs_or_None, channel)]. Blocking."""
    opts = {**YDL_OPTS, "noplaylist": False, "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    return [(e.get("title", "?"), track_ref(e), e.get("duration"), e.get("channel") or e.get("uploader") or "")
            for e in info.get("entries", []) if track_ref(e)]


def fmt_duration(secs):
    """73 -> '1:13', 3723 -> '1:02:03', None -> 'live'."""
    if not secs:
        return "live"
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def related(video_id, seen):
    """Next track from YouTube's radio mix for video_id, skipping ids in `seen`.
    Returns (title, vid) or None. Blocking; call via asyncio.to_thread."""
    if not video_id or video_id.startswith("http"):
        return None  # radio mixes only exist for YouTube ids
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
