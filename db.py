"""MongoDB persistence: per-guild settings, saved playlists, resume snapshots.

Collections (all keyed by guild_id):
  settings  {_id: guild_id, autoplay: bool}
  playlists {_id: guild_id, names: {name: [[title, vid], ...]}}
  resume    {_id: guild_id, voice_id, channel_id, queue: [[title, vid], ...]}
"""
from motor.motor_asyncio import AsyncIOMotorClient

from config import DB_NAME, MONGO_URI

_db = AsyncIOMotorClient(MONGO_URI)[DB_NAME]


# --- settings ---
async def get_settings(guild_id):
    doc = await _db.settings.find_one({"_id": guild_id}) or {"_id": guild_id}
    doc.setdefault("autoplay", True)  # fill defaults for docs saved before this field existed
    doc.setdefault("leave_after", 60)  # seconds alone before auto-leave; 0 = never
    doc.setdefault("dj_roles", [])     # role ids allowed to control any track
    return doc


async def get_prefix(guild_id, default):
    doc = await _db.settings.find_one({"_id": guild_id})
    return (doc or {}).get("prefix", default)


async def set_setting(guild_id, key, value):
    await _db.settings.update_one({"_id": guild_id}, {"$set": {key: value}}, upsert=True)


async def add_dj_role(guild_id, role_id):
    await _db.settings.update_one({"_id": guild_id}, {"$addToSet": {"dj_roles": role_id}}, upsert=True)


async def remove_dj_role(guild_id, role_id):
    await _db.settings.update_one({"_id": guild_id}, {"$pull": {"dj_roles": role_id}})


# --- saved playlists ---
async def save_playlist(guild_id, name, tracks):
    await _db.playlists.update_one(
        {"_id": guild_id}, {"$set": {f"names.{name}": tracks}}, upsert=True
    )


async def load_playlist(guild_id, name):
    doc = await _db.playlists.find_one({"_id": guild_id})
    return (doc or {}).get("names", {}).get(name)


async def list_playlists(guild_id):
    doc = await _db.playlists.find_one({"_id": guild_id})
    return list((doc or {}).get("names", {}).keys())


# --- resume snapshot ---
async def save_resume(guild_id, voice_id, channel_id, queue):
    await _db.resume.update_one(
        {"_id": guild_id},
        {"$set": {"voice_id": voice_id, "channel_id": channel_id, "queue": queue}},
        upsert=True,
    )


async def get_resume(guild_id):
    return await _db.resume.find_one({"_id": guild_id})


async def clear_resume(guild_id):
    await _db.resume.delete_one({"_id": guild_id})


async def all_resumes():
    return [doc async for doc in _db.resume.find()]
