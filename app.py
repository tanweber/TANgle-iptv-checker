#!/usr/bin/env python3
import os
import re
import time
import hashlib
import secrets
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Response, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import database as db
import checker_core as checker
import epg as epg_module

sessions = {}
scheduler_running = False
scheduler_thread = None
check_in_progress = False
last_check_time = 0.0
last_epg_update_time = 0.0
check_progress = {"current": 0, "total": 0, "stage": ""}


def scheduler_loop():
    global scheduler_running, last_check_time, last_epg_update_time
    last_epg_download = 0
    while scheduler_running:
        interval = int(db.get_setting("check_interval", "3600"))
        now = time.time()
        wait = max(0, interval - (now - last_check_time))
        time.sleep(wait)
        if not scheduler_running:
            break
        run_check_background()
        epg_interval = int(db.get_setting("epg_update_interval", "86400"))
        if now - last_epg_download > epg_interval:
            try:
                epg_module.download_epg_sources()
                last_epg_download = time.time()
                last_epg_update_time = time.time()
            except Exception as e:
                print(f"[scheduler] EPG download failed: {e}")


def run_check_background():
    global check_in_progress, last_check_time, check_progress
    if check_in_progress:
        print("[scheduler] Check already in progress, skipping")
        return
    check_in_progress = True
    check_progress = {"current": 0, "total": 0, "stage": "Starting check"}
    try:
        print("[scheduler] Starting check...")

        def update_progress(current, total, stage):
            global check_progress
            check_progress = {"current": current, "total": total, "stage": stage}

        checker.run_check(progress_callback=update_progress)
        last_check_time = time.time()
        check_progress = {"current": 1, "total": 1, "stage": "Generating playlist"}
        generate_playlist_file()
        check_progress = {"current": 1, "total": 1, "stage": "Updating TV Guide"}
        try:
            global epg_channel_count
            epg_channel_count = epg_module.update_epg() or 0
        except Exception as e:
            print(f"[scheduler] EPG update failed: {e}")
    except Exception as e:
        print(f"[scheduler] Check failed: {e}")
    finally:
        check_progress = {"current": 0, "total": 0, "stage": ""}
        check_in_progress = False


def start_scheduler():
    global scheduler_running, scheduler_thread
    if scheduler_running:
        return
    scheduler_running = True
    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler_thread.start()


def stop_scheduler():
    global scheduler_running
    scheduler_running = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="TANgle - IPTV Checker", lifespan=lifespan)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class SourceCreate(BaseModel):
    name: str
    url: str
    enabled: bool = True


class SourceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    enabled: bool | None = None


class SettingsUpdate(BaseModel):
    check_interval: int | None = None
    check_timeout: int | None = None
    check_parallel: int | None = None
    auth_login: str | None = None
    auth_password: str | None = None
    playlist_all: bool | None = None
    playlist_fast: bool | None = None
    playlist_medium: bool | None = None
    playlist_slow: bool | None = None
    epg_update_interval: int | None = None
    availability_period_days: int | None = None
    min_availability: int | None = None


class LoginRequest(BaseModel):
    login: str
    password: str


class EPGSourceCreate(BaseModel):
    name: str
    url: str
    enabled: bool = True


class EPGSourceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    enabled: bool | None = None


def get_session_token(request: Request):
    token = request.cookies.get("session")
    if token and token in sessions:
        return token
    return None


def require_auth(request: Request):
    token = get_session_token(request)
    if not token:
        raise HTTPException(401, detail="Unauthorized")
    return token


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not get_session_token(request):
        return RedirectResponse(url="/login")
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    html_path = os.path.join(os.path.dirname(__file__), "static", "login.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/login")
async def login(req: LoginRequest, response: Response):
    login_val = db.get_setting("auth_login", "admin")
    password_val = db.get_setting("auth_password", "admin")
    if req.login == login_val and req.password == password_val:
        token = secrets.token_hex(32)
        sessions[token] = req.login
        response.set_cookie("session", token, httponly=True, max_age=86400)
        return {"ok": True}
    raise HTTPException(401, detail="Invalid credentials")


@app.post("/api/logout")
async def logout(request: Request, response: Response):
    token = get_session_token(request)
    if token:
        sessions.pop(token, None)
    response.delete_cookie("session")
    return {"ok": True}


@app.get("/api/check_login")
async def check_login(request: Request):
    return {"logged_in": get_session_token(request) is not None}


@app.get("/api/stats")
async def get_stats():
    return db.get_stats()


@app.get("/api/settings")
async def get_settings():
    return {
        "check_interval": int(db.get_setting("check_interval", "3600")),
        "check_timeout": int(db.get_setting("check_timeout", "10")),
        "check_parallel": int(db.get_setting("check_parallel", "50")),
        "auth_login": db.get_setting("auth_login", "admin"),
        "auth_password": db.get_setting("auth_password", "admin"),
        "playlist_all": db.get_setting("playlist_all", "1") == "1",
        "playlist_fast": db.get_setting("playlist_fast", "1") == "1",
        "playlist_medium": db.get_setting("playlist_medium", "1") == "1",
        "playlist_slow": db.get_setting("playlist_slow", "1") == "1",
        "epg_update_interval": int(db.get_setting("epg_update_interval", "86400")),
        "availability_period_days": int(db.get_setting("availability_period_days", "7")),
        "min_availability": int(db.get_setting("min_availability", "0")),
    }


@app.put("/api/settings")
async def update_settings(s: SettingsUpdate):
    if s.check_interval is not None:
        db.set_setting("check_interval", s.check_interval)
    if s.check_timeout is not None:
        db.set_setting("check_timeout", s.check_timeout)
    if s.check_parallel is not None:
        db.set_setting("check_parallel", s.check_parallel)
    if s.auth_login is not None:
        db.set_setting("auth_login", s.auth_login)
    if s.auth_password is not None:
        db.set_setting("auth_password", s.auth_password)
    if s.playlist_all is not None:
        db.set_setting("playlist_all", "1" if s.playlist_all else "0")
    if s.playlist_fast is not None:
        db.set_setting("playlist_fast", "1" if s.playlist_fast else "0")
    if s.playlist_medium is not None:
        db.set_setting("playlist_medium", "1" if s.playlist_medium else "0")
    if s.playlist_slow is not None:
        db.set_setting("playlist_slow", "1" if s.playlist_slow else "0")
    if s.epg_update_interval is not None:
        db.set_setting("epg_update_interval", s.epg_update_interval)
    if s.availability_period_days is not None:
        db.set_setting("availability_period_days", s.availability_period_days)
    if s.min_availability is not None:
        db.set_setting("min_availability", s.min_availability)
    return {"ok": True}


@app.get("/api/sources")
async def list_sources():
    return db.get_sources()


@app.post("/api/sources")
async def create_source(s: SourceCreate):
    try:
        text = checker.fetch_source(s.url)
        if not text or len(text.strip()) == 0:
            raise HTTPException(400, detail="Файл пустой")
        if not text.strip().startswith("#EXTM3U") and "#EXTINF:" not in text:
            raise HTTPException(400, detail="Файл не является M3U/M3U8 плейлистом (не найдены теги #EXTM3U или #EXTINF)")
        channels = checker.parse_m3u(text)
        if not channels:
            raise HTTPException(400, detail="Плейлист не содержит каналов")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, detail=f"Не удалось загрузить плейлист: {str(e)[:200]}")
    sid = db.add_source(s.name, s.url, s.enabled)
    db.update_source_status(sid, True, len(channels))
    return {"id": sid, "ok": True, "channels_found": len(channels)}


@app.put("/api/sources/{source_id}")
async def update_source(source_id: int, s: SourceUpdate):
    db.update_source(source_id, s.name, s.url, s.enabled)
    return {"ok": True}


@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: int):
    db.delete_source(source_id)
    return {"ok": True}


@app.get("/api/epg-sources")
async def list_epg_sources():
    return db.get_epg_sources()


@app.post("/api/epg-sources")
async def create_epg_source(s: EPGSourceCreate):
    alive, ms, error = epg_module.check_epg_source(s.url, timeout=10)
    if not alive:
        raise HTTPException(400, detail=f"Источник недоступен: {error or 'HTTP error'}")
    try:
        raw = epg_module.download_epg_source(s.url)
        if raw is None:
            raise HTTPException(400, detail="Не удалось скачать файл")
        channel_map, programmes = epg_module.parse_xmltv(raw)
        if not channel_map:
            raise HTTPException(400, detail="Файл не содержит XMLTV данные (нет каналов). Поддерживаются: .xml, .xml.gz, .zip с XML")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, detail=f"Ошибка парсинга: {str(e)[:200]}")
    sid = db.add_epg_source(s.name, s.url, s.enabled)
    return {"id": sid, "ok": True, "channels_found": len(channel_map)}


@app.put("/api/epg-sources/{epg_id}")
async def update_epg_source(epg_id: int, s: EPGSourceUpdate):
    db.update_epg_source(epg_id, s.name, s.url, s.enabled)
    return {"ok": True}


@app.delete("/api/epg-sources/{epg_id}")
async def delete_epg_source(epg_id: int):
    db.delete_epg_source(epg_id)
    return {"ok": True}


@app.post("/api/epg/download")
async def download_epg():
    try:
        epg_module.download_epg_sources()
        return {"ok": True, "message": "EPG sources downloaded"}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.get("/api/epg")
async def get_epg(request: Request):
    client_ip = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
    user_agent = request.headers.get("user-agent", "unknown")
    db.log_access("epg", client_ip, user_agent)
    if not os.path.exists(epg_module.EPG_PATH):
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><tv/>',
                        media_type="application/xml")
    with open(epg_module.EPG_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content=content, media_type="application/xml")


@app.get("/api/channels")
async def list_channels(source_id: int | None = None, alive: bool | None = None):
    return db.get_channels(source_id=source_id, alive_only=(alive is True))


@app.put("/api/channels/{channel_id}/toggle")
async def toggle_channel(channel_id: int, enabled: bool):
    db.toggle_channel(channel_id, enabled)
    return {"ok": True}


@app.put("/api/channels/{channel_id}/group")
async def update_channel_group(channel_id: int, group_title: str):
    db.update_channel_group(channel_id, group_title)
    return {"ok": True}


@app.get("/api/debug/headers")
async def debug_headers(request: Request):
    headers = dict(request.headers)
    return {
        "client": str(request.client),
        "headers": headers,
    }


@app.get("/api/access/stats")
async def access_stats(date_from: str | None = None, date_to: str | None = None):
    return db.get_access_stats(date_from=date_from, date_to=date_to)


@app.get("/api/access/log")
async def access_log(endpoint: str | None = None, limit: int = 10, offset: int = 0, date_from: str | None = None, date_to: str | None = None):
    return db.get_access_log(endpoint=endpoint, limit=limit, offset=offset, date_from=date_from, date_to=date_to)


@app.delete("/api/access/log")
async def delete_access_log(date_from: str | None = None, date_to: str | None = None):
    deleted = db.delete_access_log(date_from=date_from, date_to=date_to)
    return {"ok": True, "deleted": deleted}


@app.post("/api/check")
async def trigger_check():
    global check_in_progress, last_check_time
    if check_in_progress:
        raise HTTPException(409, detail="Check already in progress")
    threading.Thread(target=run_check_background, daemon=True).start()
    return {"ok": True, "message": "Check started"}


@app.get("/api/check/status")
async def check_status():
    return {
        "in_progress": check_in_progress,
        "last_check": last_check_time,
        "next_check": last_check_time + int(db.get_setting("check_interval", "3600")) if last_check_time else 0,
        "progress": check_progress,
    }


EPG_SERVE_URL = os.environ.get("EPG_SERVE_URL", "http://localhost:9239/epg.xml")
PLAYLIST_SERVE_URL = os.environ.get("PLAYLIST_SERVE_URL", "http://localhost:9239/rus_fixed.m3u")
PLAYLIST_PATH = os.environ.get("PLAYLIST_PATH", "/playlist/rus_fixed.m3u")
playlist_channel_count = 0
epg_channel_count = 0


def normalize_channel_name(name):
    if not name:
        return ""
    name = name.lower().strip()
    name = re.sub(r'\(.*?\d+[рp].*?\)', '', name)
    name = re.sub(r'\[.*?\d+[рp].*?\]', '', name)
    name = re.sub(r'\b(hd|fhd|uhd|4k|sd)\b', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def generate_playlist_file():
    global playlist_channel_count
    pl_fast = db.get_setting("playlist_fast", "1") == "1"
    pl_medium = db.get_setting("playlist_medium", "1") == "1"
    pl_slow = db.get_setting("playlist_slow", "1") == "1"
    min_avail = int(db.get_setting("min_availability", "0"))

    channels = db.get_channels()

    alive_channels = []
    for ch in channels:
        if not ch.get("enabled", 1):
            continue
        if not ch["is_alive"] or ch["last_check"] is None:
            continue
        ms = ch.get("response_time_ms")
        if ms is None:
            continue
        total = ch.get("total_checks", 0)
        alive_cnt = ch.get("alive_checks", 0)
        if total > 0:
            avail_pct = alive_cnt / total * 100
            if avail_pct < min_avail:
                continue
        if ms < 1000 and pl_fast:
            alive_channels.append(ch)
        elif ms < 3000 and pl_medium:
            alive_channels.append(ch)
        elif ms >= 3000 and pl_slow:
            alive_channels.append(ch)

    by_name = {}
    for ch in alive_channels:
        if not ch.get("enabled", 1):
            continue
        key = normalize_channel_name(ch["name"])
        ms = ch.get("response_time_ms") or 99999
        if key not in by_name or ms < (by_name[key].get("response_time_ms") or 99999):
            by_name[key] = ch

    unique = sorted(by_name.values(), key=lambda c: c["name"].lower())

    lines = [f'#EXTM3U x-tvg-url="{EPG_SERVE_URL}" url-tvg="{PLAYLIST_SERVE_URL}"\n']
    for ch in unique:
        if ch["inf_line"]:
            inf = re.sub(r'group-title="[^"]*"', f'group-title="{ch["group_title"]}"', ch["inf_line"])
            if 'group-title' not in inf:
                inf = inf.replace("#EXTINF:", f'#EXTINF: group-title="{ch["group_title"]}" ', 1)
        else:
            inf = f'#EXTINF:-1 group-title="{ch["group_title"]}",{ch["name"]}'
        inf = re.sub(r',[^,]*$', f',{ch["name"]}', inf)
        lines.append(f'{inf}\n{ch["url"]}\n')

    content = "".join(lines)
    os.makedirs(os.path.dirname(PLAYLIST_PATH), exist_ok=True)
    with open(PLAYLIST_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    playlist_channel_count = len(unique)
    print(f"[scheduler] Playlist saved: {playlist_channel_count} channels -> {PLAYLIST_PATH}")
    return content


@app.get("/api/playlist/info")
async def playlist_info(request: Request):
    token = get_session_token(request)
    if not token:
        raise HTTPException(401, detail="Unauthorized")
    return {
        "url": PLAYLIST_PATH,
        "channel_count": playlist_channel_count,
        "epg_channel_count": epg_channel_count,
        "last_check": last_check_time,
        "last_epg_update": last_epg_update_time,
    }


@app.post("/api/playlist/generate")
async def regenerate_playlist(request: Request):
    token = get_session_token(request)
    if not token:
        raise HTTPException(401, detail="Unauthorized")
    generate_playlist_file()
    return {
        "ok": True,
        "channel_count": playlist_channel_count,
    }


@app.get("/api/playlist")
async def generate_playlist(request: Request):
    token = get_session_token(request)
    if not token:
        raise HTTPException(401, detail="Unauthorized")

    content = generate_playlist_file()
    client_ip = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
    user_agent = request.headers.get("user-agent", "unknown")
    db.log_access("playlist", client_ip, user_agent)
    return Response(content=content, media_type="audio/x-mpegurl",
                    headers={"Content-Disposition": "attachment; filename=playlist.m3u"})


@app.get("/p/rus_fixed.m3u")
@app.get("/rus_fixed.m3u")
async def serve_playlist_public(request: Request):
    client_ip = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
    user_agent = request.headers.get("user-agent", "unknown")
    db.log_access("playlist", client_ip, user_agent)
    if not os.path.exists(PLAYLIST_PATH):
        return Response(content="", status_code=404)
    with open(PLAYLIST_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content=content, media_type="audio/x-mpegurl")


@app.get("/epg.xml")
async def serve_epg_public(request: Request):
    client_ip = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
    user_agent = request.headers.get("user-agent", "unknown")
    db.log_access("epg", client_ip, user_agent)
    if not os.path.exists(epg_module.EPG_PATH):
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><tv/>',
                        media_type="application/xml")
    with open(epg_module.EPG_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content=content, media_type="application/xml")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9239)
