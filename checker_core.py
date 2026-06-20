#!/usr/bin/env python3
import re
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor
import database as db

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux) IPTV-Checker"}

GROUPS_TRANSLATION = {
    "Animation": "Мультфильмы", "Business": "Бизнес", "Classic": "Классика",
    "Comedy": "Комедия", "Cooking": "Кухня", "Culture": "Культура",
    "Documentary": "Документальное", "Education": "Образование",
    "Entertainment": "Развлекательное", "Family": "Семейное", "General": "Общие",
    "Kids": "Детские", "Lifestyle": "Стиль жизни", "Movies": "Кино",
    "Music": "Музыка", "News": "Новости", "Outdoor": "Активный отдых",
    "Religious": "Религия", "Science": "Наука", "Series": "Сериалы",
    "Shop": "Магазин", "Sports": "Спорт", "Travel": "Путешествия",
    "Weather": "Погода", "Undefined": "Другое", "Unknown": "Другое",
}


def translate_group(group_str):
    if not group_str:
        return "Другое"
    parts = [p.strip() for p in group_str.split(";")]
    translated = [GROUPS_TRANSLATION.get(p, p) for p in parts]
    return translated[0]


def clean_title(title):
    title = re.sub(r'\(.*?\d+[рp].*?\)', '', title)
    title = re.sub(r'\[.*?\d+[рp].*?\]', '', title)
    title = re.sub(r'\b(hd|fhd|uhd|4k|sd)\b', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\(.*?\)', '', title)
    title = re.sub(r'\[.*?\]', '', title)
    return re.sub(r'\s+', ' ', title).strip()


def parse_m3u(text):
    channels = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF:"):
            inf_line = lines[i]
            group_name = "Другое"
            group_match = re.search(r'group-title="([^"]+)"', inf_line)
            if group_match:
                group_name = translate_group(group_match.group(1))
            curr = i + 1
            while curr < len(lines) and lines[curr].startswith("#"):
                if lines[curr].startswith("#EXTGRP:"):
                    group_name = translate_group(lines[curr].replace("#EXTGRP:", "").strip())
                curr += 1
            title_match = re.search(r",([^,]+)$", inf_line)
            raw_title = title_match.group(1).strip() if title_match else "Unknown"
            clean_name = clean_title(raw_title)
            inf_clean = re.sub(r'group-title="[^"]*"', f'group-title="{group_name}"', inf_line)
            if 'group-title' not in inf_clean:
                inf_clean = inf_clean.replace("#EXTINF:", f'#EXTINF: group-title="{group_name}" ', 1)
            if curr < len(lines):
                channels.append({
                    "inf_line": inf_clean,
                    "name": clean_name if clean_name else raw_title,
                    "url": lines[curr],
                    "group_title": group_name,
                })
                i = curr
        i += 1
    return channels


def fetch_source(url):
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=Retry(total=2)))
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=2)))
    r = session.get(url, timeout=15, headers=HEADERS)
    r.raise_for_status()
    return r.text


def check_single_channel(session, url, timeout=10):
    start = time.monotonic()
    try:
        with session.get(url, timeout=timeout, headers=HEADERS, stream=True) as r:
            elapsed = (time.monotonic() - start) * 1000
            alive = r.status_code in (200, 301, 302, 307, 308)
            return alive, round(elapsed, 1) if alive else None
    except Exception:
        return False, None


def batch_update_channels(results):
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    now = time.time()
    try:
        conn.executemany(
            "UPDATE channels SET is_alive=?, response_time_ms=?, last_check=?, total_checks=total_checks+1, alive_checks=alive_checks+? WHERE id=?",
            [(1 if alive else 0, ms, now, 1 if alive else 0, cid) for cid, alive, ms in results],
        )
        conn.commit()
    finally:
        conn.close()


def run_check(progress_callback=None):
    sources = db.get_sources(enabled_only=True)
    timeout = int(db.get_setting("check_timeout", "10"))
    parallel = int(db.get_setting("check_parallel", "50"))

    if progress_callback:
        progress_callback(0, len(sources), "Загрузка источников")

    for i, source in enumerate(sources):
        if progress_callback:
            progress_callback(i, len(sources), f"Источник: {source['name']}")
        start = time.monotonic()
        try:
            text = fetch_source(source["url"])
            elapsed = (time.monotonic() - start) * 1000
            channels = parse_m3u(text)
            valid_urls = set()
            for ch in channels:
                db.upsert_channel(source["id"], ch["name"], ch["url"], ch["inf_line"], ch["group_title"])
                valid_urls.add(ch["url"])
            db.delete_stale_channels(source["id"], valid_urls)
            db.update_source_status(source["id"], True, len(channels), round(elapsed, 1))
            print(f"[checker] Source {source['name']}: {len(channels)} channels, {round(elapsed)}ms")
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            db.update_source_status(source["id"], False, 0, round(elapsed, 1))
            print(f"[checker] Error fetching source {source['name']}: {e}")
            continue

    all_channels = db.get_channels()
    if not all_channels:
        if progress_callback:
            progress_callback(1, 1, "Нет каналов")
        return

    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=Retry(total=2)))
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=2)))

    total = len(all_channels)
    print(f"[checker] Checking {total} channels ({parallel} workers, timeout={timeout}s)...")

    if progress_callback:
        progress_callback(0, total, "Проверка каналов")

    checked = [0]
    lock = __import__('threading').Lock()

    def check_one(ch):
        alive, ms = check_single_channel(session, ch["url"], timeout)
        with lock:
            checked[0] += 1
            if progress_callback:
                progress_callback(checked[0], total, "Проверка каналов")
        return (ch["id"], alive, ms)

    with ThreadPoolExecutor(max_workers=parallel) as executor:
        results = list(executor.map(check_one, all_channels))

    batch_update_channels(results)

    alive_count = sum(1 for _, alive, _ in results if alive)
    print(f"[checker] Done. Alive: {alive_count}/{total}")
