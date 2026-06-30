"""Per-server translations. Strings live in language.json; per-guild choice in Mongo."""
import json
from pathlib import Path

import db
from config import DEFAULT_LANG

_STRINGS = json.loads((Path(__file__).parent / "language.json").read_text(encoding="utf-8"))
LANGS = list(_STRINGS)
_cache = {}  # guild_id -> lang code


async def lang_of(guild_id):
    if guild_id not in _cache:
        s = await db.get_settings(guild_id)
        _cache[guild_id] = s.get("language", DEFAULT_LANG)
    return _cache[guild_id]


async def set_lang(guild_id, code):
    if code not in _STRINGS:
        return False
    await db.set_setting(guild_id, "language", code)
    _cache[guild_id] = code
    return True


async def t(guild_id, key, **kw):
    await lang_of(guild_id)  # warm the cache
    return t_sync(guild_id, key, **kw)


def t_sync(guild_id, key, **kw):
    """Sync lookup using the cached lang (for UI built outside async). Falls back to default."""
    code = _cache.get(guild_id, DEFAULT_LANG)
    table = _STRINGS.get(code, _STRINGS[DEFAULT_LANG])
    text = table.get(key) or _STRINGS[DEFAULT_LANG].get(key, key)
    return text.format(**kw) if kw else text
