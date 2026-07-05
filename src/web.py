"""Read-only web dashboard: now playing + queue per guild. Enable with DASHBOARD=true."""
import html

from aiohttp import web  # already installed: discord.py depends on aiohttp

_PAGE = """<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="5">
<title>Music Bot</title>
<style>
body{font-family:sans-serif;max-width:640px;margin:2em auto;padding:0 1em;background:#1e1f22;color:#dbdee1}
h2{color:#5865f2;margin-bottom:.2em}li{margin:.2em 0}i{color:#80848e}
</style>
<h1>🎵 Music Bot</h1>
%s"""


async def start_dashboard(bot, players, port):
    async def index(request):
        sections = []
        for gid, p in players.items():
            guild = bot.get_guild(gid)
            name = html.escape(guild.name if guild else str(gid))
            now = f"▶️ <b>{html.escape(p.current[0])}</b>" if p.current else "<i>nothing playing</i>"
            q = "".join(f"<li>{html.escape(row[0])}</li>" for row in p.queue) or "<li><i>empty</i></li>"
            sections.append(f"<h2>{name}</h2><p>{now}</p><ol>{q}</ol>")
        body = "".join(sections) or "<p><i>No active players.</i></p>"
        return web.Response(text=_PAGE % body, content_type="text/html")

    app = web.Application()
    app.router.add_get("/", index)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    print(f"Dashboard on http://localhost:{port}")
