#!/usr/bin/env python3
import sqlite3
import time
import os
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/iptv.db")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                is_alive INTEGER DEFAULT 0,
                channel_count INTEGER DEFAULT 0,
                last_check REAL,
                response_time_ms REAL,
                created_at REAL DEFAULT (strftime('%s','now'))
            );
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                inf_line TEXT,
                group_title TEXT DEFAULT 'Другое',
                last_check REAL,
                is_alive INTEGER DEFAULT 0,
                response_time_ms REAL,
                total_checks INTEGER DEFAULT 0,
                alive_checks INTEGER DEFAULT 0,
                created_at REAL DEFAULT (strftime('%s','now')),
                FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS epg_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                last_download REAL,
                channel_count INTEGER DEFAULT 0,
                is_alive INTEGER DEFAULT 0,
                response_time_ms REAL,
                last_check REAL,
                error_message TEXT,
                created_at REAL DEFAULT (strftime('%s','now'))
            );
            CREATE TABLE IF NOT EXISTS access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                timestamp REAL DEFAULT (strftime('%s','now'))
            );
        """)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(epg_sources)").fetchall()]
        if "is_alive" not in cols:
            conn.execute("ALTER TABLE epg_sources ADD COLUMN is_alive INTEGER DEFAULT 0")
        if "response_time_ms" not in cols:
            conn.execute("ALTER TABLE epg_sources ADD COLUMN response_time_ms REAL")
        if "last_check" not in cols:
            conn.execute("ALTER TABLE epg_sources ADD COLUMN last_check REAL")
        if "error_message" not in cols:
            conn.execute("ALTER TABLE epg_sources ADD COLUMN error_message TEXT")
        ch_cols = [r[1] for r in conn.execute("PRAGMA table_info(channels)").fetchall()]
        if "total_checks" not in ch_cols:
            conn.execute("ALTER TABLE channels ADD COLUMN total_checks INTEGER DEFAULT 0")
        if "alive_checks" not in ch_cols:
            conn.execute("ALTER TABLE channels ADD COLUMN alive_checks INTEGER DEFAULT 0")
        src_cols = [r[1] for r in conn.execute("PRAGMA table_info(sources)").fetchall()]
        if "is_alive" not in src_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN is_alive INTEGER DEFAULT 0")
        if "channel_count" not in src_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN channel_count INTEGER DEFAULT 0")
        if "last_check" not in src_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN last_check REAL")
        if "response_time_ms" not in src_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN response_time_ms REAL")
        row = conn.execute("SELECT value FROM settings WHERE key='check_interval'").fetchone()
        if not row:
            conn.execute("INSERT INTO settings (key, value) VALUES ('check_interval', '3600')")
            conn.execute("INSERT INTO settings (key, value) VALUES ('check_parallel', '50')")
            conn.execute("INSERT INTO settings (key, value) VALUES ('check_timeout', '10')")
            conn.execute("INSERT INTO settings (key, value) VALUES ('auth_login', 'admin')")
            conn.execute("INSERT INTO settings (key, value) VALUES ('auth_password', 'admin')")
            conn.execute("INSERT INTO settings (key, value) VALUES ('playlist_all', '1')")
            conn.execute("INSERT INTO settings (key, value) VALUES ('playlist_fast', '1')")
            conn.execute("INSERT INTO settings (key, value) VALUES ('playlist_medium', '1')")
            conn.execute("INSERT INTO settings (key, value) VALUES ('playlist_slow', '1')")
            conn.execute("INSERT INTO settings (key, value) VALUES ('epg_update_interval', '86400')")
            conn.execute("INSERT INTO settings (key, value) VALUES ('availability_period_days', '7')")
            conn.execute("INSERT INTO settings (key, value) VALUES ('min_availability', '0')")
        epg_count = conn.execute("SELECT COUNT(*) as cnt FROM epg_sources").fetchone()["cnt"]
        if epg_count == 0:
            conn.execute("INSERT INTO epg_sources (name, url, enabled) VALUES ('IPTVX One', 'http://iptvx.one/epg/epg_lite.xml.gz', 1)")
            conn.execute("INSERT INTO epg_sources (name, url, enabled) VALUES ('ProgramTV', 'http://programtv.ru/xmltv.xml.gz', 1)")
            conn.execute("INSERT INTO epg_sources (name, url, enabled) VALUES ('EPG It999 (Universal)', 'http://epg.it999.ru/edem.xml.gz', 1)")
            conn.execute("INSERT INTO epg_sources (name, url, enabled) VALUES ('EPG It999 RU', 'http://epg.it999.ru/ru2.xml.gz', 1)")
            conn.execute("INSERT INTO epg_sources (name, url, enabled) VALUES ('OTT EPG', 'https://ottepg.ru/ottepg.xml.gz', 1)")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )


def add_source(name, url, enabled=True):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sources (name, url, enabled) VALUES (?, ?, ?)",
            (name, url, 1 if enabled else 0),
        )
        return cur.lastrowid


def update_source(source_id, name=None, url=None, enabled=None):
    with get_conn() as conn:
        fields, values = [], []
        if name is not None:
            fields.append("name=?")
            values.append(name)
        if url is not None:
            fields.append("url=?")
            values.append(url)
        if enabled is not None:
            fields.append("enabled=?")
            values.append(1 if enabled else 0)
        if fields:
            values.append(source_id)
            conn.execute(f"UPDATE sources SET {','.join(fields)} WHERE id=?", values)


def update_source_status(source_id, is_alive, channel_count, response_time_ms=None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE sources SET is_alive=?, channel_count=?, last_check=?, response_time_ms=? WHERE id=?",
            (1 if is_alive else 0, channel_count, time.time(), response_time_ms, source_id),
        )


def delete_source(source_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM channels WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))


def get_sources(enabled_only=False):
    with get_conn() as conn:
        q = "SELECT * FROM sources"
        if enabled_only:
            q += " WHERE enabled=1"
        q += " ORDER BY name"
        return [dict(r) for r in conn.execute(q).fetchall()]


def upsert_channel(source_id, name, url, inf_line, group_title):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM channels WHERE source_id=? AND url=?", (source_id, url)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE channels SET name=?, inf_line=?, group_title=? WHERE id=?",
                (name, inf_line, group_title, existing["id"]),
            )
            return existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO channels (source_id, name, url, inf_line, group_title) VALUES (?, ?, ?, ?, ?)",
                (source_id, name, url, inf_line, group_title),
            )
            return cur.lastrowid


def update_channel_status(channel_id, is_alive, response_time_ms=None):
    with get_conn() as conn:
        alive_val = 1 if is_alive else 0
        conn.execute(
            "UPDATE channels SET is_alive=?, response_time_ms=?, last_check=?, total_checks=total_checks+1, alive_checks=alive_checks+? WHERE id=?",
            (alive_val, response_time_ms, time.time(), alive_val, channel_id),
        )


def delete_stale_channels(source_id, valid_urls):
    with get_conn() as conn:
        if valid_urls:
            placeholders = ",".join(["?"] * len(valid_urls))
            conn.execute(
                f"DELETE FROM channels WHERE source_id=? AND url NOT IN ({placeholders})",
                [source_id] + list(valid_urls),
            )
        else:
            conn.execute("DELETE FROM channels WHERE source_id=?", (source_id,))


def get_channels(source_id=None, alive_only=False):
    with get_conn() as conn:
        q = "SELECT c.*, s.name as source_name FROM channels c LEFT JOIN sources s ON c.source_id=s.id"
        conditions, params = [], []
        if source_id:
            conditions.append("c.source_id=?")
            params.append(source_id)
        if alive_only:
            conditions.append("c.is_alive=1")
        if conditions:
            q += " WHERE " + " AND ".join(conditions)
        q += " ORDER BY c.group_title, c.name"
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def get_stats():
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM channels").fetchone()["cnt"]
        alive = conn.execute("SELECT COUNT(*) as cnt FROM channels WHERE is_alive=1").fetchone()["cnt"]
        sources = conn.execute("SELECT COUNT(*) as cnt FROM sources").fetchone()["cnt"]
        avg_ms = conn.execute(
            "SELECT AVG(response_time_ms) as avg_ms FROM channels WHERE is_alive=1 AND response_time_ms IS NOT NULL"
        ).fetchone()["avg_ms"]
        return {
            "total_channels": total,
            "alive_channels": alive,
            "dead_channels": total - alive,
            "sources": sources,
            "avg_response_ms": round(avg_ms, 1) if avg_ms else None,
        }


def clear_channels_for_source(source_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM channels WHERE source_id=?", (source_id,))


def add_epg_source(name, url, enabled=True):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO epg_sources (name, url, enabled) VALUES (?, ?, ?)",
            (name, url, 1 if enabled else 0),
        )
        return cur.lastrowid


def update_epg_source(epg_id, name=None, url=None, enabled=None):
    with get_conn() as conn:
        fields, values = [], []
        if name is not None:
            fields.append("name=?")
            values.append(name)
        if url is not None:
            fields.append("url=?")
            values.append(url)
        if enabled is not None:
            fields.append("enabled=?")
            values.append(1 if enabled else 0)
        if fields:
            values.append(epg_id)
            conn.execute(f"UPDATE epg_sources SET {','.join(fields)} WHERE id=?", values)


def delete_epg_source(epg_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM epg_sources WHERE id=?", (epg_id,))


def get_epg_sources(enabled_only=False):
    with get_conn() as conn:
        q = "SELECT * FROM epg_sources"
        if enabled_only:
            q += " WHERE enabled=1"
        q += " ORDER BY name"
        return [dict(r) for r in conn.execute(q).fetchall()]


def update_epg_download_stats(epg_id, channel_count):
    with get_conn() as conn:
        conn.execute(
            "UPDATE epg_sources SET last_download=?, channel_count=? WHERE id=?",
            (time.time(), channel_count, epg_id),
        )


def update_epg_source_status(epg_id, is_alive, response_time_ms=None, error_message=None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE epg_sources SET is_alive=?, response_time_ms=?, last_check=?, error_message=? WHERE id=?",
            (1 if is_alive else 0, response_time_ms, time.time(), error_message, epg_id),
        )


def log_access(endpoint, ip_address, user_agent):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO access_log (endpoint, ip_address, user_agent) VALUES (?, ?, ?)",
            (endpoint, ip_address, user_agent),
        )


def get_access_log(endpoint=None, limit=10, offset=0, date_from=None, date_to=None):
    with get_conn() as conn:
        conditions = []
        params = []
        if endpoint:
            conditions.append("endpoint=?")
            params.append(endpoint)
        if date_from:
            from datetime import datetime
            ts = datetime.strptime(date_from, "%Y-%m-%d").timestamp()
            conditions.append("timestamp>=?")
            params.append(ts)
        if date_to:
            from datetime import datetime, timedelta
            ts = datetime.strptime(date_to, "%Y-%m-%d").timestamp() + 86400
            conditions.append("timestamp<=?")
            params.append(ts)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        rows = conn.execute(
            f"SELECT * FROM access_log{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        total = conn.execute(f"SELECT COUNT(*) as cnt FROM access_log{where}", params).fetchone()["cnt"]
        return {"items": [dict(r) for r in rows], "total": total}


def get_access_stats():
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM access_log").fetchone()["cnt"]
        playlist = conn.execute("SELECT COUNT(*) as cnt FROM access_log WHERE endpoint='playlist'").fetchone()["cnt"]
        epg = conn.execute("SELECT COUNT(*) as cnt FROM access_log WHERE endpoint='epg'").fetchone()["cnt"]
        unique_ips = conn.execute("SELECT COUNT(DISTINCT ip_address) as cnt FROM access_log").fetchone()["cnt"]
        return {
            "total": total,
            "playlist": playlist,
            "epg": epg,
            "unique_ips": unique_ips,
        }
