"""Who may control playback: the current track's requester, a DJ, a server admin — or a vote."""
import db


async def can_control(member, player):
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    if player and player.requester_id() == member.id:  # requested the now-playing track
        return True
    dj_roles = (await db.get_settings(member.guild.id))["dj_roles"]
    return any(r.id in dj_roles for r in member.roles)


async def resolve_control(member, player, action):
    """Decide whether `action` may run for `member`.

    Returns (proceed: bool, status, have, need):
      status "allowed" — privileged (DJ/admin/requester); have/need are 0.
      status "passed"  — this vote reached the majority; run it.
      status "voted"   — vote registered, not enough yet.
    A member not in the bot's voice channel can't vote (proceed False, "voted", 0, 0).
    """
    if await can_control(member, player):
        return True, "allowed", 0, 0
    if not player or member not in player.listeners():
        return False, "voted", 0, 0  # must be listening to vote
    have, need = player.add_vote(action, member.id)
    if have >= need:
        player.votes.pop(action, None)  # consumed -> next round starts fresh
        return True, "passed", have, need
    return False, "voted", have, need
