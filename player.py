import asyncio

import db
from audio import make_source, related, resolve
from lang import t


class Player:
    """Per-guild playback state: queue, history, current track, autoplay loop."""

    def __init__(self, bot, voice_client, channel, autoplay=True):
        self.bot = bot
        self.vc = voice_client
        self.channel = channel  # text channel to post "now playing" + controls
        self.queue = []         # [(title, vid, requester), ...] upcoming
        self.history = []       # [(title, vid, requester), ...] previously played
        self.current = None     # (title, vid, requester) playing now
        self.autoplay = autoplay  # when queue empties, pull a related track
        self.seen = set()       # video ids already played, so radio doesn't repeat
        self.now_msg = None     # last "now playing" message, deleted when the next one posts
        self.controller = None  # name of whoever last used a control button

    async def _snapshot(self):
        """Persist current+queue so a restart can resume this guild."""
        q = ([list(self.current)] if self.current else []) + [list(t) for t in self.queue]
        await db.save_resume(self.vc.guild.id, self.vc.channel.id, self.channel.id, q)

    def add(self, title, vid, requester=""):
        self.queue.append((title, vid, requester))  # stream URL resolved lazily at play time

    def _after(self, error):
        # runs in a voice thread when a track ends -> advance from the bot loop
        if not self.vc.is_connected():
            return
        asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

    async def play_next(self):
        if not self.queue and self.autoplay and self.current:
            await self._autoplay_fill()  # radio: queue a related track
        if not self.queue:
            self.current = None
            return
        if self.current:
            self.history.append(self.current)
        title, vid, requester = self.queue.pop(0)
        self.current = (title, vid, requester)
        self.seen.add(vid)
        url, _, _ = await asyncio.to_thread(resolve, f"https://www.youtube.com/watch?v={vid}")
        self.vc.play(make_source(url), after=self._after)
        await self._announce()
        await self._snapshot()

    async def _autoplay_fill(self):
        seed = self.current[1] if self.current else None
        nxt = await asyncio.to_thread(related, seed, self.seen)
        if nxt:
            label = await t(self.vc.guild.id, "autoplay_name")
            self.queue.append((nxt[0], nxt[1], label))  # (title, vid, requester)
        else:
            await self.channel.send("⏹️ Autoplay found no related track — stopping.")

    async def play_previous(self):
        if not self.history:
            return False
        # queue: [prev, current, ...rest]; then restart playback from the front
        if self.current:
            self.queue.insert(0, self.current)
        self.queue.insert(0, self.history.pop())
        self.current = None
        if self.vc.is_playing() or self.vc.is_paused():
            self.vc.stop()  # _after fires -> play_next picks up [prev] from front
        else:
            await self.play_next()
        return True

    def pause(self):
        if self.vc.is_playing():
            self.vc.pause()
            return True
        if self.vc.is_paused():
            self.vc.resume()
            return True
        return False

    def jump_to(self, index):
        """Drop queue entries before `index`, then start that track now."""
        if not (0 <= index < len(self.queue)):
            return False
        del self.queue[:index]  # drop everything before the chosen track
        if self.vc.is_playing() or self.vc.is_paused():
            self.vc.stop()  # _after -> play_next pops the now-front track
        else:
            asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)
        return True

    def skip(self):
        if self.vc.is_playing() or self.vc.is_paused():
            self.vc.stop()  # triggers _after -> play_next
            return True
        return False

    async def stop(self):
        import discord

        guild_id = self.vc.guild.id
        self.queue.clear()
        self.current = None
        if self.now_msg:
            try:
                await self.now_msg.delete()
            except discord.HTTPException:
                pass
            self.now_msg = None
        if self.vc.is_connected():
            await self.vc.disconnect()
        await db.clear_resume(guild_id)

    async def _announce(self):
        import discord
        from controls import Controls  # local import avoids circular import

        if self.now_msg:  # delete the previous now-playing message
            try:
                await self.now_msg.delete()
            except discord.HTTPException:
                pass
            self.now_msg = None
        if self.current:
            gid = self.vc.guild.id
            title, vid, requester = self.current
            embed = discord.Embed(
                title=title,
                url=f"https://youtu.be/{vid}",
                description=await t(gid, "now_playing"),
                color=discord.Color.blurple(),
            )
            embed.add_field(name=await t(gid, "requested_by"), value=requester or "—", inline=True)
            if self.controller:
                embed.add_field(name=await t(gid, "controlled_by"), value=self.controller, inline=True)
            embed.set_thumbnail(url=f"https://img.youtube.com/vi/{vid}/mqdefault.jpg")
            embed.set_footer(text=await t(gid, "in_queue", n=len(self.queue)))
            self.now_msg = await self.channel.send(embed=embed, view=Controls(self))
