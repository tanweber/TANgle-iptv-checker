#!/usr/bin/env python3
import gzip
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import zipfile
import io
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import database as db

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux) IPTV-Checker"}
EPG_PATH = os.environ.get("EPG_PATH", "/playlist/epg.xml")
EPG_CACHE_DIR = os.environ.get("EPG_CACHE_DIR", "/data/epg_cache")


def normalize_name(name):
    if not name:
        return ""
    name = name.lower().strip()
    name = re.sub(r'\b(hd|fhd|uhd|4k|sd)\b', '', name)
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'[«»""]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def download_epg_source(url):
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=Retry(total=2)))
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=2)))
    try:
        r = session.get(url, timeout=120, headers=HEADERS)
        r.raise_for_status()
        data = r.content
        if data[:2] == b'\x1f\x8b':
            data = gzip.decompress(data)
        elif data[:2] == b'PK':
            zf = zipfile.ZipFile(io.BytesIO(data))
            xml_names = [n for n in zf.namelist() if n.endswith('.xml')]
            if xml_names:
                data = zf.read(xml_names[0])
            else:
                data = zf.read(zf.namelist()[0])
        return data
    except Exception as e:
        print(f"[epg] Error downloading {url}: {e}")
        return None


def check_epg_source(url, timeout=15):
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=Retry(total=1)))
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=1)))
    start = time.monotonic()
    try:
        r = session.get(url, timeout=timeout, headers=HEADERS, stream=True)
        elapsed = (time.monotonic() - start) * 1000
        alive = r.status_code in (200, 301, 302, 307, 308)
        r.close()
        return alive, round(elapsed, 1) if alive else None, None
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return False, None, str(e)[:200]


def parse_xmltv(xml_bytes):
    try:
        text = xml_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = xml_bytes.decode("windows-1251")
        except UnicodeDecodeError:
            return {}, {}

    root = ET.fromstring(text)

    channel_map = {}
    for ch_el in root.findall("channel"):
        ch_id = ch_el.get("id", "")
        display_names = ch_el.findall("display-name")
        if display_names and display_names[0].text:
            norm_name = normalize_name(display_names[0].text)
            if norm_name and norm_name not in channel_map:
                channel_map[norm_name] = ch_id

    id_to_norm = {v: k for k, v in channel_map.items()}

    programmes = {}
    for prog in root.findall("programme"):
        ch_id = prog.get("channel", "")
        norm_name = id_to_norm.get(ch_id)
        if not norm_name:
            continue

        start = prog.get("start", "")
        stop = prog.get("stop", "")
        title_el = prog.find("title")
        desc_el = prog.find("desc")
        title = title_el.text if title_el is not None and title_el.text else ""
        desc = desc_el.text if desc_el is not None and desc_el.text else ""

        if norm_name not in programmes:
            programmes[norm_name] = []
        programmes[norm_name].append({
            "start": start,
            "stop": stop,
            "title": title,
            "desc": desc,
            "channel_id": ch_id,
        })

    return channel_map, programmes


def build_channel_set(m3u_path):
    names = set()
    try:
        with open(m3u_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#EXTINF:"):
                    parts = line.rsplit(",", 1)
                    if len(parts) == 2:
                        norm = normalize_name(parts[1])
                        if norm:
                            names.add(norm)
    except FileNotFoundError:
        pass
    return names


def _cache_path(source_id):
    return os.path.join(EPG_CACHE_DIR, f"epg_{source_id}.xml")


def _cache_age_hours(source_id):
    path = _cache_path(source_id)
    if not os.path.exists(path):
        return 999
    mtime = os.path.getmtime(path)
    return (time.time() - mtime) / 3600


def download_all_sources(epg_sources_data):
    os.makedirs(EPG_CACHE_DIR, exist_ok=True)

    def fetch_one(source):
        raw = download_epg_source(source["url"])
        if raw is None:
            db.update_epg_source_status(source["id"], False, None, "Download failed")
            return source, False
        cache = _cache_path(source["id"])
        tmp = cache + ".tmp"
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, cache)
        db.update_epg_source_status(source["id"], True, None, None)
        print(f"[epg] Cached {source['name']} ({len(raw)} bytes)")
        return source, True

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(fetch_one, epg_sources_data))

    for source, ok in results:
        if not ok:
            print(f"[epg] Failed to cache {source['name']}")


def merge_from_cache(epg_sources_data, playlist_channel_names):
    merged_programmes = {}
    merged_channels = {}

    for source in epg_sources_data:
        cache = _cache_path(source["id"])
        if not os.path.exists(cache):
            continue

        try:
            with open(cache, "rb") as f:
                raw = f.read()
            channel_map, programmes = parse_xmltv(raw)
        except Exception as e:
            print(f"[epg] Error parsing cached {source['name']}: {e}")
            continue

        for norm_name, ch_id in channel_map.items():
            if norm_name in playlist_channel_names and norm_name not in merged_channels:
                merged_channels[norm_name] = ch_id

        matched_count = 0
        for norm_name, progs in programmes.items():
            if norm_name in playlist_channel_names:
                if norm_name not in merged_programmes:
                    merged_programmes[norm_name] = []
                merged_programmes[norm_name].extend(progs)
                matched_count += 1

        db.update_epg_download_stats(source["id"], matched_count)
        print(f"[epg] {source['name']}: {matched_count} channels matched from cache")

    for ch_name in merged_programmes:
        seen = set()
        unique = []
        for p in merged_programmes[ch_name]:
            key = (p["start"], p["title"])
            if key not in seen:
                seen.add(key)
                unique.append(p)
        merged_programmes[ch_name] = sorted(unique, key=lambda x: x["start"])

    root = ET.Element("tv")
    root.set("generator-info-name", "iptv-autocheck")

    written_ids = set()
    for norm_name in sorted(merged_programmes.keys()):
        ch_id = merged_channels.get(norm_name)
        if ch_id and ch_id not in written_ids:
            written_ids.add(ch_id)
            ch_el = ET.SubElement(root, "channel")
            ch_el.set("id", ch_id)
            dn = ET.SubElement(ch_el, "display-name")
            dn.text = norm_name

    for norm_name, progs in merged_programmes.items():
        for p in progs:
            prog_el = ET.SubElement(root, "programme")
            prog_el.set("start", p["start"])
            prog_el.set("stop", p["stop"])
            prog_el.set("channel", p["channel_id"])
            title_el = ET.SubElement(prog_el, "title")
            title_el.text = p["title"]
            if p.get("desc"):
                desc_el = ET.SubElement(prog_el, "desc")
                desc_el.text = p["desc"]

    return ET.tostring(root, encoding="unicode", xml_declaration=False), len(merged_programmes)


def write_epg_file(xml_content):
    os.makedirs(os.path.dirname(EPG_PATH), exist_ok=True)
    tmp_path = EPG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(xml_content)
    os.replace(tmp_path, EPG_PATH)


def download_epg_sources():
    epg_sources = db.get_epg_sources(enabled_only=True)
    if not epg_sources:
        print("[epg] No enabled EPG sources to download")
        return

    print(f"[epg] Downloading {len(epg_sources)} EPG sources...")
    download_all_sources(epg_sources)
    print("[epg] Download complete")


def update_epg():
    epg_sources = db.get_epg_sources(enabled_only=True)
    if not epg_sources:
        print("[epg] No enabled EPG sources")
        write_epg_file('<?xml version="1.0" encoding="UTF-8"?><tv/>')
        return

    for source in epg_sources:
        age = _cache_age_hours(source["id"])
        if age > 23:
            print(f"[epg] Cache stale for {source['name']}, downloading...")
            raw = download_epg_source(source["url"])
            if raw is not None:
                cache = _cache_path(source["id"])
                os.makedirs(EPG_CACHE_DIR, exist_ok=True)
                tmp = cache + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(raw)
                os.replace(tmp, cache)
                db.update_epg_source_status(source["id"], True, None, None)
                print(f"[epg] Cached {source['name']} ({len(raw)} bytes)")
            else:
                db.update_epg_source_status(source["id"], False, None, "Download failed")

    playlist_path = os.environ.get("PLAYLIST_PATH", "/playlist/rus_fixed.m3u")
    channel_names = build_channel_set(playlist_path)
    if not channel_names:
        print("[epg] No channels in playlist")
        write_epg_file('<?xml version="1.0" encoding="UTF-8"?><tv/>')
        return

    print(f"[epg] Merging EPG for {len(channel_names)} playlist channels...")
    xml_content, merged_count = merge_from_cache(epg_sources, channel_names)
    write_epg_file(xml_content)
    print(f"[epg] EPG saved to {EPG_PATH} ({merged_count} channels)")
    return merged_count
