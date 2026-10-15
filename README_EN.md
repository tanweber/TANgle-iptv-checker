# TANgle - IPTV Checker

[Русская версия](README.md)

Smart web interface for IPTV playlist management.
TANgle automatically builds a single M3U playlist from multiple sources, checks channel availability and response time, removes duplicates, and generates a week-ahead TV Guide (EPG) for the channels that made it into the playlist.

Developed with [MiMo Code](https://github.com/XiaoMi/MiMo) — AI coding assistant by Xiaomi.

## Features

- **IPTV Channel Checking** — parallel availability testing of M3U/M3U8 playlists with response time measurement.
- **Unified Playlist** — merge multiple playlists into one with rules by speed (fast / medium / slow) and minimum availability.
- **Channel Management** — enable/disable individual channels, edit groups. Channels that don't pass the playlist rules (unavailable, unchecked, too slow, low availability) are switched off automatically, with a tooltip explaining why.
- **Automatic Deduplication** — the fastest copy of a duplicated channel is kept.
- **TV Guide (EPG)** — downloads and merges XMLTV from multiple sources. Each channel's guide comes from the single source with the best coverage, channel ids match the playlist's `tvg-id`, and the output is valid XML. A compressed `/epg.xml.gz` is also available.
- **Users and personal links** — each user gets their own playlist and TV guide links. Copy them in one click, disable temporarily or delete; see the last connection time, IP address and device.
- **Security** — the whole API requires sign-in, the password is stored as a PBKDF2 hash, login and password can be changed in the UI.
- **Clean, responsive UI** — works on desktop, tablets and smartphones.
- **7 Themes** — Auto, Warm, Warm dark, Light, Dark, Nord, Forest.
- **Multilingual** — instant EN/RU switching.
- **Automation** — built-in scheduler for channel checks and EPG updates.
- **Easy Deployment** — Docker, all settings in a single `.env` file.

## Screenshots
<img width="1228" height="914" alt="s1" src="https://github.com/user-attachments/assets/4a0d0bf2-2e30-4b7c-93ca-bc893e75cab2" />
<img width="1217" height="569" alt="s2" src="https://github.com/user-attachments/assets/bbe46017-ed14-4971-a83a-d5b33bd933cc" />
<img width="1211" height="653" alt="s3" src="https://github.com/user-attachments/assets/afbd1dc9-ab97-48ce-b190-e528a14edebc" />

## Installation

Requires Docker and Docker Compose.

```bash
git clone https://github.com/tanweber/TANgle-iptv-checker.git
cd TANgle-iptv-checker
cp .env.example .env      # then edit .env
docker compose up -d --build
```

Open `http://<server-address>:9239` and sign in with the login and password from `.env` (default `admin` / `admin`). **Change the password right away**: Settings → Sign-in.

Next:
1. **Sources** → add M3U playlists (EPG sources are preconfigured).
2. **Channels** → "Check now". The first check and TV guide build take a few minutes.
3. **Settings** → choose the playlist rules.
4. **Users** → "Add user", enter any name and copy the playlist link. Paste it into the player — the TV guide is picked up automatically from the playlist header (or set it manually with the "TV guide" button).

### Updating

```bash
git pull
docker compose up -d --build
```

The database (`data/`), playlist and EPG (`playlist/`) live on the host and are kept across updates.

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `TANGLE_PORT` | `9239` | Host port for the web UI |
| `PUBLIC_URL` | `http://localhost:9239` | Public URL of the service, no trailing `/`. User links are built from it, so players must be able to reach it (e.g. `https://iptv.example.com`) |
| `EPG_DAYS` | `7` | How many days ahead the TV guide covers |
| `ADMIN_LOGIN` | `admin` | Admin login — first start only |
| `ADMIN_PASSWORD` | `admin` | Admin password — first start only |

`ADMIN_LOGIN` and `ADMIN_PASSWORD` apply only to a new (empty) database. After that, change them in the UI.

Everything else (check and EPG update intervals, timeouts, worker count, playlist rules) is configured in the UI under "Settings".

### Reverse proxy

For HTTPS, put a reverse proxy (nginx, Caddy, Traefik) in front of TANgle and set the external address in `PUBLIC_URL`. An nginx example is in `nginx.conf`. The proxy should pass the `X-Real-IP` header so the user list shows real IPs. Better turn off gzip on the proxy: some players (Televizo) can't read it.

## Project Structure

```
tangle/
├── app.py              # FastAPI server, auth, scheduler, playlist builder
├── database.py         # SQLite operations
├── checker_core.py     # Channel checker
├── epg.py              # TV guide (EPG) builder
├── static/
│   ├── index.html      # Main UI
│   ├── login.html      # Login page
│   ├── theme.css       # Shared styles and themes
│   └── translations.js # EN/RU translations
├── .env.example        # Settings template
├── Dockerfile
├── docker-compose.yml
└── nginx.conf          # Reverse proxy example
```

## API

Personal user links (no sign-in, `{token}` is the user's unique code):

| Method | Path | Description |
|--------|------|-------------|
| GET, HEAD | `/u/{token}/playlist.m3u` | Playlist |
| GET, HEAD | `/u/{token}/epg.xml` | TV guide (XMLTV) |
| GET, HEAD | `/u/{token}/epg.xml.gz` | TV guide, gzipped |

A disabled, deleted or unknown link returns 404.

Sign-in required (session cookie):

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/login` | Sign in |
| POST | `/api/auth/password` | Change login and password |
| GET | `/api/stats` | Channel statistics |
| GET | `/api/channels` | Channel list (with the reason a channel is excluded from the playlist) |
| PUT | `/api/channels/{id}/toggle` | Toggle channel |
| PUT | `/api/channels/{id}/group` | Change group |
| GET, PUT | `/api/settings` | Settings |
| GET | `/api/sources` | Playlist sources |
| GET | `/api/epg-sources` | EPG sources |
| POST | `/api/check` | Trigger check |
| GET, POST | `/api/users` | Users and their links / add a user |
| PUT, DELETE | `/api/users/{id}` | Rename, disable / delete a user |

## What's new in v2.2

- **Personal links instead of shared ones.** "Users" tab: each user gets their own playlist and TV guide links with a random code. Copy, temporarily disable or delete them — a disabled link stops working immediately.
- Each user shows the date and time of the last connection, IP address and device.
- The shared `/rus_fixed.m3u` and `/epg.xml` links are disabled. **When upgrading from v2.1**, create users and replace the links in your players.
- The "Connections" statistics tab has been removed.
- Broken programmes whose end is before their start are dropped from the TV guide.

## What's new in v2.1

- **Fixed the TV guide** that players failed to read:
  - the playlist's `url-tvg` header pointed at the playlist itself instead of the EPG;
  - programmes referenced channels that were not declared in the file;
  - guides from different sources and regional channel copies ("+2", "+4") were mixed and overlapped;
  - EPG channel ids didn't match the playlist's `tvg-id`, so most channels showed no guide.
- The TV guide now covers **7 days** (configurable via `EPG_DAYS`). It is built by streaming and needs far less memory.
- New compressed `/epg.xml.gz`. On `/epg.xml`, players that can't handle gzip (Televizo, okhttp) get the plain file — also behind a reverse proxy (nginx, Nginx Proxy Manager) that used to compress the response itself and broke guide updates in Televizo.
- The playlist and EPG are served with `Last-Modified` and `Content-Length` and support `HEAD`, so players can check for updates.
- **Security:** the whole API now requires sign-in (previously settings, including the password, were readable without it), the password is stored hashed, and changing it requires the current password.
- **New design** in a clean style, 7 themes (Auto, Warm, Warm dark, Light, Dark, Nord, Forest), a redesigned login page, one-click copy of playlist and EPG URLs.
- **Automatic switch-off** of channels that don't pass the playlist rules, with a tooltip explaining why. Speed rules are now strict: each checkbox covers only its own range.
- All personal settings moved to `.env` (template: `.env.example`).
- Fixed: sorting by availability, channel counters after restart, EPG update scheduling, special characters in group names; Docker image dependencies are now pinned via `requirements.txt`.

## Requirements

- Docker and Docker Compose
- 512 MB RAM
- 2 GB disk space (the EPG source cache can take 1–1.5 GB)

## License

MIT
