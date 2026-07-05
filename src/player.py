import asyncio
import random

import db
from audio import make_source, related, resolve, watch_url
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
        self._leave_task = None  # pending auto-leave timer when alone in voice
        self.votes = {}         # action -> set of user ids who've voted this round
        self.loop = "off"       # "off" | "one" (repeat current) | "all" (requeue after playing)

    def listeners(self):
        """Human (non-bot) members currently in the bot's voice channel."""
        return [m for m in self.vc.channel.members if not m.bot]

    def add_vote(self, action, user_id):
        """Record a vote; return (votes_so_far, needed) for a majority of current listeners."""
        self.votes.setdefault(action, set()).add(user_id)
        needed = len(self.listeners()) // 2 + 1  # strict majority
        return len(self.votes[action]), needed

    def clear_votes(self):
        self.votes.clear()  # call after any action runs, so the next round starts fresh

    def schedule_leave(self, seconds):
        """Disconnect + terminate the queue after `seconds` alone. 0 disables. Resets any pending timer."""
        self.cancel_leave()
        if seconds:
            self._leave_task = asyncio.create_task(self._leave_after(seconds))

    def cancel_leave(self):
        if self._leave_task:
            self._leave_task.cancel()
            self._leave_task = None

    async def _leave_after(self, seconds):
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        self._leave_task = None
        await self.stop()

    async def _snapshot(self):
        """Persist current+queue so a restart can resume this guild. Drops requester_id (index 3)."""
        rows = ([self.current] if self.current else []) + list(self.queue)
        q = [list(t[:3]) for t in rows]
        await db.save_resume(self.vc.guild.id, self.vc.channel.id, self.channel.id, q)

    def requester_id(self):
        """Discord user id of whoever requested the now-playing track, or None (autoplay/resumed)."""
        return self.current[3] if self.current and len(self.current) > 3 else None

    def add(self, title, vid, requester="", requester_id=None, top=False):
        # tuple: (title, vid, requester_name, requester_id); id is runtime-only, not persisted
        track = (title, vid, requester, requester_id)  # stream URL resolved lazily
        if top:
            self.queue.insert(0, track)
        else:
            self.queue.append(track)

    def _after(self, error):
        # runs in a voice thread when a track ends -> advance from the bot loop
        if not self.vc.is_connected():
            return
        asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

    async def play_next(self):
        if self.loop == "one" and self.current:
            await self._start(self.current)  # replay the same track
            return
        if self.loop == "all" and self.current:
            self.queue.append(self.current)  # cycle: send finished track to the back
        if not self.queue and self.autoplay and self.current:
            await self._autoplay_fill()  # radio: queue a related track
        if not self.queue:
            self.current = None
            return
        if self.current:
            self.history.append(self.current)
        await self._start(self.queue.pop(0))  # (title, vid, requester, requester_id)

    async def _start(self, track):
        self.current = track
        vid = self.current[1]
        self.seen.add(vid)
        self.clear_votes()  # new track -> old skip/pause votes are stale
        url, _, _ = await asyncio.to_thread(resolve, watch_url(vid))
        self.vc.play(make_source(url), after=self._after)
        await self._announce()
        await self._snapshot()

    async def _autoplay_fill(self):
        seed = self.current[1] if self.current else None
        nxt = await asyncio.to_thread(related, seed, self.seen)
        if nxt:
            label = await t(self.vc.guild.id, "autoplay_name")
            self.queue.append((nxt[0], nxt[1], label, None))  # autoplay: no requester id
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

    def shuffle(self):
        """Randomize the upcoming queue in place. Returns False if nothing to shuffle."""
        if len(self.queue) < 2:
            return False
        random.shuffle(self.queue)
        return True

    def cycle_loop(self):
        """Advance loop mode off -> one -> all -> off. Returns the new mode."""
        self.loop = {"off": "one", "one": "all", "all": "off"}[self.loop]
        return self.loop

    def remove(self, index):
        """Drop queue entry at `index`. Returns its title, or None if out of range."""
        if not (0 <= index < len(self.queue)):
            return None
        return self.queue.pop(index)[0]

    def skip(self):
        if self.vc.is_playing() or self.vc.is_paused():
            self.vc.stop()  # triggers _after -> play_next
            return True
        return False

    async def stop(self):
        import discord

        guild_id = self.vc.guild.id
        self.cancel_leave()
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
            title, vid, requester = self.current[:3]
            embed = discord.Embed(
                title=title,
                url=vid if vid.startswith("http") else f"https://youtu.be/{vid}",
                description=await t(gid, "now_playing"),
                color=discord.Color.blurple(),
            )
            embed.add_field(name=await t(gid, "requested_by"), value=requester or "—", inline=True)
            if self.controller:
                embed.add_field(name=await t(gid, "controlled_by"), value=self.controller, inline=True)
            if not vid.startswith("http"):  # thumbnail only known for YouTube ids
                embed.set_thumbnail(url=f"https://img.youtube.com/vi/{vid}/mqdefault.jpg")
            embed.set_footer(text=await t(gid, "in_queue", n=len(self.queue)))
            self.now_msg = await self.channel.send(embed=embed, view=Controls(self))
