# Discord Music Bot

A Discord music bot: yt-dlp resolves audio, FFmpeg streams it into voice.
Plays YouTube plus any other [yt-dlp-supported service](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)
(SoundCloud, Bandcamp, Twitch VODs, direct links, …) — paste a URL, or search
YouTube by name. Slash + prefix commands, queue with jump controls,
YouTube-radio autoplay, saved playlists, per-server settings, DJ-role
permissions, auto-leave when alone, and queue resume on restart (state in
MongoDB).

> mpv can't join Discord voice, so discord.py + FFmpeg does the piping — same yt-dlp source.

## Requirements
- Python 3.10+
- **FFmpeg** on PATH (`ffmpeg -version` to check)
- A MongoDB instance (local, Docker `docker run -d -p 27017:27017 mongo`, or Atlas)
- **Deno** on PATH — yt-dlp uses it to solve YouTube's challenge (`remote_components`)

## Setup
1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in the values.
3. Create a bot at https://discord.com/developers:
   - enable the **Message Content Intent**
   - invite with **Connect**, **Speak**, **Send Messages**, and `applications.commands` scope
4. `python main.py`

Set `GUILD_ID` in `.env` for instant slash-command sync while developing
(global sync can take up to ~1h to appear).

### Docker
`docker compose up -d` — builds the bot and starts MongoDB alongside it
(only `.env` needed; `MONGODB_URI` is set for you).

## Configuration (`.env`)
| Key | Purpose |
|-----|---------|
| `DISCORD_TOKEN` | Bot token (required) |
| `MONGODB_URI` | MongoDB connection string |
| `MONGODB_DB_NAME` | Database name |
| `PREFIX` | Default prefix for text commands (per-server overridable) |
| `LANGUAGE` | Default language code (`en`, `vi`; per-server overridable) |
| `GUILD_ID` | Optional — server ID for instant command sync |
| `DASHBOARD` | `true` to serve a read-only web dashboard (now playing + queues) |
| `DASHBOARD_PORT` | Dashboard port (default `8080`) |

## Commands
Every command works as both `/slash` and `!prefix`.

| Command | Description |
|---------|-------------|
| `play <url or search>` | Play / queue a track or playlist (up to 25) from any supported site |
| `playtop <url or search>` | Same, but adds to the **front** of the queue |
| `search <query>` | Search YouTube; pick from the top 5 (with channel + duration) to queue |
| `skip` | Skip the current track |
| `previous` | Play the previous track |
| `pause` | Pause / resume |
| `queue` | Show the queue with a jump-to dropdown |
| `remove <position>` | Remove a queued track by its position |
| `shuffle` | Shuffle the upcoming queue |
| `loop` | Cycle loop mode: off → one track → whole queue |
| `stop` | Clear the queue and disconnect |
| `autoplay` | Toggle YouTube-radio autoplay when the queue empties (YouTube tracks only) |
| `playlist-save <name>` | Save the current queue under a name |
| `playlist-load <name>` | Load a saved playlist |
| `playlists` | List saved playlists |
| `leavetime <seconds>` | Seconds alone in voice before auto-leaving + clearing the queue (`0` = never) |
| `dj-add <role>` | **Admin** — let a role control any track |
| `dj-remove <role>` | **Admin** — remove a DJ role |
| `dj-list` | Show this server's DJ roles |
| `prefix <new>` | Set this server's text-command prefix |
| `language <code>` | Set this server's language |
| `help` | List all commands |

### Playback permissions
Skip / previous / pause / stop / jump / loop / shuffle / remove run immediately for:
- the person who **requested the now-playing track**,
- anyone with a **DJ role** (`dj-add`, per server), or
- server **admins** (Administrator / Manage Server).

Everyone else **votes**: each listener in the voice channel who triggers the
action casts one vote, and it runs once a **majority** of current listeners
agree (votes reset when the track changes). `autoplay` stays DJ/admin-only.

Anyone can still `play`, view the `queue`, and manage playlists.

The now-playing message shows track info, who requested it, who last used a
control, queue length, and ⏮️ ⏯️ ⏭️ ⏹️ buttons plus the jump dropdown.

## Languages
Strings live in `language.json`, keyed by language code. Add a language by
adding a top-level block with the same keys — no code change needed.

## License
MIT — see [LICENSE](LICENSE).
