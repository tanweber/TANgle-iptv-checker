# TANgle - IPTV Checker

Веб-интерфейс для умного управления IPTV-плейлистами.
TANgle автоматически собирает единый M3U-плейлист из нескольких источников, проверяет каналы на доступность и скорость отклика, удаляет дубли и формирует актуальную ТВ-программу (EPG) только для работающих каналов.

Smart web interface for IPTV playlist management.
TANgle automatically builds a single M3U playlist from multiple sources, checks channel availability and response time, removes duplicates, and generates an up-to-date TV Guide (EPG) for active channels only.

Разработано с использованием [MiMo Code](https://github.com/XiaoMi/MiMo) — AI-помощник для программистов от Xiaomi.
Developed with [MiMo Code](https://github.com/XiaoMi/MiMo) — AI coding assistant by Xiaomi.

---

## Возможности / Features

- **Проверка IPTV-каналов** — параллельное тестирование доступности каналов из M3U и M3U8-плейлистов с измерением времени отклика.
  **IPTV Channel Checking** — parallel availability testing from M3U/M3U8 playlists with response time measurement.
- **Формирование единого плейлиста** — объединение нескольких плейлистов в один с возможностью гибкой настройки правил фильтрации по скорости и доступности.
  **Unified Playlist** — merge multiple playlists into one with flexible filtering by speed and availability.
- **Управление каналами** — включение/отключение отдельных каналов чекбоксами, редактирование групп каналов. Состояние сохраняется между перезапусками.
  **Channel Management** — enable/disable individual channels with checkboxes, edit channel groups. State persists across restarts.
- **Автоматическое удаление дублей** — перед публикацией итогового плейлиста все повторяющиеся каналы исключаются (оставляется самый быстрый).
  **Automatic Deduplication** — duplicates are removed before publishing (fastest channel is kept).
- **ТВ-программа (EPG)** — автоматическое скачивание и слияние XMLTV-файлов из разных источников с формированием программы только для каналов плейлиста.
  **TV Guide (EPG)** — automatic download and merge of XMLTV files from multiple sources, filtered to playlist channels only.
- **Статистика подключений** — отслеживание IP-адресов, устройств, истории обращений с фильтрацией по периоду и удалением.
  **Connection Statistics** — tracking IPs, devices, access history with period filtering and deletion.
- **Адаптивный веб-интерфейс** — удобное управление с ПК, планшетов и смартфонов.
  **Responsive Web UI** — works on desktop, tablets, and smartphones.
- **7 тем оформления** — Dark, Light, Monokai, Dracula, Nord, Solarized, GitHub.
  **7 Themes** — Dark, Light, Monokai, Dracula, Nord, Solarized, GitHub.
- **Мультиязычность** — переключение EN/RU в реальном времени.
  **Multilingual** — instant EN/RU language switching.
- **Автоматизация** — встроенный планировщик для регулярной проверки плейлистов и обновления EPG.
  **Automation** — built-in scheduler for periodic playlist checks and EPG updates.
- **Простота развертывания** — готовый Docker-образ для запуска одной командой.
  **Easy Deployment** — Docker image, one command to run.

## Скриншоты / Screenshots
<img width="1228" height="914" alt="s1" src="https://github.com/user-attachments/assets/4a0d0bf2-2e30-4b7c-93ca-bc893e75cab2" />
<img width="1217" height="569" alt="s2" src="https://github.com/user-attachments/assets/bbe46017-ed14-4971-a83a-d5b33bd933cc" />
<img width="1211" height="653" alt="s3" src="https://github.com/user-attachments/assets/afbd1dc9-ab97-48ce-b190-e528a14edebc" />

## Быстрый старт / Quick Start

```bash
git clone https://github.com/tanweber/TANgle-iptv-checker.git
cd TANgle-iptv-checker
docker compose up -d
```

Откройте в браузере: `http://localhost:9239`
Open in browser: `http://localhost:9239`

Логин по умолчанию: `admin` / `admin`
Default credentials: `admin` / `admin`

## Структура проекта / Project Structure

```
tangle/
├── app.py              # FastAPI сервер / FastAPI server
├── database.py         # SQLite операции / SQLite operations
├── checker_core.py     # Проверка каналов / Channel checker
├── epg.py              # Обработка EPG / EPG processor
├── static/
│   ├── index.html      # Основной интерфейс / Main UI
│   ├── login.html      # Страница входа / Login page
│   └── translations.js # Переводы EN/RU / Translations
├── Dockerfile
├── docker-compose.yml
└── nginx.conf
```

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Веб-интерфейс / Web UI |
| GET | `/rus_fixed.m3u` | Скачать плейлист / Download playlist |
| GET | `/epg.xml` | Скачать ТВ-программу / Download TV Guide |
| POST | `/api/login` | Авторизация / Login |
| GET | `/api/stats` | Статистика каналов / Channel stats |
| GET | `/api/channels` | Список каналов / Channel list |
| PUT | `/api/channels/{id}/toggle` | Вкл/выкл канал / Toggle channel |
| PUT | `/api/channels/{id}/group` | Изменить группу / Change group |
| GET | `/api/sources` | Источники плейлистов / Playlist sources |
| GET | `/api/epg-sources` | Источники EPG / EPG sources |
| POST | `/api/check` | Запустить проверку / Trigger check |
| GET | `/api/access/log` | Лог подключений / Access log |
| DELETE | `/api/access/log` | Удалить лог за период / Delete log by period |

## Настройки / Settings

- Интервал проверки каналов / Channel check interval
- Интервал обновления EPG / EPG update interval
- Правила формирования плейлиста (по скорости и доступности) / Playlist rules (by speed and availability)
- Период расчёта доступности каналов / Channel availability calculation period
- Возможность добавить плейлисты / Add playlist sources
- Возможность добавить ТВ-программу (EPG) / Add EPG sources

## Требования / Requirements

- Docker и Docker Compose / Docker and Docker Compose
- 512MB RAM
- 1GB дискового пространства / 1GB disk space

## Лицензия / License

MIT
