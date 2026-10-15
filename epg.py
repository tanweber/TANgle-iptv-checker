#!/usr/bin/env python3
import gzip
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import zipfile
import io
import time
import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import database as db

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux) IPTV-Checker"}
EPG_PATH = os.environ.get("EPG_PATH", "/playlist/epg.xml")
EPG_CACHE_DIR = os.environ.get("EPG_CACHE_DIR", "/data/epg_cache")
# Горизонт программы: сколько дней вперёд включать в итоговый EPG
EPG_DAYS = int(os.environ.get("EPG_DAYS", "7"))


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


def build_playlist_channels(m3u_path):
    """Каналы итогового плейлиста: [(норм. имя, id для EPG, отображаемое имя)].

    id для EPG = tvg-id из плейлиста (по нему плееры сопоставляют программу),
    иначе — само название канала (плееры сопоставят по display-name).
    """
    result = []
    seen = set()
    try:
        with open(m3u_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("#EXTINF:"):
                    continue
                parts = line.rsplit(",", 1)
                if len(parts) != 2:
                    continue
                display = parts[1].strip()
                norm = normalize_name(display)
                if not norm:
                    continue
                m = re.search(r'tvg-id="([^"]*)"', parts[0])
                out_id = (m.group(1).strip() if m else "") or display
                if out_id in seen:
                    continue
                seen.add(out_id)
                result.append((norm, out_id, display))
    except FileNotFoundError:
        pass
    return result


def build_channel_set(m3u_path):
    return {norm for norm, _, _ in build_playlist_channels(m3u_path)}


def _xmltv_dt(s):
    # XMLTV start: "20260909193000 +0300" (зона может отсутствовать — считаем UTC)
    if not s:
        return None
    s = s.strip()
    try:
        return datetime.datetime.strptime(s, "%Y%m%d%H%M%S %z")
    except ValueError:
        pass
    try:
        return datetime.datetime.strptime(s[:14], "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


# Символы, недопустимые в XML 1.0: из-за них плееры не могут разобрать файл
_INVALID_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _clean_text(s):
    return _INVALID_XML_CHARS.sub("", s).strip() if s else ""


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


def scan_cached_source(path, wanted, keep_from, horizon):
    """Потоково читает XMLTV-файл и возвращает {норм. имя: [передачи]}
    только для нужных каналов и только в пределах окна [keep_from, horizon]."""
    # Несколько каналов источника могут давать одно норм. имя («Россия 1 (+2)»,
    # «Россия 1 (+4)» → «россия 1»). Берём ровно один: с точным совпадением
    # названия, иначе первый встретившийся — иначе программы перемешаются.
    chosen = {}  # норм. имя -> (id канала, приоритет)
    id_to_norms = None
    result = {}
    root = None
    for event, el in ET.iterparse(path, events=("start", "end")):
        if event == "start":
            if root is None:
                root = el
            continue
        if el.tag == "channel":
            ch_id = el.get("id", "")
            for dn in el.findall("display-name"):
                n = normalize_name(dn.text)
                if n in wanted:
                    score = 0 if dn.text.strip().lower() == n else 1
                    if n not in chosen or score < chosen[n][1]:
                        chosen[n] = (ch_id, score)
            root.clear()
        elif el.tag == "programme":
            if id_to_norms is None:
                id_to_norms = {}
                for n, (ch_id, _) in chosen.items():
                    id_to_norms.setdefault(ch_id, set()).add(n)
            norms = id_to_norms.get(el.get("channel", ""))
            if norms:
                start = _xmltv_dt(el.get("start"))
                if start is not None and keep_from <= start <= horizon:
                    stop = _xmltv_dt(el.get("stop"))
                    title = _clean_text(el.findtext("title"))
                    if title:
                        prog = {
                            "start": el.get("start").strip(),
                            "stop": el.get("stop", "").strip() if stop else "",
                            "start_dt": start,
                            "stop_dt": stop,
                            "title": title,
                            "desc": _clean_text(el.findtext("desc")),
                            "category": _clean_text(el.findtext("category")),
                        }
                        for n in norms:
                            result.setdefault(n, []).append(prog)
            root.clear()
    return result


def _sanitize_programmes(progs):
    """Сортирует по времени и убирает дубли и пересечения внутри канала."""
    # Битые записи источника: окончание раньше начала
    progs = sorted((p for p in progs if p["stop_dt"] is None or p["stop_dt"] > p["start_dt"]),
                   key=lambda p: p["start_dt"])
    out = []
    last_stop = None
    for p in progs:
        if last_stop is not None and p["start_dt"] < last_stop:
            continue
        out.append(p)
        last_stop = p["stop_dt"] or p["start_dt"]
    # stop у передачи без stop = start следующей
    for cur, nxt in zip(out, out[1:]):
        if not cur["stop"]:
            cur["stop"] = nxt["start"]
    return out


def merge_from_cache(epg_sources_data, playlist_channels):
    now = datetime.datetime.now(datetime.timezone.utc)
    horizon = now + datetime.timedelta(days=EPG_DAYS)
    keep_from = now - datetime.timedelta(hours=6)
    wanted = {norm for norm, _, _ in playlist_channels}

    # Для каждого канала берём программу из ОДНОГО источника — с наибольшим
    # покрытием (сначала по числу дней, потом по числу передач). Смешивание
    # источников даёт пересечения и битые ссылки на каналы.
    def coverage(progs):
        return len({p["start"][:8] for p in progs}), len(progs)

    best = {}
    for source in epg_sources_data:
        cache = _cache_path(source["id"])
        if not os.path.exists(cache):
            continue
        try:
            found = scan_cached_source(cache, wanted, keep_from, horizon)
        except Exception as e:
            print(f"[epg] Error parsing cached {source['name']}: {e}")
            continue
        for norm, progs in found.items():
            if norm not in best or coverage(progs) > coverage(best[norm]):
                best[norm] = progs
        db.update_epg_download_stats(source["id"], len(found))
        print(f"[epg] {source['name']}: {len(found)} channels matched from cache")

    for norm in list(best):
        best[norm] = _sanitize_programmes(best[norm])

    root = ET.Element("tv")
    root.set("generator-info-name", "TANgle")
    out_channels = [(norm, out_id, display) for norm, out_id, display in playlist_channels if best.get(norm)]
    for _, out_id, display in out_channels:
        ch_el = ET.SubElement(root, "channel")
        ch_el.set("id", out_id)
        dn = ET.SubElement(ch_el, "display-name")
        dn.text = display

    kept_total = 0
    for norm, out_id, _ in out_channels:
        for p in best[norm]:
            prog_el = ET.SubElement(root, "programme")
            prog_el.set("start", p["start"])
            if p["stop"]:
                prog_el.set("stop", p["stop"])
            prog_el.set("channel", out_id)
            title_el = ET.SubElement(prog_el, "title")
            title_el.set("lang", "ru")
            title_el.text = p["title"]
            if p["desc"]:
                desc_el = ET.SubElement(prog_el, "desc")
                desc_el.set("lang", "ru")
                desc_el.text = p["desc"]
            if p["category"]:
                cat_el = ET.SubElement(prog_el, "category")
                cat_el.set("lang", "ru")
                cat_el.text = p["category"]
            kept_total += 1

    print(f"[epg] Horizon {EPG_DAYS}d: {len(out_channels)} channels, {kept_total} programmes")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    return xml, len(out_channels)


def write_epg_file(xml_content):
    os.makedirs(os.path.dirname(EPG_PATH), exist_ok=True)
    tmp_path = EPG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(xml_content)
    os.replace(tmp_path, EPG_PATH)
    # Precompressed copy: отдаётся только клиентам, умеющим gzip (браузеры).
    # Televizo/okhttp (шлют Accept-Encoding, но не декодируют) получают plain.
    gz_path = EPG_PATH + ".gz"
    tmp_gz = gz_path + ".tmp"
    with open(tmp_gz, "wb") as f:
        f.write(gzip.compress(xml_content.encode("utf-8"), mtime=0))
    os.replace(tmp_gz, gz_path)


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
        return 0

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
    playlist_channels = build_playlist_channels(playlist_path)
    if not playlist_channels:
        print("[epg] No channels in playlist")
        write_epg_file('<?xml version="1.0" encoding="UTF-8"?><tv/>')
        return 0

    print(f"[epg] Merging EPG for {len(playlist_channels)} playlist channels...")
    xml_content, merged_count = merge_from_cache(epg_sources, playlist_channels)
    write_epg_file(xml_content)
    print(f"[epg] EPG saved to {EPG_PATH} ({merged_count} channels)")
    return merged_count
