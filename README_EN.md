# TANgle - IPTV Checker

Smart web interface for IPTV playlist management.
TANgle automatically builds a single M3U playlist from multiple sources, checks channel availability and response time, removes duplicates, and generates an up-to-date TV Guide (EPG) for active channels only.

Developed with [MiMo Code](https://github.com/XiaoMi/MiMo) — AI coding assistant by Xiaomi.

[Русская версия](README.md)

## Features

- **IPTV Channel Checking** — parallel availability testing from M3U/M3U8 playlists with response time measurement.
- **Unified Playlist** — merge multiple playlists into one with flexible filtering by speed and availability.
- **Channel Management** — enable/disable individual channels with checkboxes, edit channel groups. State persists across restarts.
- **Automatic Deduplication** — duplicates are removed before publishing (fastest channel is kept).
- **TV Guide (EPG)** — automatic download and merge of XMLTV files from multiple sources, filtered to playlist channels only.
- **Connection Statistics** — tracking IPs, devices, access history with period filtering and deletion.
- **Responsive Web UI** — works on desktop, tablets, and smartphones.
- **7 Themes** — Dark, Light, Monokai, Dracula, Nord, Solarized, GitHub.
- **Multilingual** — instant EN/RU language switching.
- **Automation** — built-in scheduler for periodic playlist checks and EPG updates.
- **Easy Deployment** — Docker image, one command to run.

## Screenshots
<img width="1228" height="914" alt="s1" src="https://github.com/user-attachments/assets/4a0d0bf2-2e30-4b7c-93ca-bc893e75cab2" />
<img width="1217" height="569" alt="s2" src="https://github.com/user-attachments/assets/bbe46017-ed14-4971-a83a-d5b33bd933cc" />
<img width="1211" height="653" alt="s3" src="https://github.com/user-attachments/assets/afbd1dc9-ab97-48ce-b190-e528a14edebc" />

## Quick Start

```bash
git clone https://github.com/tanweber/TANgle-iptv-checker.git
cd TANgle-iptv-checker
docker compose up -d
```

Open in browser: `http://localhost:9239`

Default credentials: `admin` / `admin`

## Project Structure

```
tangle/
├── app.py              # FastAPI server
├── database.py         # SQLite operations
├── checker_core.py     # Channel checker
├── epg.py              # EPG processor
├── static/
│   ├── index.html      # Main UI
│   ├── login.html      # Login page
│   └── translations.js # EN/RU translations
├── Dockerfile
├── docker-compose.yml
└── nginx.conf
```

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Web UI |
| GET | `/rus_fixed.m3u` | Download playlist |
| GET | `/epg.xml` | Download TV Guide |
| POST | `/api/login` | Login |
| GET | `/api/stats` | Channel statistics |
| GET | `/api/channels` | Channel list |
| PUT | `/api/channels/{id}/toggle` | Toggle channel |
| PUT | `/api/channels/{id}/group` | Change group |
| GET | `/api/sources` | Playlist sources |
| GET | `/api/epg-sources` | EPG sources |
| POST | `/api/check` | Trigger check |
| GET | `/api/access/log` | Access log |
| DELETE | `/api/access/log` | Delete log by period |

## Settings

- Channel check interval
- EPG update interval
- Playlist rules (by speed and availability)
- Channel availability calculation period
- Add playlist sources
- Add EPG sources

## Requirements

- Docker and Docker Compose
- 512MB RAM
- 1GB disk space

## License

MIT
