import asyncio

import discord
from discord.ext import commands

import db
from audio import fmt_duration, resolve_list
from audio import search as yt_search  # aliased: the /search command below shadows the name
from config import DASHBOARD, DASHBOARD_PORT, GUILD_ID, PREFIX
from lang import LANGS, set_lang, t
from perms import can_control, resolve_control
from player import Player

async def get_prefix(bot, message):
    gid = message.guild.id if message.guild else None
    return await db.get_prefix(gid, PREFIX) if gid else PREFIX


async def ensure_voice(ctx):
    """Return a voice client in the caller's channel, reusing an existing connection.

    Discord tracks the real connection on ctx.guild.voice_client, which can outlive
    our players dict (e.g. after a gateway reconnect) — connecting again raises
    'Already connected'. So reuse/move that client rather than always calling connect().
    """
    vc = ctx.guild.voice_client
    target = ctx.author.voice.channel
    if vc and vc.is_connected():
        if vc.channel != target:
            await vc.move_to(target)
        return vc
    return await target.connect()


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)
players = {}  # guild_id -> Player


def get_player(ctx):
    return players.get(ctx.guild.id)


async def get_or_make_player(ctx):
    """Return this guild's Player, rebuilding it if the connection is orphaned.

    After a gateway reconnect the voice client can outlive our players dict; ensure_voice
    reuses that client, but its old playback (and any stuck ffmpeg) is stale, so we stop it
    and hand back a fresh Player.
    """
    player = get_player(ctx)
    if player and player.vc.is_connected():
        return player
    vc = await ensure_voice(ctx)
    if vc.is_playing() or vc.is_paused():
        vc.stop()  # orphaned playback from before the reconnect — start clean
    settings = await db.get_settings(ctx.guild.id)
    player = players[ctx.guild.id] = Player(bot, vc, ctx.channel, autoplay=settings["autoplay"])

    resume = await db.get_resume(ctx.guild.id)  # queue lost on reconnect — restore it
    if resume and resume["queue"]:
        for title, vid, *rest in resume["queue"]:
            player.add(title, vid, rest[0] if rest else "")
        await player.play_next()  # queue[0] was the track playing before the drop
    return player


async def check_alone(player):
    """Arm the auto-leave timer if the bot is already alone (nobody joined via an event)."""
    if all(m.bot for m in player.vc.channel.members):
        settings = await db.get_settings(player.vc.guild.id)
        player.schedule_leave(settings["leave_after"])


async def reply(ctx, content, **kwargs):
    """Send a command reply that self-deletes after 30s, and delete the invoking !message."""
    if ctx.interaction is None:  # prefix command: remove the user's "!..." message
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
    return await ctx.send(content, delete_after=30, **kwargs)


async def gate(ctx, player, action):
    """Permission-or-vote gate. Returns True if the caller's action should proceed.

    Privileged users pass straight through. Others cast a vote; when a majority of the
    voice channel's listeners agree, the action runs. Sends the appropriate notice either way.
    """
    proceed, status, have, need = await resolve_control(ctx.author, player, action)
    if status == "voted":
        key = "vote_registered" if need else "no_permission"
        await reply(ctx, await t(ctx.guild.id, key, action=action, have=have, need=need))
    return proceed


_synced = False


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        return await reply(ctx, await t(ctx.guild.id, "admin_only"))
    raise error


@bot.event
async def on_ready():
    global _synced
    if _synced:  # on_ready can fire more than once (reconnects)
        return
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)       # mirror commands onto this guild
        synced = await bot.tree.sync(guild=guild)  # guild sync is instant
    else:
        synced = await bot.tree.sync()             # global sync (up to ~1h to appear)
    _synced = True
    print(f"Logged in as {bot.user} — synced {len(synced)} commands: {[c.name for c in synced]}")
    if DASHBOARD:
        from web import start_dashboard

        await start_dashboard(bot, players, DASHBOARD_PORT)
    await resume_all()


@bot.event
async def on_voice_state_update(member, before, after):
    """Start/cancel the auto-leave timer as people leave/join the bot's channel."""
    player = players.get(member.guild.id)
    if not player or not player.vc.is_connected():
        return
    chan = player.vc.channel
    if member.id == bot.user.id and after.channel is None:  # bot got disconnected
        return player.cancel_leave()
    alone = all(m.bot for m in chan.members)
    if alone:
        settings = await db.get_settings(member.guild.id)
        player.schedule_leave(settings["leave_after"])
    else:
        player.cancel_leave()


@bot.hybrid_command(description="Seconds alone before the bot leaves and clears the queue (0 = never)")
async def leavetime(ctx, seconds: int):
    seconds = max(0, seconds)
    await db.set_setting(ctx.guild.id, "leave_after", seconds)
    key = "leavetime_off" if seconds == 0 else "leavetime_set"
    await reply(ctx, await t(ctx.guild.id, key, n=seconds))


@bot.hybrid_command(description="Play or queue a track from a URL or search term")
async def play(ctx, *, query):
    await ctx.defer()  # resolving can take a few seconds; ack the slash interaction
    gid = ctx.guild.id
    if not ctx.author.voice:
        return await reply(ctx, await t(gid, "join_voice"))

    player = await get_or_make_player(ctx)

    tracks = await asyncio.to_thread(resolve_list, query)
    if not tracks:
        return await reply(ctx, await t(gid, "not_found"))
    for title, vid in tracks:
        player.add(title, vid, ctx.author.display_name, ctx.author.id)

    if player.vc.is_playing() or player.vc.is_paused():
        await player._snapshot()      # capture the newly-queued tracks
        await player._announce()      # re-post now-playing so its dropdown shows the new queue
        if len(tracks) == 1:
            await reply(ctx, await t(gid, "queued_one", title=tracks[0][0]))
        else:
            await reply(ctx, await t(gid, "queued_many", n=len(tracks)))
    else:
        await reply(ctx, await t(gid, "loading", title=tracks[0][0]))
        await player.play_next()


@bot.hybrid_command(description="Search YouTube and pick a track to queue")
async def search(ctx, *, query):
    await ctx.defer()
    gid = ctx.guild.id
    if not ctx.author.voice:
        return await reply(ctx, await t(gid, "join_voice"))

    results = await asyncio.to_thread(yt_search, query)
    if not results:
        return await reply(ctx, await t(gid, "not_found"))

    select = discord.ui.Select(
        placeholder=await t(gid, "search_placeholder"),
        options=[
            discord.SelectOption(
                label=(title or "?")[:100],
                value=str(i),
                description=f"{channel} • {fmt_duration(duration)}"[:100],
            )
            for i, (title, _, duration, channel) in enumerate(results)
        ],
    )

    async def pick(interaction):
        title, vid = results[int(select.values[0])][:2]
        if not interaction.user.voice:
            return await interaction.response.send_message(await t(gid, "join_voice"), ephemeral=True)
        player = await get_or_make_player(ctx)
        player.add(title, vid, interaction.user.display_name, interaction.user.id)
        await interaction.response.send_message(await t(gid, "queued_one", title=title))
        if player.vc.is_playing() or player.vc.is_paused():
            await player._snapshot()
            await player._announce()
        else:
            await player.play_next()

    select.callback = pick
    view = discord.ui.View(timeout=60)
    view.add_item(select)
    await reply(ctx, await t(gid, "search_results", query=query), view=view)


@bot.hybrid_command(description="List all commands")
async def help(ctx):
    lines = [f"`/{c.name}` — {c.description}" for c in sorted(bot.commands, key=lambda c: c.name)]
    await reply(ctx, "\n".join(lines))


@bot.hybrid_command(description="Play a track next (front of the queue)")
async def playtop(ctx, *, query):
    await ctx.defer()
    gid = ctx.guild.id
    if not ctx.author.voice:
        return await reply(ctx, await t(gid, "join_voice"))

    player = await get_or_make_player(ctx)

    tracks = await asyncio.to_thread(resolve_list, query)
    if not tracks:
        return await reply(ctx, await t(gid, "not_found"))
    for title, vid in reversed(tracks):  # reversed so inserts at 0 keep playlist order
        player.add(title, vid, ctx.author.display_name, ctx.author.id, top=True)

    if player.vc.is_playing() or player.vc.is_paused():
        await player._snapshot()
        await player._announce()  # refresh now-playing so its dropdown shows the new queue
        await reply(ctx, await t(gid, "queued_top", title=tracks[0][0]))
    else:
        await reply(ctx, await t(gid, "loading", title=tracks[0][0]))
        await player.play_next()


@bot.hybrid_command(description="Skip the current track")
async def skip(ctx):
    player = get_player(ctx)
    if not await gate(ctx, player, "skip"):
        return
    key = "skipped" if player and player.skip() else "nothing_playing"
    await reply(ctx, await t(ctx.guild.id, key))


@bot.hybrid_command(description="Play the previous track")
async def previous(ctx):
    player = get_player(ctx)
    if not await gate(ctx, player, "previous"):
        return
    ok = await player.play_previous() if player else False
    await reply(ctx, await t(ctx.guild.id, "previous" if ok else "no_previous"))


@bot.hybrid_command(description="Pause or resume playback")
async def pause(ctx):
    player = get_player(ctx)
    if not await gate(ctx, player, "pause"):
        return
    key = "toggled" if player and player.pause() else "nothing_playing"
    await reply(ctx, await t(ctx.guild.id, key))


@bot.hybrid_command(description="Toggle queue-empty autoplay (YouTube radio)")
async def autoplay(ctx):
    player = get_player(ctx)
    if not player:
        return await reply(ctx, await t(ctx.guild.id, "nothing_playing"))
    if not await can_control(ctx.author, player):
        return await reply(ctx, await t(ctx.guild.id, "no_permission"))
    player.autoplay = not player.autoplay
    await db.set_setting(ctx.guild.id, "autoplay", player.autoplay)
    await reply(ctx, await t(ctx.guild.id, "autoplay_on" if player.autoplay else "autoplay_off"))


@bot.hybrid_command(description="Show the queue; pick a track to jump to it")
async def queue(ctx):
    from controls import QueueSelect

    player = get_player(ctx)
    if not player or not player.queue:
        return await reply(ctx, await t(ctx.guild.id, "queue_empty"))
    listing = "\n".join(f"{i+1}. {row[0]}" for i, row in enumerate(player.queue))
    await reply(ctx, listing, view=QueueSelect(player))


@bot.hybrid_command(description="Cycle loop mode: off → one track → whole queue")
async def loop(ctx):
    player = get_player(ctx)
    if not player:
        return await reply(ctx, await t(ctx.guild.id, "nothing_playing"))
    if not await gate(ctx, player, "loop"):
        return
    mode = player.cycle_loop()
    await player._snapshot()  # keep on-disk state consistent (loop is runtime-only, but cheap)
    await reply(ctx, await t(ctx.guild.id, f"loop_{mode}"))


@bot.hybrid_command(description="Shuffle the upcoming queue")
async def shuffle(ctx):
    player = get_player(ctx)
    if not player:
        return await reply(ctx, await t(ctx.guild.id, "nothing_playing"))
    if not await gate(ctx, player, "shuffle"):
        return
    if not player.shuffle():
        return await reply(ctx, await t(ctx.guild.id, "queue_empty"))
    await player._announce()  # refresh now-playing so its jump dropdown reflects the new order
    await reply(ctx, await t(ctx.guild.id, "shuffled"))


@bot.hybrid_command(description="Remove a track from the queue by its position")
async def remove(ctx, position: int):
    player = get_player(ctx)
    if not player or not player.queue:
        return await reply(ctx, await t(ctx.guild.id, "queue_empty"))
    if not await gate(ctx, player, "remove"):
        return
    title = player.remove(position - 1)  # /queue shows 1-based positions
    if title is None:
        return await reply(ctx, await t(ctx.guild.id, "bad_position"))
    await player._snapshot()
    await player._announce()  # refresh jump dropdown after removal
    await reply(ctx, await t(ctx.guild.id, "removed", title=title))


@bot.hybrid_command(description="Clear the queue and disconnect")
async def stop(ctx):
    player = get_player(ctx)
    if player and not await gate(ctx, player, "stop"):
        return
    players.pop(ctx.guild.id, None)
    if player:
        await player.stop()
    await reply(ctx, await t(ctx.guild.id, "stopped"))


@bot.hybrid_command(name="playlist-save", description="Save the current queue under a name")
async def playlist_save(ctx, name):
    player = get_player(ctx)
    tracks = ([list(player.current[:3])] if player and player.current else []) + \
             ([list(row[:3]) for row in player.queue] if player else [])
    if not tracks:
        return await reply(ctx, await t(ctx.guild.id, "nothing_to_save"))
    await db.save_playlist(ctx.guild.id, name, tracks)
    await reply(ctx, await t(ctx.guild.id, "saved", n=len(tracks), name=name))


@bot.hybrid_command(name="playlist-load", description="Load a saved playlist into the queue")
async def playlist_load(ctx, name):
    await ctx.defer()
    gid = ctx.guild.id
    if not ctx.author.voice:
        return await reply(ctx, await t(gid, "join_voice"))
    tracks = await db.load_playlist(gid, name)
    if not tracks:
        return await reply(ctx, await t(gid, "no_playlist", name=name))

    player = await get_or_make_player(ctx)

    for title, vid, *rest in tracks:
        player.add(title, vid, rest[0] if rest else ctx.author.display_name, ctx.author.id)
    if player.vc.is_playing() or player.vc.is_paused():
        await player._snapshot()
        await player._announce()
        await reply(ctx, await t(gid, "loaded", n=len(tracks), name=name))
    else:
        await reply(ctx, await t(gid, "loading_playlist", name=name))
        await player.play_next()


@bot.hybrid_command(description="Set this server's command prefix")
async def prefix(ctx, new_prefix):
    await db.set_setting(ctx.guild.id, "prefix", new_prefix)
    await reply(ctx, await t(ctx.guild.id, "prefix_set", prefix=new_prefix))


@bot.hybrid_command(description="Set this server's language")
async def language(ctx, code):
    if await set_lang(ctx.guild.id, code):
        await reply(ctx, await t(ctx.guild.id, "language_set", lang=code))
    else:
        await reply(ctx, await t(ctx.guild.id, "bad_language", langs=", ".join(LANGS)))


@bot.hybrid_command(name="dj-add", description="Admin: allow a role to control any track")
@commands.has_permissions(administrator=True)
async def dj_add(ctx, role: discord.Role):
    await db.add_dj_role(ctx.guild.id, role.id)
    await reply(ctx, await t(ctx.guild.id, "dj_added", role=role.name))


@bot.hybrid_command(name="dj-remove", description="Admin: remove a DJ role")
@commands.has_permissions(administrator=True)
async def dj_remove(ctx, role: discord.Role):
    await db.remove_dj_role(ctx.guild.id, role.id)
    await reply(ctx, await t(ctx.guild.id, "dj_removed", role=role.name))


@bot.hybrid_command(name="dj-list", description="List this server's DJ roles")
async def dj_list(ctx):
    ids = (await db.get_settings(ctx.guild.id))["dj_roles"]
    names = [r.mention for rid in ids if (r := ctx.guild.get_role(rid))]
    key = "dj_list" if names else "dj_none"
    await reply(ctx, await t(ctx.guild.id, key, roles=", ".join(names)))


@bot.hybrid_command(name="playlists", description="List saved playlists")
async def playlists(ctx):
    names = await db.list_playlists(ctx.guild.id)
    if names:
        await reply(ctx, await t(ctx.guild.id, "playlists", names=", ".join(names)))
    else:
        await reply(ctx, await t(ctx.guild.id, "no_playlists"))


async def resume_all():
    """On startup, rebuild queues from MongoDB and rejoin voice; drop ones we can't rejoin."""
    for doc in await db.all_resumes():
        guild_id, voice_id = doc["_id"], doc["voice_id"]
        channel = bot.get_channel(doc["channel_id"])
        voice = bot.get_channel(voice_id)
        if not voice or not channel:  # channel gone -> terminate this queue
            await db.clear_resume(guild_id)
            continue
        try:
            vc = await voice.connect()
        except (discord.ClientException, discord.HTTPException, asyncio.TimeoutError):
            await db.clear_resume(guild_id)  # couldn't rejoin -> terminate
            continue
        settings = await db.get_settings(guild_id)
        player = players[guild_id] = Player(bot, vc, channel, autoplay=settings["autoplay"])
        for title, vid, *rest in doc["queue"]:
            player.add(title, vid, rest[0] if rest else "")
        await player.play_next()
        await check_alone(player)
