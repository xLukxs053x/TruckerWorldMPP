# TruckerWorldMP Discord Bot

The Python bot connects the TruckerWorldMP Discord community to the existing website, launcher, and platform API.
The public `/api/v1` endpoints remain the source of truth; the bot never connects directly to the platform's MongoDB
database and does not use member access tokens.

The complete bot interface is in English. `Europe 1` (`europe-1`) is the configured primary game server. The
Simulation Lab is deliberately excluded from presence, status output, automatic server announcements, and convoy
selection.

## Features

- live Europe 1 status, queue, game version, and player count
- upcoming Europe 1 convoys, news, public TWMP profiles, and VTC search
- latest launcher release with download link, checksum, and release notes
- automatic Europe 1 presence and server status announcements
- automatic news and Europe 1 convoy announcements
- welcome messages, farewell messages, automatic member role, and Discord logs
- account-gated private tickets linked to the user's TWMP Discord connection
- two-way Discord/My Support synchronization and protected PDF transcripts
- website reopen requests for closed tickets within a 20-day window
- Discord warnings, timeouts, timeout removal, and message cleanup
- complete per-guild setup through `/admin`
- SQLite with WAL mode for guild settings, tickets, and Discord warnings

## Requirements

- Python 3.10 or newer
- a Discord application with a bot user
- `Server Members Intent` and `Message Content Intent` enabled in the Discord Developer Portal
- access to `https://truckerworldmp.com/api/v1`

`Message Content Intent` is required so ticket messages can be synchronized and included in the PDF transcript.

## Windows installation

```powershell
cd D:\programmieren\TruckerWorldMPP
.\start.ps1 -Install
```

Later starts only require:

```powershell
.\start.ps1
```

## Ubuntu installation

When the project is stored in `/home/lukas/TruckerWorldMPP`:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip

cd ~/TruckerWorldMPP
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
chmod 600 .env
./.venv/bin/python main.py
```

The included helper can also start the bot:

```bash
cd ~/TruckerWorldMPP
chmod +x start.sh
./start.sh
```

Do not use `/opt/truckerworldmp-bot` unless the project was actually copied there. Virtual environments created on
Windows cannot be reused on Linux; always create `.venv` again on the target machine.

## Discord Developer Portal

Enable `Server Members Intent` and `Message Content Intent` under **Bot → Privileged Gateway Intents**. Under
**Installation → Guild Install**, use the `bot` and `applications.commands` scopes.

The bot needs these permissions:

- View Channels, Send Messages, Embed Links, Attach Files, and Read Message History
- Manage Channels for private tickets
- Manage Messages for `/mod clear`
- Moderate Members for Discord timeouts

The bot can generate the correct installation link with `/admin invite`.

## Initial Discord setup

After installing the bot, a guild administrator should run:

```text
/admin channel section:welcome channel:#welcome
/admin channel section:farewell channel:#farewell
/admin channel section:logs channel:#bot-log
/admin channel section:announcements channel:#announcements
/admin role section:support role:@Support
/admin role section:automatic role:@Member
/admin category category:Support Tickets
/admin ticket-panel channel:#support
/admin show
```

The bot role must be above the automatic member role and above any member roles the bot needs to moderate.
Only Discord users with a linked TWMP account can open a ticket. Closing does not delete the channel: it locks the
requester, uploads a private PDF transcript to My Support, and keeps the channel available to support staff. For 20
days the requester can apply to reopen the same case on the website; after approval, the bot unlocks or recreates
the mapped channel automatically.

## Commands

### `/twmp`

- `/twmp status` — live Europe 1 status and player count
- `/twmp server` — detailed Europe 1 information
- `/twmp convoys` — upcoming Europe 1 convoys
- `/twmp news` — latest platform news
- `/twmp profile` — public profile by TWMP ID
- `/twmp vtc` — VTC lookup
- `/twmp download` — latest launcher release
- `/twmp links` — important platform links
- `/twmp help` — command overview

### `/ticket`

- `/ticket create`
- `/ticket close`
- `/ticket panel` — requires Manage Guild

### `/mod`

- `/mod warn`
- `/mod warnings`
- `/mod timeout`
- `/mod untimeout`
- `/mod clear`

Discord permissions and role hierarchy are checked before every moderation action. Discord warnings are intentionally
separate from platform punishments because the current platform API does not provide a general administrative bot
service login.

### `/admin`

- `/admin show`
- `/admin channel`
- `/admin role`
- `/admin category`
- `/admin reset`
- `/admin ticket-panel`
- `/admin invite`

## Environment variables

The complete secret-free template is available in `.env.example`.

| Variable | Purpose |
| --- | --- |
| `DISCORD_CLIENT_ID` | Public Discord application ID |
| `DISCORD_BOT_TOKEN` | Secret bot token used for the Gateway and Discord API |
| `DISCORD_CLIENT_SECRET` | Not required for normal bot operation |
| `DISCORD_GUILD_ID` | Optional test guild for immediate command synchronization |
| `TWMP_API_URL` | Existing platform API |
| `TWMP_WEB_URL` | Public website used in links and embeds |
| `TWMP_LOGO_URL` | Brand icon used in embed footers |
| `TWMP_PRIMARY_SERVER_SLUG` | Primary server; must remain `europe-1` for this deployment |
| `TWMP_BOT_SERVICE_SECRET` | Shared 32+ character secret; must match the API's `DISCORD_BOT_SERVICE_SECRET` |
| `DISCORD_MEMBER_ROLE_ID` | Discord role assigned to new members; configured as `1507686479541829772` for TWMP |
| `TWMP_ACCOUNT_HELP_IMAGE_URL` | Public English account-linking guide embedded in the account-required DM |
| `BOT_DATABASE_PATH` | Local SQLite database path |
| `COMMAND_SYNC_ON_START` | Synchronize slash commands at startup |
| `ENABLE_MEMBER_INTENT` | Enables member events, welcome messages, and automatic roles |
| `ENABLE_MESSAGE_CONTENT_INTENT` | Enables ticket synchronization and PDF transcript content |
| `STATUS_POLL_INTERVAL_SECONDS` | Europe 1 presence/status interval, minimum 30 seconds |
| `ANNOUNCEMENT_POLL_INTERVAL_SECONDS` | News/convoy polling interval, minimum 60 seconds |
| `REQUEST_TIMEOUT_SECONDS` | Platform HTTP timeout |

The bot authenticates with `DISCORD_BOT_TOKEN`. A Discord client secret is only needed if a separate OAuth2
authorization-code flow is implemented later.

## Tests and quality checks

Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

Linux:

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m pytest
./.venv/bin/python -m ruff check .
```

## Docker

```bash
docker compose up -d --build
docker compose logs -f discord-bot
```

## systemd

The included `deployment/truckerworldmp-bot.service` expects the project at `/opt/truckerworldmp-bot` and runs it as
the `truckerworldmp` system user. If the project remains in `/home/lukas/TruckerWorldMPP`, either update
`WorkingDirectory`, `ExecStart`, and the service user or move the project to `/opt/truckerworldmp-bot` first.

The `.env` file must remain outside version control and should have mode `600` on Linux.
