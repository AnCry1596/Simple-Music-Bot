# Discord Music Bot

A Discord music bot: yt-dlp resolves audio, FFmpeg streams it into voice.
Slash + prefix commands, queue with jump controls, YouTube-radio autoplay,
saved playlists, per-server settings, and queue resume on restart (state in MongoDB).

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
4. `python bot.py`

Set `GUILD_ID` in `.env` for instant slash-command sync while developing
(global sync can take up to ~1h to appear).

## Configuration (`.env`)
| Key | Purpose |
|-----|---------|
| `DISCORD_TOKEN` | Bot token (required) |
| `MONGODB_URI` | MongoDB connection string |
| `MONGODB_DB_NAME` | Database name |
| `PREFIX` | Default prefix for text commands (per-server overridable) |
| `LANGUAGE` | Default language code (`en`, `vi`; per-server overridable) |
| `GUILD_ID` | Optional — server ID for instant command sync |

## Commands
Every command works as both `/slash` and `!prefix`.

| Command | Description |
|---------|-------------|
| `play <url or search>` | Play / queue a track or playlist (up to 25) |
| `skip` | Skip the current track |
| `previous` | Play the previous track |
| `pause` | Pause / resume |
| `queue` | Show the queue with a jump-to dropdown |
| `stop` | Clear the queue and disconnect |
| `autoplay` | Toggle YouTube-radio autoplay when the queue empties |
| `playlist-save <name>` | Save the current queue under a name |
| `playlist-load <name>` | Load a saved playlist |
| `playlists` | List saved playlists |
| `prefix <new>` | Set this server's text-command prefix |
| `language <code>` | Set this server's language |

The now-playing message shows track info, who requested it, who last used a
control, queue length, and ⏮️ ⏯️ ⏭️ ⏹️ buttons plus the jump dropdown.

## Languages
Strings live in `language.json`, keyed by language code. Add a language by
adding a top-level block with the same keys — no code change needed.

## License
MIT — see [LICENSE](LICENSE).
