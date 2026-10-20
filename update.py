#!/usr/bin/env python3
"""Tracking Loker: penarik data lowongan harian.

Sumber
  1. Karirhub Kemnaker, lewat API publik yang juga dipakai situs karirhub.kemnaker.go.id.
  2. Situs karier perusahaan yang terdaftar di perusahaan.json: emiten besar BEI dan anak usahanya,
     lewat Greenhouse, Lever, Ashby (di sini) serta Workday, SmartRecruiters, Workable, SuccessFactors,
     Oracle, Radancy, dan data JobPosting di halaman lowongan (karier.py).

Hasil (ditulis di folder yang sama dengan skrip ini)
  jobs.json   lowongan aktif dalam format ringkas, dibaca situs saat dibuka
  links.json  tautan lamaran asli per lowongan, dibaca saat detail dibuka
  stats.json  riwayat harian: total aktif, baru, ditutup

Mode cek (python3 update.py --cek) memeriksa situs karier semua perusahaan di perusahaan.json dan
menulis cek-karier.json, tanpa mengubah data lowongan.

Hanya memakai pustaka standar Python, jadi tidak perlu pip install di GitHub Actions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import karier

API = "https://api.kemnaker.go.id/karirhub"
LISTING = f"{API}/vacancy/v2/published-industrial-vacancies"
PROVINCES = f"{API}/onboarding/v2/provinces"
CITIES = f"{API}/onboarding/v2/cities"
EDUCATIONS = f"{API}/v1/educations"
LOGO_BASE = "https://kemnaker-assets.oss-accelerate.aliyuncs.com/"

WIB = timezone(timedelta(hours=7))
HERE = Path(__file__).resolve().parent
FORMAT_VERSION = 1
HISTORY_DAYS = 180
# Penarikan dianggap utuh bila minimal 90% dari total yang dilaporkan API berhasil diambil.
COMPLETE_RATIO = 0.9
MAX_PAGES = 4000
# Lowongan yang lokasinya hanya kecamatan dilengkapi dari halaman detail; dibatasi per hari supaya
# penarikan tetap selesai jauh sebelum batas waktu GitHub Actions.
DETAIL_CAP = 600
DETAIL_BUDGET_SEC = 30 * 60
# Batas waktu untuk semua situs karier perusahaan, supaya penarikan harian tetap di bawah batas GitHub Actions.
COMPANY_BUDGET_SEC = 12 * 60
BOARDS = {"greenhouse", "lever", "ashby"}
# Gaji di bawah ini hampir pasti upah harian/per paket, bukan gaji bulanan.
MIN_MONTHLY = 500_000
TYPE_NAMES = {
    "contract": "Kontrak", "kontrak": "Kontrak",
    "internship": "Magang", "intern": "Magang", "magang": "Magang",
    "full time": "Full time", "full-time": "Full time", "fulltime": "Full time",
    "part time": "Part time", "part-time": "Part time", "parttime": "Part time",
    "freelance": "Freelance", "daily": "Harian", "harian": "Harian",
}
FIELDS = [
    "id", "title", "company", "city", "province", "platform", "function",
    "industry", "type", "edu", "smin", "smax", "posted", "expires", "first", "via",
]
LISTS = ["company", "city", "province", "platform", "function", "industry", "type", "edu", "via"]


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- jaringan

def _user_agent() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    return f"TrackingLoker/1.0 (+https://github.com/{repo})" if repo else "TrackingLoker/1.0"


def http_json(url: str, params: dict | None = None, tries: int = 4, timeout: int = 40):
    """GET JSON dengan percobaan ulang. Galat 4xx (kecuali 408/429) langsung dilempar."""
    if params:
        url = url + ("&" if "?" in url else "?") + urlencode(params)
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = Request(url, headers={"Accept": "application/json", "User-Agent": _user_agent()})
            with urlopen(req, timeout=timeout) as res:
                return json.loads(res.read().decode("utf-8"))
        except HTTPError as err:
            last = err
            if 400 <= err.code < 500 and err.code not in (408, 429):
                raise
        except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as err:
            last = err
        wait = 2 ** attempt * 2
        log(f"  ulangi dalam {wait} dtk ({last})")
        time.sleep(wait)
    raise RuntimeError(f"Gagal mengambil {url}: {last}")


# Diganti di pengujian.
fetch = http_json
sleep = time.sleep


def paged(url: str, params: dict | None = None, limits=(100, 50, 18), delay: float = 0.25,
          max_pages: int = MAX_PAGES):
    """Ambil semua halaman dari endpoint Laravel (data + meta.last_page).

    Mengembalikan (items, total_dari_meta). Jika ukuran halaman ditolak, coba ukuran lebih kecil.
    """
    params = dict(params or {})
    limit = None
    first = None
    for size in limits:
        try:
            first = fetch(url, {**params, "page": 1, "limit": size})
            limit = size
            break
        except HTTPError as err:
            if err.code in (400, 422):
                log(f"  ukuran halaman {size} ditolak, coba lebih kecil")
                continue
            raise
    if first is None:
        raise RuntimeError(f"Semua ukuran halaman ditolak oleh {url}")

    items = list(first.get("data") or [])
    meta = first.get("meta") or {}
    total = _int(meta.get("total"), len(items))
    last_page = _int(meta.get("last_page", meta.get("lastPage")), 1)
    page = 1
    while page < min(last_page, max_pages):
        page += 1
        if delay:
            sleep(delay)
        payload = fetch(url, {**params, "page": page, "limit": limit})
        rows = payload.get("data") or []
        if not rows:
            break
        items.extend(rows)
        meta = payload.get("meta") or {}
        last_page = _int(meta.get("last_page", meta.get("lastPage")), last_page)
        if page % 50 == 0:
            log(f"  halaman {page}/{last_page} ({len(items)} baris)")
    return items, total


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- referensi Karirhub

def load_refs() -> dict:
    """Provinsi, kota/kabupaten, dan jenjang pendidikan. Masing-masing boleh gagal."""
    refs = {"provinces": {}, "cities": {}, "educations": {}}
    try:
        rows, _ = paged(PROVINCES, limits=(100, 50), delay=0)
        refs["provinces"] = {str(r["id"]): clean(r.get("name")) for r in rows if r.get("id")}
    except Exception as err:  # noqa: BLE001
        log(f"! provinsi gagal: {err}")
    try:
        rows, _ = paged(CITIES, limits=(100, 50), delay=0.1)
        refs["cities"] = {
            str(r["id"]): (clean(r.get("name")), str(r.get("province_id") or ""))
            for r in rows if r.get("id")
        }
    except Exception as err:  # noqa: BLE001
        log(f"! kota gagal: {err}")
    try:
        payload = fetch(EDUCATIONS)
        refs["educations"] = {str(r["id"]): clean(r.get("name")) for r in payload.get("data") or [] if r.get("id")}
    except Exception as err:  # noqa: BLE001
        log(f"! pendidikan gagal: {err}")
    log(f"Referensi: {len(refs['provinces'])} provinsi, {len(refs['cities'])} kota/kab, "
        f"{len(refs['educations'])} jenjang")
    return refs


# ---------------------------------------------------------------- normalisasi

def clean(value) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text


def strip_tracking(url: str) -> str:
    """Buang parameter utm_* supaya tautan lebih pendek."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def logo_tail(url: str) -> str:
    url = clean(url)
    if url.startswith(LOGO_BASE):
        return url[len(LOGO_BASE):]
    return url


def wib_epoch(text: str) -> int:
    """'2026-10-13 16:21:09' (waktu WIB) menjadi detik epoch."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=WIB).timestamp())
        except (TypeError, ValueError):
            continue
    return 0


def iso_epoch(text) -> int:
    if not text:
        return 0
    if isinstance(text, (int, float)):
        # Lever memakai milidetik.
        return int(text / 1000) if text > 10_000_000_000 else int(text)
    try:
        return int(datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def salary(row: dict) -> tuple[int, int]:
    if row.get("show_salary") is False:
        return 0, 0
    lo = row.get("min_salary_amount")
    hi = row.get("max_salary_amount")
    if lo is None:
        lo = (row.get("min_salary") or {}).get("amount")
    if hi is None:
        hi = (row.get("max_salary") or {}).get("amount")
    lo, hi = _int(lo), _int(hi)
    currency = str(row.get("min_salary_currency") or row.get("max_salary_currency") or "IDR").upper()
    if currency != "IDR":
        return 0, 0
    lo = lo if lo >= MIN_MONTHLY else 0
    hi = hi if hi >= MIN_MONTHLY else 0
    if lo and hi and lo > hi:
        lo, hi = hi, lo
    return lo, hi


def job_type(name) -> str:
    name = clean(name)
    return TYPE_NAMES.get(name.lower()) or karier.norm_type(name)


def from_karirhub(row: dict, refs: dict) -> dict | None:
    job_id = clean(row.get("id"))
    title = clean(row.get("title"))
    if not job_id or not title:
        return None
    city, province = "", ""
    for loc in row.get("locations") or []:
        kind, _, ref = str(loc).partition(":")
        if kind == "city" and ref in refs["cities"]:
            city, prov_id = refs["cities"][ref]
            province = refs["provinces"].get(prov_id, "")
            break
        if kind == "province" and ref in refs["provinces"]:
            province = refs["provinces"][ref]
            break
    if not city and row.get("city_name"):
        city = clean(row.get("city_name"))
    lo, hi = salary(row)
    posted = _int(row.get("published_at")) or wib_epoch(clean(row.get("created_at")))
    return {
        "id": job_id,
        "title": title,
        "company": clean(row.get("company_name")) or "Perusahaan dirahasiakan",
        "logo": logo_tail(row.get("company_logo_uri") or ""),
        "city": city,
        "province": province,
        "platform": clean(row.get("platform_name")) or "Karirhub",
        "function": clean(row.get("job_function_name")),
        "industry": clean(row.get("industry_name")),
        "type": job_type(row.get("job_type_name")),
        "edu": refs["educations"].get(str(row.get("education_id") or ""), ""),
        "smin": lo,
        "smax": hi,
        "posted": posted,
        "expires": _int(row.get("expires_at")),
        "via": "karirhub",
        "link": strip_tracking(clean(row.get("platform_link"))),
    }


def place_from_detail(detail: dict, refs: dict) -> tuple[str, str]:
    """(kota/kabupaten, provinsi) dari detail lowongan Karirhub.

    Urutan: nama wilayah ("Kecamatan, Kota, Provinsi"), id di objek wilayah, lalu alamat perusahaan.
    """
    provinces, cities = refs["provinces"], refs["cities"]
    prov_by_name = {n.lower(): n for n in provinces.values() if n}
    city_by_name = {n.lower(): (n, pid) for n, pid in cities.values() if n}
    city, prov = "", ""
    region = detail.get("region") if isinstance(detail.get("region"), dict) else {}
    regionable = region.get("regionable") if isinstance(region.get("regionable"), dict) else {}

    for part in reversed([clean(p) for p in str(region.get("name") or "").split(",")]):
        low = part.lower()
        if not prov and low in prov_by_name:
            prov = prov_by_name[low]
        elif not city and low in city_by_name:
            city = city_by_name[low][0]
            prov = prov or provinces.get(city_by_name[low][1], "")
    if not city and region.get("regionable_type") == "city" and clean(regionable.get("name")).lower() in city_by_name:
        city = city_by_name[clean(regionable.get("name")).lower()][0]
    for cid in (regionable.get("city_id"), detail.get("city_id")):
        cid = str(cid or "")
        if not city and cid in cities:
            city = cities[cid][0]
            prov = prov or provinces.get(cities[cid][1], "")
    pid = str(regionable.get("province_id") or "")
    if not prov and pid in provinces:
        prov = provinces[pid]
    employer = detail.get("employer") if isinstance(detail.get("employer"), dict) else {}
    if not prov:
        cid, pid = str(employer.get("city_id") or ""), str(employer.get("province_id") or "")
        if not city and cid in cities:
            city = cities[cid][0]
        prov = provinces.get(pid, "") or (provinces.get(cities[cid][1], "") if cid in cities else "")
    return city, prov


def fill_locations(jobs: list[dict], prev: dict, checked: set[str], refs: dict, started: float) -> set[str]:
    """Lengkapi provinsi untuk lowongan yang lokasinya hanya kecamatan. Mengembalikan id yang sudah dicoba."""
    todo = []
    for job in jobs:
        if job["via"] != "karirhub" or job["province"]:
            continue
        old = prev.get(job["id"])
        if old and old.get("province"):
            job["city"], job["province"] = old["city"], old["province"]
        elif job["id"] not in checked:
            todo.append(job)
    done = {j["id"] for j in jobs if j["id"] in checked}
    filled = 0
    for job in todo[:DETAIL_CAP]:
        if time.monotonic() - started > DETAIL_BUDGET_SEC:
            log("  batas waktu detail tercapai, sisanya dilanjutkan besok")
            break
        try:
            detail = (fetch(f"{LISTING}/{job['id']}") or {}).get("data") or {}
        except Exception as err:  # noqa: BLE001
            log(f"  detail {job['id']} gagal: {err}")
            continue
        city, prov = place_from_detail(detail, refs)
        if prov:
            job["province"] = prov
            job["city"] = city or job["city"]
            filled += 1
        done.add(job["id"])
        sleep(0.2)
    if todo:
        log(f"Lokasi dilengkapi: {filled} dari {min(len(todo), DETAIL_CAP)} lowongan (antrean {len(todo)})")
    return done


def fetch_karirhub(refs: dict, max_pages: int = MAX_PAGES):
    log("Karirhub: menarik daftar lowongan")
    rows, total = paged(LISTING, max_pages=max_pages)
    jobs, seen = [], set()
    for row in rows:
        job = from_karirhub(row, refs)
        if job and job["id"] not in seen:
            seen.add(job["id"])
            jobs.append(job)
    complete = total > 0 and len(jobs) >= total * COMPLETE_RATIO
    log(f"Karirhub: {len(jobs)} lowongan unik dari total {total} ({'utuh' if complete else 'sebagian'})")
    return jobs, total, complete


# ---------------------------------------------------------------- situs karier perusahaan

ID_ALIASES = {
    # kata kunci lokasi -> (kota yang ditampilkan, kata kunci provinsi)
    "jakarta": ("Jakarta", "jakarta"),
    "tangerang": ("Tangerang", "banten"),
    "bsd": ("Tangerang Selatan", "banten"),
    "bekasi": ("Bekasi", "jawa barat"),
    "depok": ("Depok", "jawa barat"),
    "bogor": ("Bogor", "jawa barat"),
    "bandung": ("Bandung", "jawa barat"),
    "surabaya": ("Surabaya", "jawa timur"),
    "malang": ("Malang", "jawa timur"),
    "semarang": ("Semarang", "jawa tengah"),
    "solo": ("Surakarta", "jawa tengah"),
    "surakarta": ("Surakarta", "jawa tengah"),
    "yogyakarta": ("Yogyakarta", "yogyakarta"),
    "jogja": ("Yogyakarta", "yogyakarta"),
    "bali": ("Bali", "bali"),
    "denpasar": ("Denpasar", "bali"),
    "medan": ("Medan", "sumatera utara"),
    "batam": ("Batam", "kepulauan riau"),
    "palembang": ("Palembang", "sumatera selatan"),
    "makassar": ("Makassar", "sulawesi selatan"),
    "balikpapan": ("Balikpapan", "kalimantan timur"),
}


def indonesia_place(location: str, provinces: dict) -> tuple[str, str] | None:
    """Cari bagian lokasi yang berada di Indonesia. None jika lowongan di luar Indonesia."""
    for part in re.split(r"[;|/]", location or ""):
        low = part.lower()
        hit = next((k for k in ID_ALIASES if re.search(rf"\b{k}\b", low)), None)
        if hit:
            city, prov_key = ID_ALIASES[hit]
            prov = next((n for n in provinces.values() if prov_key in n.lower()), "")
            if not prov and prov_key == "jakarta":
                prov = "DKI Jakarta"
            return city, prov
        if "indonesia" in low:
            city = clean(part.split(",")[0])
            return ("" if city.lower() == "indonesia" else city), ""
    return None


def from_board(kind: str, company: dict, raw: dict, provinces: dict) -> dict | None:
    name = company.get("nama") or company.get("slug")
    if kind == "greenhouse":
        loc = (raw.get("location") or {}).get("name", "")
        title, link = raw.get("title"), raw.get("absolute_url")
        posted = iso_epoch(raw.get("first_published") or raw.get("updated_at"))
        work, function = "", ""
        ident = raw.get("id")
        desc = karier.html_to_text(raw.get("content") or "")
    elif kind == "lever":
        cats = raw.get("categories") or {}
        loc = ", ".join(filter(None, [cats.get("location"), *(cats.get("allLocations") or [])]))
        title, link = raw.get("text"), raw.get("hostedUrl")
        posted = iso_epoch(raw.get("createdAt"))
        work, function = cats.get("commitment") or "", cats.get("team") or ""
        ident = raw.get("id")
        lists = "".join(f"<h3>{x.get('text') or ''}</h3><ul>{x.get('content') or ''}</ul>" for x in raw.get("lists") or [])
        desc = karier.html_to_text((raw.get("description") or raw.get("descriptionPlain") or "") + lists
                                   + (raw.get("additional") or raw.get("additionalPlain") or ""))
    elif kind == "ashby":
        loc = ", ".join(filter(None, [raw.get("location"), *[
            (s.get("location") if isinstance(s, dict) else str(s)) for s in raw.get("secondaryLocations") or []
        ]]))
        title, link = raw.get("title"), raw.get("jobUrl")
        posted = iso_epoch(raw.get("publishedAt"))
        work, function = raw.get("employmentType") or "", raw.get("department") or ""
        ident = raw.get("id")
        desc = karier.html_to_text(raw.get("descriptionHtml") or raw.get("descriptionPlain") or "")
    else:
        return None
    place = indonesia_place(loc, provinces)
    if place is None or not title or not ident:
        return None
    work = job_type({"FullTime": "Full time", "PartTime": "Part time"}.get(work, work))
    return {
        "id": f"{kind[:2]}-{company['slug']}-{ident}",
        "title": clean(title),
        "company": clean(name),
        "logo": clean(company.get("logo") or ""),
        "city": place[0],
        "province": place[1],
        "platform": f"Karier {clean(name)}",
        "function": clean(function),
        "industry": clean(company.get("industri") or ""),
        "type": work,
        "edu": "",
        "smin": 0,
        "smax": 0,
        "posted": posted,
        "expires": 0,
        "via": f"{kind}:{company['slug']}",
        "link": clean(link),
        "desc": desc,
    }


def fetch_board(company: dict, provinces: dict):
    kind, slug = company.get("ats", "").lower(), company.get("slug", "")
    if kind == "greenhouse":
        raw = fetch(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", {"content": "true"}).get("jobs") or []
    elif kind == "lever":
        raw = fetch(f"https://api.lever.co/v0/postings/{slug}", {"mode": "json"}) or []
    elif kind == "ashby":
        raw = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{slug}").get("jobs") or []
    else:
        raise ValueError(f"ATS tidak dikenal: {kind}")
    jobs = [j for j in (from_board(kind, company, r, provinces) for r in raw) if j]
    return jobs, len(raw)


def read_companies(path: Path) -> list[dict]:
    """Semua perusahaan di perusahaan.json (termasuk yang belum punya adapter)."""
    if not path.exists():
        return []
    data = json.loads(path.read_text("utf-8"))
    rows = data.get("perusahaan", []) if isinstance(data, dict) else data
    return [c for c in rows if isinstance(c, dict) and c.get("nama")]


def load_companies(path: Path) -> list[dict]:
    """Perusahaan yang lowongannya bisa ditarik setiap hari."""
    out = []
    for c in read_companies(path):
        kind = str(c.get("ats") or "").lower()
        if kind in BOARDS and c.get("slug"):
            out.append(c)
        elif kind in karier.SUPPORTED and (c.get("url") or c.get("slug")):
            out.append(c)
    return out


# ---------------------------------------------------------------- deskripsi lowongan perusahaan

DETAIL_DIR = "detail"
# Naikkan bila pembaca deskripsi diperbaiki: deskripsi yang dulu kosong dicoba sekali lagi.
DESC_VERSION = 2
LOGO_DAYS = 30            # logo perusahaan dicek ulang setiap 30 hari
LOGO_BUDGET_SEC = 3 * 60


def shard(job_id: str) -> str:
    """Nama berkas pecahan deskripsi (00-ff), FNV-1a 32-bit. Rumus yang sama dipakai app.js."""
    h = 0x811C9DC5
    for b in job_id.encode("utf-8"):
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return f"{h & 0xFF:02x}"


def described_ids(out_dir: Path, stored: dict[str, str]) -> set[str]:
    """Id yang tidak perlu diambil lagi deskripsinya. Yang kosong dicoba ulang bila versi pembacanya baru."""
    version = read_json(out_dir / DETAIL_DIR / "_info.json", {}).get("versi", 1)
    return {k for k, v in stored.items() if v or version >= DESC_VERSION}


def read_details(out_dir: Path) -> dict[str, str]:
    """Semua deskripsi tersimpan: {id lowongan: teks}. Teks kosong berarti sudah dicoba tapi tidak ada."""
    folder = out_dir / DETAIL_DIR
    out: dict[str, str] = {}
    if folder.is_dir():
        for path in folder.glob("[0-9a-f][0-9a-f].json"):
            data = read_json(path, {})
            out.update({k: (v.get("d", "") if isinstance(v, dict) else str(v)) for k, v in data.items()})
    return out


def write_details(out_dir: Path, details: dict[str, str], now: datetime) -> None:
    folder = out_dir / DETAIL_DIR
    folder.mkdir(exist_ok=True)
    shards: dict[str, dict] = {}
    for job_id, text in details.items():
        shards.setdefault(shard(job_id), {})[job_id] = {"d": text}
    for path in folder.glob("[0-9a-f][0-9a-f].json"):
        if path.stem not in shards:
            path.unlink()
    for name, data in shards.items():
        write_json(folder / f"{name}.json", dict(sorted(data.items())))
    # Selalu ada, supaya "git add detail" di workflow tidak gagal walau belum ada deskripsi.
    write_json(folder / "_info.json", {"updated": now.isoformat(timespec="seconds"), "versi": DESC_VERSION,
                                       "jobs": sum(1 for t in details.values() if t)})


def name_key(name: str) -> str:
    """Nama perusahaan tanpa PT/Tbk/(Persero)/tanda baca, untuk mencocokkan perusahaan yang sama."""
    low = re.sub(r"\(persero\)|\bpt\b\.?|\btbk\b\.?|[^a-z0-9 ]", " ", (name or "").lower())
    return re.sub(r"\s+", " ", low).strip()


def resolve_logos(out_dir: Path, companies: list[dict], now: datetime) -> dict[str, str]:
    """Logo resmi tiap perusahaan, disimpan di detail/_logo.json dan dicek ulang setiap LOGO_DAYS hari."""
    from concurrent.futures import ThreadPoolExecutor, wait

    path = out_dir / DETAIL_DIR / "_logo.json"
    cache = read_json(path, {})
    now_ts = int(now.timestamp())
    todo = [c for c in companies if not c.get("logo") and c.get("web")
            and now_ts - int((cache.get(c["nama"]) or {}).get("t", 0)) > LOGO_DAYS * 86400]

    def one(company):
        try:
            return company["nama"], karier.find_logo(company)
        except Exception:  # noqa: BLE001
            return company["nama"], ""

    if todo:
        pool = ThreadPoolExecutor(max_workers=8)
        futures = [pool.submit(one, c) for c in todo]
        done, _ = wait(futures, timeout=LOGO_BUDGET_SEC)
        for fut in done:
            name, url = fut.result()
            cache[name] = {"url": url, "t": now_ts}
        pool.shutdown(wait=False, cancel_futures=True)
        (out_dir / DETAIL_DIR).mkdir(exist_ok=True)
        write_json(path, dict(sorted(cache.items())))
        log(f"Logo perusahaan: {sum(1 for f in done if f.result()[1])} ditemukan dari {len(todo)} dicek")
    logos = {c["nama"]: (cache.get(c["nama"]) or {}).get("url", "") for c in companies}
    for c in companies:
        if c.get("logo"):
            logos[c["nama"]] = c["logo"]
    return {k: v for k, v in logos.items() if v}


def company_via(company: dict) -> str:
    kind = company["ats"].lower()
    return f"{kind}:{company['slug']}" if kind in BOARDS else f"{kind}:{karier.source_key(company)}"


def fetch_companies(companies: list[dict], refs: dict, prev: dict, now: datetime, described: set | None = None):
    """Tarik semua situs karier perusahaan secara paralel. Mengembalikan (lowongan, sumber_utuh, ringkasan)."""
    from concurrent.futures import ThreadPoolExecutor, wait

    fresh, complete, sources = [], set(), []
    by_via: dict[str, dict] = {}
    for job in prev.values():
        if job.get("link"):
            by_via.setdefault(job["via"], {})[job["link"]] = job

    def one(company):
        if company["ats"].lower() in BOARDS:
            return fetch_board(company, refs["provinces"])
        return karier.fetch_company(company, refs, by_via.get(company_via(company)), now, described or set())

    pool = ThreadPoolExecutor(max_workers=6)
    futures = {pool.submit(one, c): c for c in companies}
    done, pending = wait(futures, timeout=COMPANY_BUDGET_SEC)
    for fut, company in futures.items():
        label = company.get("label") or company.get("nama") or company.get("slug")
        base = {"name": f"Karier {label}", "jenis": "perusahaan"}
        if fut in pending:
            log(f"! {label}: melewati batas waktu")
            sources.append({**base, "ok": False, "count": 0, "error": "melewati batas waktu"})
            continue
        try:
            jobs, raw_count = fut.result()
        except Exception as err:  # noqa: BLE001
            log(f"! {label} gagal: {err}")
            sources.append({**base, "ok": False, "count": 0, "error": str(err)[:200]})
            continue
        fresh += jobs
        complete.add(company_via(company))
        sources.append({**base, "ok": True, "count": len(jobs), "total": raw_count})
        log(f"{label}: {len(jobs)} lowongan di Indonesia dari {raw_count}")
    pool.shutdown(wait=False, cancel_futures=True)
    return fresh, complete, sources


# ---------------------------------------------------------------- penggabungan + riwayat

def merge(prev: dict, fresh: list[dict], complete: set[str], today: int, now: int):
    """Gabungkan hasil baru dengan data kemarin.

    Lowongan lama yang tidak muncul lagi dianggap ditutup hanya jika sumbernya ditarik utuh;
    kalau sumbernya gagal atau sebagian, lowongan lama dipertahankan sampai tanggal kedaluwarsanya.
    """
    out: dict[str, dict] = {}
    added = 0
    for job in fresh:
        old = prev.get(job["id"])
        job["first"] = old["first"] if old else today
        if not old:
            added += 1
        out[job["id"]] = job
    closed = 0
    for job_id, job in prev.items():
        if job_id in out:
            continue
        if job["via"] not in complete and (not job["expires"] or job["expires"] > now):
            out[job_id] = job
        else:
            closed += 1
    expired = [k for k, j in out.items() if j["expires"] and j["expires"] < now]
    for k in expired:
        del out[k]
    closed += len([k for k in expired if k in prev])
    jobs = sorted(out.values(), key=lambda j: (-j["posted"], j["title"]))
    return jobs, added, closed


def day_number(dt: datetime) -> int:
    return int(dt.strftime("%Y%m%d"))


def update_stats(stats: dict, jobs: list[dict], added: int | None, closed: int | None, now: datetime) -> dict:
    day = now.strftime("%Y-%m-%d")
    cutoff = int(now.timestamp()) - 86400
    row = {
        "d": day,
        "active": len(jobs),
        "new": added,
        "closed": closed,
        "posted24": sum(1 for j in jobs if j["posted"] >= cutoff),
        "companies": len({j["company"] for j in jobs}),
        "salaried": sum(1 for j in jobs if j["smin"] or j["smax"]),
    }
    # Penarikan kedua di hari yang sama (jadwal cadangan atau manual): jumlah baru/ditutup dijumlahkan.
    same = next((d for d in stats.get("days", []) if d.get("d") == day), None)
    if same:
        for key in ("new", "closed"):
            if same.get(key) is not None and row[key] is not None:
                row[key] += same[key]
            elif row[key] is None:
                row[key] = same.get(key)
    days = [d for d in stats.get("days", []) if d.get("d") != day]
    days.append(row)
    days = sorted(days, key=lambda d: d["d"])[-HISTORY_DAYS:]
    return {"v": FORMAT_VERSION, "days": days}


# ---------------------------------------------------------------- format berkas

def encode(jobs: list[dict], meta: dict) -> dict:
    tables = {name: {} for name in LISTS}
    logos: dict[str, str] = {}

    def ref(name: str, value: str) -> int:
        table = tables[name]
        if value not in table:
            table[value] = len(table)
        return table[value]

    rows = []
    for j in jobs:
        if j.get("logo") and j["company"] not in logos:
            logos[j["company"]] = j["logo"]
        rows.append([
            j["id"], j["title"], ref("company", j["company"]), ref("city", j["city"]),
            ref("province", j["province"]), ref("platform", j["platform"]), ref("function", j["function"]),
            ref("industry", j["industry"]), ref("type", j["type"]), ref("edu", j["edu"]),
            j["smin"], j["smax"], j["posted"], j["expires"], j["first"], ref("via", j["via"]),
        ])
    lists = {name: list(table) for name, table in tables.items()}
    lists["logo"] = [logos.get(c, "") for c in lists["company"]]
    return {"v": FORMAT_VERSION, **meta, "logoBase": LOGO_BASE, "fields": FIELDS, "lists": lists, "jobs": rows}


def decode(data: dict) -> dict[str, dict]:
    if not data or data.get("v") != FORMAT_VERSION:
        return {}
    lists = data.get("lists") or {}
    fields = data.get("fields") or FIELDS
    logos = lists.get("logo") or []
    out = {}
    for row in data.get("jobs") or []:
        rec = dict(zip(fields, row))
        for name in LISTS:
            idx = rec.get(name)
            rec[name] = lists.get(name, [])[idx] if isinstance(idx, int) and idx < len(lists.get(name, [])) else ""
        company_idx = row[fields.index("company")]
        rec["logo"] = logos[company_idx] if company_idx < len(logos) else ""
        rec.setdefault("link", "")
        out[rec["id"]] = rec
    return out


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), "utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- utama

def run(out_dir: Path, max_pages: int = MAX_PAGES, now: datetime | None = None) -> int:
    now = now or datetime.now(WIB)
    now_ts = int(now.timestamp())
    started = time.monotonic()
    jobs_path, links_path, stats_path = out_dir / "jobs.json", out_dir / "links.json", out_dir / "stats.json"

    prev_data = read_json(jobs_path, {})
    prev = decode(prev_data)
    checked = set(prev_data.get("checked") or []) if isinstance(prev_data, dict) else set()
    old_links = read_json(links_path, {})
    for job_id, job in prev.items():
        job["link"] = old_links.get(job_id, "")

    refs = load_refs()
    fresh: list[dict] = []
    complete: set[str] = set()
    sources = []

    try:
        jobs, total, whole = fetch_karirhub(refs, max_pages=max_pages)
        fresh += jobs
        if whole:
            complete.add("karirhub")
        sources.append({"name": "Karirhub Kemnaker", "ok": True, "count": len(jobs), "total": total, "complete": whole})
    except Exception as err:  # noqa: BLE001
        log(f"! Karirhub gagal: {err}")
        sources.append({"name": "Karirhub Kemnaker", "ok": False, "count": 0, "error": str(err)[:200]})

    companies = load_companies(out_dir / "perusahaan.json")
    stored = read_details(out_dir)
    logos = resolve_logos(out_dir, read_companies(out_dir / "perusahaan.json"), now)
    for company in companies:
        if logos.get(company["nama"]) and not company.get("logo"):
            company["logo"] = logos[company["nama"]]
    if companies:
        jobs, whole, company_sources = fetch_companies(companies, refs, prev, now, described_ids(out_dir, stored))
        fresh += jobs
        complete |= whole
        sources += company_sources

    if not fresh:
        log("Tidak ada data yang berhasil ditarik; berkas lama tidak diubah.")
        return 1

    checked = fill_locations(fresh, prev, checked, refs, started)

    jobs, added, closed = merge(prev, fresh, complete, day_number(now), now_ts)
    # Lowongan yang sama perusahaannya (termasuk dari Karirhub) memakai logo resmi bila belum punya logo.
    by_name = {name_key(n): url for n, url in logos.items()}
    for job in jobs:
        if not job.get("logo"):
            job["logo"] = by_name.get(name_key(job["company"]), "")
    first_run = not prev
    unresolved = {j["id"] for j in jobs if j["via"] == "karirhub" and not j["province"]}
    meta = {
        "updated": now.isoformat(timespec="seconds"),
        "sources": sources,
        # Lowongan yang detailnya sudah dicek tapi lokasinya tetap tak diketahui: tidak dicek ulang.
        "checked": sorted(i for i in checked if i in unresolved),
    }
    write_json(jobs_path, encode(jobs, meta))
    write_json(links_path, {j["id"]: j["link"] for j in jobs if j.get("link")})
    # Deskripsi lowongan situs perusahaan: yang baru ditarik, atau yang tersimpan dari hari sebelumnya.
    details = {}
    for j in jobs:
        if j["via"] == "karirhub":
            continue
        text = j["desc"] if j.get("desc") is not None else stored.get(j["id"])
        if text is not None:
            details[j["id"]] = text
    write_details(out_dir, details, now)
    stats = update_stats(read_json(stats_path, {}), jobs, None if first_run else added,
                         None if first_run else closed, now)
    write_json(stats_path, stats)

    summary = (f"Aktif {len(jobs)} · baru {added if not first_run else '-'} · "
               f"ditutup {closed if not first_run else '-'}")
    log(summary)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(f"### Tracking Loker {now:%d-%m-%Y %H.%M} WIB\n\n{summary}\n\n| Sumber | Lowongan | Status |\n|---|---|---|\n")
            for s in sources:
                fh.write(f"| {s['name']} | {s['count']} | {'OK' if s['ok'] else 'Gagal: ' + s.get('error', '')} |\n")
    return 0


def needs_run(out_dir: Path, now: datetime, event: str) -> bool:
    """Untuk jadwal cadangan: tarik hanya bila data sesi ini (pagi 04.00-15.59 / malam 16.00-03.59 WIB) belum ada."""
    if event != "schedule":
        return True
    updated = read_json(out_dir / "jobs.json", {}).get("updated")
    if not updated:
        return True
    try:
        last = datetime.fromisoformat(updated).astimezone(WIB)
    except ValueError:
        return True
    now = now.astimezone(WIB)
    if 4 <= now.hour < 16:
        start = now.replace(hour=4, minute=0, second=0, microsecond=0)
    elif now.hour >= 16:
        start = now.replace(hour=16, minute=0, second=0, microsecond=0)
    else:
        start = (now - timedelta(days=1)).replace(hour=16, minute=0, second=0, microsecond=0)
    return last < start


def check(out_dir: Path, now: datetime | None = None, only: str = "") -> int:
    """Periksa situs karier semua perusahaan dan tulis cek-karier.json (data lowongan tidak diubah)."""
    now = now or datetime.now(WIB)
    companies = read_companies(out_dir / "perusahaan.json")
    if only:
        wanted = {x.strip().lower() for x in only.split(",")}
        companies = [c for c in companies if str(c.get("kode", "")).lower() in wanted
                     or c["nama"].lower() in wanted or str(c.get("slug", "")).lower() in wanted]
    log(f"Cek situs karier {len(companies)} perusahaan")
    refs = load_refs()
    results = karier.check_all(companies, refs)
    ok = sum(1 for r in results if any(u.get("ok") and u.get("indonesia") for u in r.get("uji", [])))
    report = {"diperiksa": now.isoformat(timespec="seconds"), "jumlah": len(results), "berhasil": ok, "hasil": results}
    path = out_dir / "cek-karier.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    log(f"Selesai: {ok} dari {len(results)} perusahaan sudah menghasilkan lowongan. Hasil di {path.name}")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(f"### Cek situs karier {now:%d-%m-%Y %H.%M} WIB\n\n{ok} dari {len(results)} perusahaan "
                     f"menghasilkan lowongan.\n\n| Perusahaan | Situs | Platform | Lowongan |\n|---|---|---|---|\n")
            for r in results:
                site = next((s for s in r.get("situs", []) if s.get("status") == 200), None)
                best = max((u.get("indonesia", 0) for u in r.get("uji", []) if u.get("ok")), default=0)
                fh.write(f"| {r.get('kode') or '-'} {r['nama']} | {site['status'] if site else 'gagal'} | "
                         f"{', '.join(r.get('terdeteksi', {})) or '-'} | {best} |\n")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Tarik lowongan harian untuk Tracking Loker.")
    parser.add_argument("--out", type=Path, default=HERE, help="folder tujuan jobs.json / links.json / stats.json")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES, help="batas halaman Karirhub (untuk uji cepat)")
    parser.add_argument("--cek", action="store_true", help="periksa situs karier perusahaan, tulis cek-karier.json")
    parser.add_argument("--hanya", default="", help="dengan --cek: kode/nama perusahaan, pisahkan dengan koma")
    parser.add_argument("--perlu", action="store_true",
                        help="cetak jalan=true/false: apakah jadwal ini perlu menarik (untuk $GITHUB_OUTPUT)")
    args = parser.parse_args(argv)
    if args.perlu:
        run_now = needs_run(args.out, datetime.now(WIB), os.environ.get("EVENT", "schedule"))
        print(f"jalan={'true' if run_now else 'false'}")
        print("Data sesi ini sudah ada, penarikan dilewati." if not run_now else "Menarik data.", file=sys.stderr)
        return 0
    if args.cek:
        return check(args.out, only=args.hanya)
    return run(args.out, max_pages=args.max_pages)


if __name__ == "__main__":
    sys.exit(main())
