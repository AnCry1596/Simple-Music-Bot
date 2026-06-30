import discord

from lang import t, t_sync


def _gid(player):
    return player.vc.guild.id


class JumpSelect(discord.ui.Select):
    """Dropdown that jumps to a queue track, dropping everything before it."""

    def __init__(self, player):
        self.player = player
        options = [
            discord.SelectOption(label=(row[0] or "?")[:100], value=str(i))
            for i, row in enumerate(player.queue[:25])  # Discord caps selects at 25
        ]
        super().__init__(placeholder=t_sync(_gid(player), "jump_placeholder"), options=options)

    async def callback(self, interaction):
        index = int(self.values[0])
        title = self.player.queue[index][0]
        self.player.controller = interaction.user.display_name
        self.player.jump_to(index)
        await interaction.response.send_message(
            await t(_gid(self.player), "jumping", title=title), ephemeral=True
        )


class QueueSelect(discord.ui.View):
    """Standalone view holding just the jump dropdown (used by /queue)."""

    def __init__(self, player):
        super().__init__(timeout=120)
        self.add_item(JumpSelect(player))


class Controls(discord.ui.View):
    """Playback buttons + (if queue non-empty) the jump dropdown, on the now-playing message."""

    def __init__(self, player):
        super().__init__(timeout=None)
        self.player = player
        if player.queue:
            self.add_item(JumpSelect(player))

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        self.player.controller = interaction.user.display_name
        ok = await self.player.play_previous()
        await interaction.response.send_message(
            await t(_gid(self.player), "previous" if ok else "no_previous"), ephemeral=True
        )

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary)
    async def pause(self, interaction, button):
        self.player.controller = interaction.user.display_name
        ok = self.player.pause()
        await self.player._announce()  # refresh embed to show who paused
        await interaction.response.send_message(
            await t(_gid(self.player), "toggled" if ok else "nothing_playing"), ephemeral=True
        )

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction, button):
        self.player.controller = interaction.user.display_name
        ok = self.player.skip()
        await interaction.response.send_message(
            await t(_gid(self.player), "skipped" if ok else "nothing_playing"), ephemeral=True
        )

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop(self, interaction, button):
        await self.player.stop()
        await interaction.response.send_message(
            await t(_gid(self.player), "stopped"), ephemeral=True
        )
